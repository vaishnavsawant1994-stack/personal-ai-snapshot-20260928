from __future__ import annotations

import json

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field

from models.router import ModelError
from security.request_context import current_trusted_request
from server.agent_workforce_api import (
    AgentInstanceBody,
    AgentVersionBody,
    AssignmentBody,
    CustomAgentBody,
    LearningBody,
    PromoteVersionBody,
    TeamBody,
)


class AgentConversationBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    instance_id: str | None = Field(default=None, max_length=160)
    title: str = Field(default="New agent chat", max_length=180)


class AgentConversationMessageBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=16000)
    sensitivity: str = Field(default="internal", pattern="^(public|internal|sensitive|private_local)$")


def agent_workforce_pwa_router(runtime) -> APIRouter:
    """Trusted-owner PWA surface for the persistent Vishnu workforce.

    Read operations require a trusted device. Mutations additionally require the
    request-context binding installed by PwaSessionMiddleware so a copied cookie
    or stale device identity cannot mutate workforce state outside the current
    authenticated owner request.
    """

    router = APIRouter(prefix="/iphone/api/agents", tags=["agent-workforce-pwa"])
    registry = runtime["device_registry"]

    def service():
        value = runtime.get("agent_workforce")
        if value is None:
            raise HTTPException(503, "Agent workforce is unavailable")
        return value

    def authenticate(device_id: str | None, token: str | None, *, write: bool = False) -> str:
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, "This browser is not trusted or its session was revoked")
        if hasattr(registry, "authorize") and not registry.authorize(device_id, "ai:chat"):
            raise HTTPException(403, "This device is not permitted to use the agent workforce")
        context = current_trusted_request()
        if write and (context is None or context.device_id != device_id):
            raise HTTPException(401, "A current trusted owner session is required to change workforce data")
        return device_id

    def project_or_404(project_id: str) -> dict:
        store = runtime.get("project_store")
        project = store.get(project_id) if store is not None else None
        if project is None:
            raise HTTPException(404, "Project not found")
        return project

    def project_context(project: dict) -> str:
        safe = {
            "id": project.get("id"),
            "name": project.get("name"),
            "goal": project.get("goal"),
            "description": project.get("description"),
            "success_criteria": project.get("success_criteria"),
            "instructions": project.get("instructions"),
            "context_notes": project.get("context_notes"),
            "status": project.get("status"),
        }
        return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))[:16000]

    @router.get("")
    def catalog(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        return {"agents": service().catalog()}

    @router.get("/summary")
    def summary(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        return service().summary()

    @router.post("", status_code=201)
    def create_agent(
        body: CustomAgentBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        try:
            return service().create_custom_agent(**body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/{template_id}")
    def detail(
        template_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        try:
            return service().detail(template_id)
        except KeyError as exc:
            raise HTTPException(404, "Agent not found") from exc

    @router.post("/{template_id}/versions", status_code=201)
    def create_version(
        template_id: str,
        body: AgentVersionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        try:
            return service().create_version(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Agent or parent version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/versions/{version_id}/state")
    def promote_version(
        version_id: str,
        body: PromoteVersionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        try:
            return service().promote_version(version_id, state=body.state, qualification=body.qualification)
        except KeyError as exc:
            raise HTTPException(404, "Agent version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{template_id}/instances", status_code=201)
    def create_instance(
        template_id: str,
        body: AgentInstanceBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        project_or_404(body.project_id)
        try:
            return service().create_instance(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Agent or version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/projects/{project_id}/team")
    def project_team(
        project_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        project_or_404(project_id)
        return {"project_id": project_id, "members": service().project_team(project_id)}

    @router.post("/projects/{project_id}/team", status_code=201)
    def create_team(
        project_id: str,
        body: TeamBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        project_or_404(project_id)
        try:
            return service().create_team(project_id, body.requirements)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/instances/{instance_id}/assign")
    def assign(
        instance_id: str,
        body: AssignmentBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        project_or_404(body.project_id)
        try:
            return service().assign(instance_id, project_id=body.project_id, work_order_id=body.work_order_id)
        except KeyError as exc:
            raise HTTPException(404, "Agent instance or WorkOrder not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/{template_id}/learning", status_code=201)
    def learning(
        template_id: str,
        body: LearningBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        if body.project_id:
            project_or_404(body.project_id)
        try:
            return service().record_learning(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Agent or version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/{template_id}/conversations")
    def conversations(
        template_id: str,
        project_id: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=100, ge=1, le=500),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        project_or_404(project_id)
        try:
            return {"conversations": service().list_conversations(template_id=template_id, project_id=project_id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(404, "Agent not found") from exc

    @router.post("/{template_id}/conversations", status_code=201)
    def create_conversation(
        template_id: str,
        body: AgentConversationBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        project_or_404(body.project_id)
        try:
            return {"conversation": service().create_conversation(template_id, **body.model_dump())}
        except KeyError as exc:
            raise HTTPException(404, "Agent or instance not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/conversations/{conversation_id}")
    def conversation(
        conversation_id: str,
        project_id: str = Query(min_length=1, max_length=200),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        project_or_404(project_id)
        try:
            return service().conversation(conversation_id, project_id=project_id)
        except KeyError as exc:
            raise HTTPException(404, "Agent conversation not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/conversations/{conversation_id}/messages")
    def send_message(
        conversation_id: str,
        body: AgentConversationMessageBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, write=True)
        project = project_or_404(body.project_id)
        try:
            return service().direct_chat(
                conversation_id,
                project_id=body.project_id,
                prompt=body.prompt,
                project_context=project_context(project),
                sensitivity=body.sensitivity,
            )
        except KeyError as exc:
            raise HTTPException(404, "Agent conversation, instance or version not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ModelError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.user_message}) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
