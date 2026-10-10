from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request
from server.project_work_api import ProjectWorkService


class AgentWorkRequestBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=200)
    playbook_id: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9_-]+$")


def agent_work_requests_router(runtime) -> APIRouter:
    """Explicit specialist-chat -> canonical Project Work handoff.

    This endpoint creates/plans Work only. It never directly executes a tool,
    grants approval, promotes evidence, or declares completion. Any subsequent
    execution continues through the existing Project autonomy/P10/P6 authority.
    """

    router = APIRouter(prefix="/iphone/api/agents", tags=["agent-work-requests"])
    registry = runtime["device_registry"]

    def authenticate(device_id: str | None, token: str | None):
        if not device_id or not token:
            raise HTTPException(401, "Owner device sign-in required")
        try:
            authenticated = registry.authenticate(device_id, token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        if authenticated is False:
            raise HTTPException(401, "This browser is not trusted or its session was revoked")
        if hasattr(registry, "authorize") and not registry.authorize(device_id, "ai:chat"):
            raise HTTPException(403, "This device is not permitted to use the agent workforce")
        context = current_trusted_request()
        if context is None or context.device_id != device_id:
            raise HTTPException(401, "A current trusted owner session is required to create Work")
        return context

    def workforce():
        value = runtime.get("agent_workforce")
        if value is None:
            raise HTTPException(503, "Agent workforce is unavailable")
        return value

    def project_store():
        value = runtime.get("project_store")
        if value is None:
            raise HTTPException(503, "Projects are unavailable")
        return value

    @router.post("/{template_id}/work-requests", status_code=201)
    def create_work_request(
        template_id: str,
        body: AgentWorkRequestBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        context = authenticate(pa_device, pa_token)
        wf = workforce()
        try:
            template = wf.store.get_template(template_id)
        except KeyError as exc:
            raise HTTPException(404, "Agent not found") from exc
        project = project_store().get(body.project_id)
        if not project or project.get("status") == "archived":
            raise HTTPException(404, "Project not found")

        conversation = None
        if body.conversation_id:
            try:
                conversation = wf.chat_store.get(body.conversation_id)
            except KeyError as exc:
                raise HTTPException(404, "Agent conversation not found") from exc
            if conversation["project_id"] != body.project_id:
                raise HTTPException(403, "Agent conversation belongs to another Project")
            if conversation["template_id"] != template_id:
                raise HTTPException(403, "Agent conversation belongs to another specialist")
            wf.chat_store.append(body.conversation_id, role="user", content=body.prompt)

        query = (
            "DIRECT SPECIALIST WORK REQUEST\n"
            f"Requested specialist: {template['name']}\n"
            f"Requested role: {template['role']}\n"
            f"Owner request: {body.prompt}\n"
            "Create bounded canonical Work for this Project. Prefer the requested specialist for matching WorkOrders, "
            "but preserve dependency, capability, evidence, approval, budget and verification rules. Do not expand Project scope."
        )[:4000]
        service = ProjectWorkService(runtime, project_store())
        try:
            result = service.create_plan(
                body.project_id,
                query=query,
                playbook_id=body.playbook_id,
                force_new_goal=False,
                session_id=context.session_id,
            )
            projection = wf.reconcile_project_work(body.project_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

        message = (
            f"Canonical Project Work {'created' if result.get('created') else 'updated'} for this request. "
            "Vishnu remains execution authority; tools, approvals, Evidence and completion continue through the governed Work runtime."
        )
        assistant_message = None
        if conversation is not None:
            assistant_message = wf.chat_store.append(
                body.conversation_id,
                role="assistant",
                content=message,
                provider="vishnu-work-orchestrator",
                model_id="canonical-work",
            )
        if wf.events is not None:
            wf.events.emit(
                "agent.work_request.created",
                template_id=template_id,
                project_id=body.project_id,
                conversation_id=body.conversation_id,
                created=bool(result.get("created")),
                authority=False,
            )
        return {
            "project_id": body.project_id,
            "template_id": template_id,
            "conversation_id": body.conversation_id,
            "message": message,
            "assistant_message": assistant_message,
            "work": result,
            "team": projection.get("assignments", []),
            "unmapped_work_orders": projection.get("unmapped", []),
            "execution_authority": False,
            "tool_authority": False,
            "completion_authority": False,
        }

    return router
