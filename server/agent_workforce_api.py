from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from models.router import ModelError


class CustomAgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=32000)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    tools: list[str] = Field(default_factory=list, max_length=100)
    model_policy: dict = Field(default_factory=dict)


class AgentVersionBody(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    parent_version_id: str = Field(min_length=1, max_length=160)
    instructions: str = Field(default="", max_length=32000)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    tools: list[str] = Field(default_factory=list, max_length=100)
    model_policy: dict = Field(default_factory=dict)


class PromoteVersionBody(BaseModel):
    state: str = Field(min_length=1, max_length=40)
    qualification: dict = Field(default_factory=dict)


class AgentInstanceBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    version_id: str | None = Field(default=None, max_length=160)
    model_provider: str | None = Field(default=None, max_length=80)
    model_id: str | None = Field(default=None, max_length=200)


class TeamBody(BaseModel):
    requirements: dict[str, int] = Field(default_factory=dict)


class AssignmentBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    work_order_id: str = Field(min_length=1, max_length=240)


class SpecialistChatBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    work_order_id: str = Field(min_length=1, max_length=240)
    instance_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=16000)
    context: str = Field(default="", max_length=16000)
    sensitivity: str = Field(default="internal", max_length=40)


class LearningBody(BaseModel):
    version_id: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=8000)
    project_id: str | None = Field(default=None, max_length=200)
    work_order_id: str | None = Field(default=None, max_length=240)
    score: float | None = None
    evidence_ref: str | None = Field(default=None, max_length=1000)


class AgentConversationBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    instance_id: str | None = Field(default=None, max_length=160)
    title: str = Field(default="New agent chat", max_length=180)


class AgentConversationMessageBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=16000)
    project_context: str = Field(default="", max_length=16000)
    sensitivity: str = Field(default="internal", pattern="^(public|internal|sensitive|private_local)$")


def agent_workforce_router(runtime, *, prefix: str = "/owner/agents", require_loopback: bool = True) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["agent-workforce"])

    def service():
        value = runtime.get("agent_workforce") if runtime else None
        if value is None:
            raise HTTPException(503, "agent workforce unavailable")
        return value

    def owner_boundary(request: Request):
        if not require_loopback:
            return
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1"}:
            raise HTTPException(403, "Local owner operation")

    @router.get("")
    def catalog(request: Request):
        owner_boundary(request)
        return {"agents": service().catalog()}

    @router.get("/summary")
    def summary(request: Request):
        owner_boundary(request)
        return service().summary()

    @router.post("")
    def create_agent(body: CustomAgentBody, request: Request):
        owner_boundary(request)
        try:
            return service().create_custom_agent(**body.model_dump())
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/{template_id}")
    def detail(template_id: str, request: Request):
        owner_boundary(request)
        try:
            return service().detail(template_id)
        except KeyError as exc:
            raise HTTPException(404, "agent not found") from exc

    @router.post("/{template_id}/versions")
    def create_version(template_id: str, body: AgentVersionBody, request: Request):
        owner_boundary(request)
        try:
            return service().create_version(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "agent or parent version not found") from exc
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/versions/{version_id}/state")
    def promote_version(version_id: str, body: PromoteVersionBody, request: Request):
        owner_boundary(request)
        try:
            return service().promote_version(version_id, state=body.state, qualification=body.qualification)
        except KeyError as exc:
            raise HTTPException(404, "version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{template_id}/instances")
    def create_instance(template_id: str, body: AgentInstanceBody, request: Request):
        owner_boundary(request)
        try:
            return service().create_instance(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "agent or version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/projects/{project_id}/team")
    def create_team(project_id: str, body: TeamBody, request: Request):
        owner_boundary(request)
        try:
            return service().create_team(project_id, body.requirements)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/projects/{project_id}/team")
    def project_team(project_id: str, request: Request):
        owner_boundary(request)
        return {"project_id": project_id, "members": service().project_team(project_id)}

    @router.post("/instances/{instance_id}/assign")
    def assign(instance_id: str, body: AssignmentBody, request: Request):
        owner_boundary(request)
        try:
            return service().assign(instance_id, project_id=body.project_id, work_order_id=body.work_order_id)
        except KeyError as exc:
            raise HTTPException(404, "agent instance or WorkOrder not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/{template_id}/learning")
    def learning(template_id: str, body: LearningBody, request: Request):
        owner_boundary(request)
        try:
            return service().record_learning(template_id, **body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "agent or version not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{template_id}/chat")
    def specialist_chat(template_id: str, body: SpecialistChatBody, request: Request):
        owner_boundary(request)
        try:
            instance = service().store.get_instance(body.instance_id)
            if instance["template_id"] != template_id:
                raise PermissionError("instance does not belong to this agent")
            return service().specialist_proposal(**body.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "WorkOrder or agent instance not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/{template_id}/conversations")
    def conversations(template_id: str, request: Request, project_id: str = Query(min_length=1, max_length=200), limit: int = Query(default=100, ge=1, le=500)):
        owner_boundary(request)
        try:
            return {"conversations": service().list_conversations(template_id=template_id, project_id=project_id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(404, "agent not found") from exc

    @router.post("/{template_id}/conversations")
    def create_conversation(template_id: str, body: AgentConversationBody, request: Request):
        owner_boundary(request)
        try:
            return {"conversation": service().create_conversation(template_id, **body.model_dump())}
        except KeyError as exc:
            raise HTTPException(404, "agent or instance not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str, request: Request, project_id: str = Query(min_length=1, max_length=200)):
        owner_boundary(request)
        try:
            return service().conversation(conversation_id, project_id=project_id)
        except KeyError as exc:
            raise HTTPException(404, "agent conversation not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, body: AgentConversationMessageBody, request: Request):
        owner_boundary(request)
        try:
            return service().direct_chat(
                conversation_id,
                project_id=body.project_id,
                prompt=body.prompt,
                project_context=body.project_context,
                sensitivity=body.sensitivity,
            )
        except KeyError as exc:
            raise HTTPException(404, "agent conversation, instance or version not found") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ModelError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.user_message}) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
