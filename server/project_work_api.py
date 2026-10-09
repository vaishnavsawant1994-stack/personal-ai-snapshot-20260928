from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request


class ProjectWorkPlanBody(BaseModel):
    query: str | None = Field(default=None, max_length=4000)
    playbook_id: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9_-]+$")
    force_new_goal: bool = False


class ProjectWorkCancelBody(BaseModel):
    reason: str = Field(default="owner cancelled project work", max_length=500)


class ProjectWorkService:
    """Owner-scoped Projects projection over the qualified P10/Work runtime.

    This service owns no execution, approval, permission, verification, recovery, or
    scheduling authority. It binds Projects to the existing qualified runtime only.
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
        if getattr(autonomy, "_work_bridge", None) is None:
            raise RuntimeError("work orchestration projection unavailable")
        return autonomy

    def _project(self, project_id: str) -> dict:
        project = self.store.get(str(project_id))
        if not project or project.get("status") == "archived":
            raise KeyError("project not found")
        return project

    @staticmethod
    def _project_goal_text(project: dict) -> str:
        return str(project.get("goal") or project.get("description") or project.get("name") or "").strip()[:4000]

    @staticmethod
    def _success_criteria(project: dict) -> list[str]:
        raw = str(project.get("success_criteria") or "").strip()
        return [raw[:1000]] if raw else []

    @staticmethod
    def _constraints(project: dict) -> list[str]:
        result = []
        for key in ("instructions", "context_notes"):
            value = str(project.get(key) or "").strip()
            if value:
                result.append(value[:1000])
        return result[:10]

    @staticmethod
    def _allowed_capabilities(autonomy) -> list[str]:
        registry = getattr(autonomy, "_worker_registry", None)
        if registry is None or not hasattr(registry, "all"):
            return ["research", "coding", "browser", "files", "data", "communications", "knowledge", "project", "reviewer", "review"]
        profiles = tuple(registry.all())
        # Preserve every trusted worker role before filling the remaining P10 parent
        # capability slots with finer-grained profile capabilities. The generic
        # `tool` wrapper is intentionally not a parent capability by itself.
        result = [str(profile.id) for profile in profiles if str(profile.id) != "tool"]
        for profile in profiles:
            result.extend(str(item) for item in getattr(profile, "supported_capabilities", ()) if str(item).strip())
        return list(dict.fromkeys(result))[:50]

    def _ensure_goal(self, project: dict, *, force_new: bool = False) -> dict:
        autonomy = self._autonomy()
        bridge = autonomy._work_bridge
        desired = self._project_goal_text(project)
        if not desired:
            raise ValueError("project needs a goal or description before Vishnu can plan work")
        if not force_new:
            record = bridge.work.latest_project_goal_record(project["id"])
            if record and record.get("source_p10_goal_id"):
                try:
                    existing = autonomy.goal(record["source_p10_goal_id"], owner_id="owner")
                    if str(existing.get("description") or "").strip() == desired and existing.get("state") != "CANCELLED":
                        return existing
                except KeyError:
                    pass
        goal = autonomy.create_goal(
            desired,
            owner_id="owner",
            desired_outcome=str(project.get("success_criteria") or project.get("description") or desired)[:2000],
            constraints=self._constraints(project),
            priority=70,
            deadline=project.get("target_date"),
            privacy="internal",
            risk="low",
            allowed_capabilities=self._allowed_capabilities(autonomy),
            success_criteria=self._success_criteria(project),
        )
        # Bind the observe-only Work projection to the Project. The authoritative
        # P10 goal remains unchanged.
        bridge.project_goal({**goal, "project_id": project["id"]})
        return goal

    def create_plan(self, project_id: str, *, query: str | None = None, playbook_id: str | None = None, force_new_goal: bool = False) -> dict:
        project = self._project(project_id)
        autonomy = self._autonomy()
        goal = self._ensure_goal(project, force_new=force_new_goal)
        result = autonomy.propose_hierarchical_plan(
            goal["id"],
            owner_id="owner",
            project_id=project["id"],
            query=str(query or project.get("goal") or project.get("description") or "")[:4000],
            playbook_id=playbook_id,
        )
        if result.get("created"):
            self.store.update(project["id"], {"status": "active"})
        return {"project_id": project["id"], "goal_id": goal["id"], **result}

    def _plan_record(self, project_id: str, p10_plan_id: str | None = None) -> dict | None:
        autonomy = self._autonomy()
        records = autonomy._work_bridge.work.project_plan_records(project_id)
        if p10_plan_id is None:
            return records[-1] if records else None
        return next((record for record in records if str(record.get("source_p10_plan_id") or "") == str(p10_plan_id)), None)

    def assert_project_plan(self, project_id: str, p10_plan_id: str) -> dict:
        self._project(project_id)
        record = self._plan_record(project_id, p10_plan_id)
        if record is None:
            raise KeyError("project work plan not found")
        return record

    @staticmethod
    def _live_projection(p10_plan: dict) -> dict:
        tasks = list(p10_plan.get("tasks") or [])
        counts = Counter(str(item.get("status") or "UNKNOWN").upper() for item in tasks)
        completed = {str(item.get("id")) for item in tasks if str(item.get("status") or "").upper() == "COMPLETED"}
        ready = [
            str(item.get("id"))
            for item in tasks
            if str(item.get("status") or "").upper() == "WAITING"
            and set(str(x) for x in item.get("dependencies") or []).issubset(completed)
        ]
        return {
            "state": p10_plan.get("state"),
            "task_counts": dict(counts),
            "ready_task_ids": ready,
            "active_task_ids": [str(item.get("id")) for item in tasks if str(item.get("status") or "").upper() in {"RUNNING", "VERIFYING", "RECOVERING"}],
            "waiting_approval_task_ids": [str(item.get("id")) for item in tasks if str(item.get("status") or "").upper() == "WAITING_APPROVAL"],
            "blocked_task_ids": [str(item.get("id")) for item in tasks if str(item.get("status") or "").upper() in {"BLOCKED", "UNCERTAIN"}],
            "replan_count": int(p10_plan.get("replan_count") or 0),
            "updated_at": p10_plan.get("updated_at"),
        }

    def snapshot(self, project_id: str) -> dict:
        project = self._project(project_id)
        autonomy = self._autonomy()
        bridge = autonomy._work_bridge
        record = self._plan_record(project_id)
        base = {
            "project_id": project["id"],
            "available": True,
            "authority": "existing_p10_p6_runtime",
            "legacy_project_task_runner_preserved": True,
            "project_status": project.get("status"),
            "playbooks": autonomy.orchestration_playbooks() if hasattr(autonomy, "orchestration_playbooks") else [],
            "capability_manifest": autonomy.capability_manifest() if hasattr(autonomy, "capability_manifest") else [],
        }
        if record is None or not record.get("source_p10_plan_id"):
            goal_record = bridge.work.latest_project_goal_record(project_id)
            return {
                **base,
                "state": "not_planned",
                "goal": goal_record["goal"].to_dict() if goal_record else None,
                "p10_plan": None,
                "work_plan": None,
                "live_work": {"state": "NOT_PLANNED", "task_counts": {}, "ready_task_ids": [], "active_task_ids": [], "waiting_approval_task_ids": [], "blocked_task_ids": [], "replan_count": 0, "updated_at": None},
                "evidence": {"total": 0, "by_task": {}},
            }
        p10_plan_id = str(record["source_p10_plan_id"])
        try:
            p10_plan = autonomy.plan(p10_plan_id, owner_id="owner")
            work_plan = autonomy.work_plan(p10_plan_id, owner_id="owner")
        except KeyError:
            return {
                **base,
                "state": "projection_stale",
                "p10_plan": None,
                "work_plan": record["plan"].to_dict(),
                "live_work": {"state": "UNKNOWN", "task_counts": {}, "ready_task_ids": [], "active_task_ids": [], "waiting_approval_task_ids": [], "blocked_task_ids": [], "replan_count": 0, "updated_at": None},
                "evidence": {"total": 0, "by_task": {}},
            }
        by_task: dict[str, list[dict]] = {}
        total = 0
        for task in p10_plan.get("tasks", []):
            task_id = str(task.get("id"))
            try:
                items = autonomy.work_evidence(p10_plan_id, task_id, owner_id="owner")
            except (KeyError, RuntimeError):
                items = []
            by_task[task_id] = items
            total += len(items)
        goal = bridge.work.get_goal(work_plan["goal_id"])
        return {
            **base,
            "state": "planned",
            "goal": goal.to_dict() if goal else None,
            "p10_plan": p10_plan,
            "work_plan": work_plan,
            "live_work": self._live_projection(p10_plan),
            "evidence": {"total": total, "by_task": by_task},
        }

    def history(self, project_id: str) -> dict:
        self._project(project_id)
        autonomy = self._autonomy()
        records = autonomy._work_bridge.work.project_plan_records(project_id)
        plans = []
        for record in records:
            source = record.get("source_p10_plan_id")
            item = {"source_p10_plan_id": source, "work_plan": record["plan"].to_dict()}
            if source:
                try:
                    item["versions"] = autonomy.work_plan_versions(source, owner_id="owner") if hasattr(autonomy, "work_plan_versions") else []
                    item["deltas"] = autonomy.work_plan_deltas(source, owner_id="owner") if hasattr(autonomy, "work_plan_deltas") else []
                except (KeyError, RuntimeError):
                    item["versions"], item["deltas"] = [], []
            plans.append(item)
        return {"project_id": project_id, "plans": plans, "authority": "history_only"}

    def task_evidence(self, project_id: str, p10_plan_id: str, task_id: str) -> dict:
        self.assert_project_plan(project_id, p10_plan_id)
        return {"project_id": project_id, "plan_id": p10_plan_id, "task_id": task_id, "evidence": self._autonomy().work_evidence(p10_plan_id, task_id, owner_id="owner")}

    def execute_task(self, project_id: str, p10_plan_id: str, task_id: str, *, device_id: str, session_id: str, reauthenticated_at: float | None) -> dict:
        self.assert_project_plan(project_id, p10_plan_id)
        self._autonomy().execute_task(
            p10_plan_id,
            task_id,
            owner_id="owner",
            device_id=device_id,
            session_id=session_id,
            reauthenticated_at=reauthenticated_at,
            background=True,
        )
        return self.snapshot(project_id)

    def pause(self, project_id: str, p10_plan_id: str) -> dict:
        self.assert_project_plan(project_id, p10_plan_id)
        self._autonomy().pause(p10_plan_id, owner_id="owner")
        return self.snapshot(project_id)

    def resume(self, project_id: str, p10_plan_id: str) -> dict:
        self.assert_project_plan(project_id, p10_plan_id)
        self._autonomy().resume(p10_plan_id, owner_id="owner")
        return self.snapshot(project_id)

    def cancel(self, project_id: str, p10_plan_id: str, *, reason: str) -> dict:
        self.assert_project_plan(project_id, p10_plan_id)
        autonomy = self._autonomy()
        if hasattr(autonomy, "cancel_governed"):
            autonomy.cancel_governed(p10_plan_id, owner_id="owner", reason=reason)
        else:
            autonomy.cancel(p10_plan_id, owner_id="owner", reason=reason)
        return self.snapshot(project_id)


def project_work_router(runtime: dict, store) -> APIRouter:
    router = APIRouter(prefix="/iphone/api/projects", tags=["projects-work"])
    service = ProjectWorkService(runtime, store)
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

    def translate_error(exc: Exception):
        if isinstance(exc, KeyError):
            raise HTTPException(404, str(exc).strip("'")) from exc
        if isinstance(exc, PermissionError):
            raise HTTPException(403, str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from exc
        if isinstance(exc, RuntimeError):
            raise HTTPException(409, str(exc)) from exc
        raise exc

    @router.get("/{project_id}/work")
    def work_snapshot(project_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        try:
            return service.snapshot(project_id)
        except Exception as exc:
            return translate_error(exc)

    @router.get("/{project_id}/work/history")
    def work_history(project_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        try:
            return service.history(project_id)
        except Exception as exc:
            return translate_error(exc)

    @router.post("/{project_id}/work/plan")
    def create_work_plan(project_id: str, body: ProjectWorkPlanBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.create_plan(project_id, query=body.query, playbook_id=body.playbook_id, force_new_goal=body.force_new_goal)
        except Exception as exc:
            return translate_error(exc)

    @router.get("/{project_id}/work/{plan_id}/tasks/{task_id}/evidence")
    def task_evidence(project_id: str, plan_id: str, task_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        try:
            return service.task_evidence(project_id, plan_id, task_id)
        except Exception as exc:
            return translate_error(exc)

    @router.post("/{project_id}/work/{plan_id}/tasks/{task_id}/execute")
    def execute_task(project_id: str, plan_id: str, task_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        context = authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.execute_task(project_id, plan_id, task_id, device_id=context.device_id, session_id=context.session_id, reauthenticated_at=context.reauthenticated_at)
        except Exception as exc:
            return translate_error(exc)

    @router.post("/{project_id}/work/{plan_id}/pause")
    def pause_work(project_id: str, plan_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.pause(project_id, plan_id)
        except Exception as exc:
            return translate_error(exc)

    @router.post("/{project_id}/work/{plan_id}/resume")
    def resume_work(project_id: str, plan_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.resume(project_id, plan_id)
        except Exception as exc:
            return translate_error(exc)

    @router.post("/{project_id}/work/{plan_id}/cancel")
    def cancel_work(project_id: str, plan_id: str, body: ProjectWorkCancelBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, require_trusted_session=True)
        try:
            return service.cancel(project_id, plan_id, reason=body.reason)
        except Exception as exc:
            return translate_error(exc)

    return router
