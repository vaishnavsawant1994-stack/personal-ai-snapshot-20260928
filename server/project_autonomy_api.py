from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from projects.autonomy_modes import ProjectAutonomyMode
from security.request_context import current_trusted_request


class ProjectAutonomyModeBody(BaseModel):
    mode: Literal["shadow", "assisted", "active"]
    advance_now: bool = False
    max_steps: int = Field(default=10, ge=1, le=20)


class ProjectAutonomyAdvanceBody(BaseModel):
    max_steps: int = Field(default=10, ge=1, le=20)


class ProjectAutonomyService:
    """Owner-controlled Project operating mode over the existing P10/P6 runtime.

    This service stores only mode policy and invokes existing AdvancedAutonomy
    execution methods. It owns no tool, approval, verification, recovery, or
    completion authority.
    """

    def __init__(self, runtime: dict, store) -> None:
        self.runtime = runtime
        self.store = store

    def _autonomy(self):
        autonomy = self.runtime.get("advanced_autonomy")
        if autonomy is None:
            raise RuntimeError("advanced autonomy runtime unavailable")
        if getattr(autonomy, "project_store", None) is not self.store:
            autonomy.project_store = self.store
        required = ("project_autonomy_mode", "set_project_autonomy_mode", "advance_project_plan")
        if not all(hasattr(autonomy, name) for name in required):
            raise RuntimeError("Project autonomy mode runtime unavailable")
        return autonomy

    def _project(self, project_id: str) -> dict:
        project = self.store.get(str(project_id))
        if not project or project.get("status") == "archived":
            raise KeyError("project not found")
        return project

    def _latest_plan_id(self, project_id: str) -> str | None:
        autonomy = self._autonomy()
        records = autonomy._work_bridge.work.project_plan_records(str(project_id))
        for record in reversed(records):
            source = record.get("source_p10_plan_id")
            if source:
                return str(source)
        return None

    def assert_project_plan(self, project_id: str, plan_id: str) -> None:
        self._project(project_id)
        autonomy = self._autonomy()
        records = autonomy._work_bridge.work.project_plan_records(str(project_id))
        if not any(str(record.get("source_p10_plan_id") or "") == str(plan_id) for record in records):
            raise KeyError("project work plan not found")

    @staticmethod
    def _semantics(mode: str) -> dict:
        return {
            "shadow": {
                "plans": True,
                "manual_execution": False,
                "automatic_execution": False,
                "description": "Vishnu may plan and evaluate this Project, but Project Work execution is disabled.",
            },
            "assisted": {
                "plans": True,
                "manual_execution": True,
                "automatic_execution": False,
                "description": "Vishnu may execute owner-triggered qualified WorkOrders through existing safeguards.",
            },
            "active": {
                "plans": True,
                "manual_execution": True,
                "automatic_execution": True,
                "description": "Vishnu may auto-advance ready qualified WorkOrders through the existing governed runtime.",
            },
        }[mode]

    def get(self, project_id: str) -> dict:
        project = self._project(project_id)
        settings = self._autonomy().project_autonomy_mode(project["id"])
        mode = str(settings["mode"])
        return {
            **settings,
            "project_name": project.get("name"),
            "semantics": self._semantics(mode),
            "execution_authority": "existing_p10_p6_runtime",
            "approval_authority": "existing_approval_manager",
            "recovery_authority": "existing_recovery_authority",
            "completion_authority": "deterministic_completion_judge",
            "emergency_stop_authoritative": True,
        }

    def set(
        self,
        project_id: str,
        mode: str,
        *,
        device_id: str,
        session_id: str,
        reauthenticated_at: float | None,
        advance_now: bool = False,
        max_steps: int = 10,
    ) -> dict:
        project = self._project(project_id)
        resolved = ProjectAutonomyMode(str(mode))
        settings = self._autonomy().set_project_autonomy_mode(project["id"], resolved.value, updated_by="owner")
        response = {
            **self.get(project["id"]),
            "in_flight_note": (
                "Changing mode does not duplicate, cancel, or retry an already-dispatched external effect; "
                "existing verification/recovery authority resolves in-flight work."
            ),
            "advance": None,
        }
        if advance_now:
            if resolved is not ProjectAutonomyMode.ACTIVE:
                raise ValueError("advance_now requires active mode")
            plan_id = self._latest_plan_id(project["id"])
            if plan_id:
                response["advance"] = self._autonomy().advance_project_plan(
                    plan_id,
                    owner_id="owner",
                    device_id=device_id,
                    session_id=session_id,
                    reauthenticated_at=reauthenticated_at,
                    max_steps=max_steps,
                )
            else:
                response["advance"] = {
                    "project_id": project["id"],
                    "mode": settings["mode"],
                    "executed_task_ids": [],
                    "stop_reason": "no_work_plan",
                    "execution_authority": "existing_p10_p6_runtime",
                }
        return response

    def advance(
        self,
        project_id: str,
        plan_id: str,
        *,
        device_id: str,
        session_id: str,
        reauthenticated_at: float | None,
        max_steps: int = 10,
    ) -> dict:
        self.assert_project_plan(project_id, plan_id)
        return self._autonomy().advance_project_plan(
            plan_id,
            owner_id="owner",
            device_id=device_id,
            session_id=session_id,
            reauthenticated_at=reauthenticated_at,
            max_steps=max_steps,
        )


def project_autonomy_router(runtime: dict, store) -> APIRouter:
    router = APIRouter(prefix="/iphone/api/projects", tags=["projects-autonomy"])
    service = ProjectAutonomyService(runtime, store)
    registry = runtime["device_registry"]

    def authenticate(device_id: str | None, token: str | None, *, require_trusted_session: bool = False):
        if not device_id or not token:
            raise HTTPException(401, "Owner device sign-in required")
        try:
            registry.authenticate(device_id, token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        if require_trusted_session:
            context = current_trusted_request()
            if context is None or context.device_id != device_id:
                raise HTTPException(401, "Active trusted owner session required")
            return context
        return None

    def translate(exc: Exception):
        if isinstance(exc, KeyError):
            raise HTTPException(404, str(exc).strip("'")) from exc
        if isinstance(exc, PermissionError):
            raise HTTPException(403, str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from exc
        if isinstance(exc, RuntimeError):
            raise HTTPException(409, str(exc)) from exc
        raise exc

    @router.get("/{project_id}/work/autonomy")
    def get_mode(project_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        try:
            return service.get(project_id)
        except Exception as exc:
            return translate(exc)

    @router.put("/{project_id}/work/autonomy")
    def set_mode(project_id: str, body: ProjectAutonomyModeBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        context = authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.set(
                project_id,
                body.mode,
                device_id=context.device_id,
                session_id=context.session_id,
                reauthenticated_at=context.reauthenticated_at,
                advance_now=body.advance_now,
                max_steps=body.max_steps,
            )
        except Exception as exc:
            return translate(exc)

    @router.post("/{project_id}/work/{plan_id}/advance")
    def advance(project_id: str, plan_id: str, body: ProjectAutonomyAdvanceBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        context = authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.advance(
                project_id,
                plan_id,
                device_id=context.device_id,
                session_id=context.session_id,
                reauthenticated_at=context.reauthenticated_at,
                max_steps=body.max_steps,
            )
        except Exception as exc:
            return translate(exc)

    return router
