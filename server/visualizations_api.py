from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from visual_intelligence.models import VisualMode, VisualType


class VisualCreateBody(BaseModel):
    title: str = Field(default='Untitled visual', min_length=1, max_length=160)
    type: VisualType = VisualType.ARCHITECTURE
    mode: VisualMode = VisualMode.MANUAL
    description: str = Field(default='', max_length=20000)
    context: dict[str, Any] = Field(default_factory=dict)
    graph: dict[str, Any] | None = None
    project_id: str | None = Field(default=None, max_length=120)
    conversation_id: str | None = Field(default=None, max_length=120)
    source_kind: str = Field(default='description', max_length=80)
    source_ref: str | None = Field(default=None, max_length=500)


class VisualPatchBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    mode: VisualMode | None = None
    graph: dict[str, Any] | None = None
    reason: str = Field(default='update', max_length=120)


class VisualRefreshBody(BaseModel):
    description: str | None = Field(default=None, max_length=20000)
    context: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default='refresh', max_length=120)


class ReachBody(BaseModel):
    origin: str = Field(min_length=1, max_length=160)
    direction: str = Field(default='downstream', pattern='^(upstream|downstream)$')


class PathBody(BaseModel):
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)


class CompareBody(BaseModel):
    before_id: str = Field(min_length=1, max_length=160)
    after_id: str = Field(min_length=1, max_length=160)


def visualizations_router(runtime):
    router = APIRouter(prefix='/iphone/api/visualizations', tags=['visualize'])
    service = runtime['visual_intelligence']
    registry = runtime['device_registry']
    projects = runtime.get('project_store')
    continuity = runtime.get('continuity')

    def require_owner(pa_device: str | None, pa_token: str | None) -> str:
        if not pa_device or not pa_token or not registry.authenticate(pa_device, pa_token):
            raise HTTPException(401, 'Vishnu owner session is not enrolled or has been revoked')
        if not registry.is_active(pa_device):
            raise HTTPException(401, 'Vishnu owner device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(pa_device, 'ai:chat'):
            raise HTTPException(403, 'This device cannot access Visualize')
        return 'owner'

    def not_found(exc: KeyError):
        raise HTTPException(404, 'Visualization not found') from exc

    def project_visual_context(project_id: str) -> tuple[str, dict[str, Any]]:
        if projects is None:
            raise HTTPException(503, 'Project workspace is unavailable')
        project = projects.get(project_id)
        if not project:
            raise HTTPException(404, 'Project not found')
        work = [task for task in project.get('tasks', []) if task.get('execution_run_id') or task.get('status') in {'in_progress', 'blocked', 'needs_review'}]
        agent_names = []
        for task in project.get('tasks', []):
            owner = str(task.get('owner') or '').strip()
            if owner and owner not in agent_names:
                agent_names.append(owner)
        context = {
            'goals': ([{'title': project.get('goal'), 'status': project.get('status', 'active'), 'description': project.get('success_criteria', '')}] if project.get('goal') else []),
            'tasks': project.get('tasks', []),
            'milestones': project.get('milestones', []),
            'agents': [{'name': name.title(), 'status': 'active'} for name in agent_names],
            'sources': [{'title': item.get('title'), 'status': item.get('indexing_state', 'stored'), 'kind': item.get('kind'), 'id': item.get('id')} for item in project.get('files', [])],
            'work': work,
        }
        return str(project.get('name') or 'Project'), context

    def conversation_description(conversation_id: str) -> tuple[str, str]:
        if continuity is None:
            raise HTTPException(503, 'Conversation continuity is unavailable')
        thread = continuity.thread(conversation_id)
        if not thread or thread.get('closed_at'):
            raise HTTPException(404, 'Conversation not found')
        parts = []
        for event in continuity.events_for_thread(conversation_id, limit=250):
            if event.get('kind') not in {'user_message', 'assistant_message'}:
                continue
            text = str((event.get('payload') or {}).get('text') or '').strip()
            if text:
                role = 'Owner' if event.get('kind') == 'user_message' else 'Vishnu'
                parts.append(f'{role}: {text}')
        return str(thread.get('title') or 'Conversation'), '\n'.join(parts)[-20000:]

    @router.get('')
    def list_visuals(
        project_id: str | None = Query(default=None, max_length=120),
        limit: int = Query(default=100, ge=1, le=250),
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        return {'visualizations': service.list(owner_id, project_id=project_id, limit=limit)}

    @router.post('')
    def create_visual(
        body: VisualCreateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        title = body.title
        description = body.description
        context = dict(body.context)
        visual_type = body.type
        source_ref = body.source_ref
        if body.source_kind == 'project' and body.project_id and body.graph is None:
            project_name, native_context = project_visual_context(body.project_id)
            context = {**native_context, **context}
            visual_type = VisualType.PROJECT_MAP
            source_ref = source_ref or body.project_id
            if title.casefold() in {'untitled visual', 'project map'}:
                title = f'{project_name} · Project Map'
        elif body.source_kind == 'conversation' and body.conversation_id and body.graph is None:
            conversation_title, native_description = conversation_description(body.conversation_id)
            description = description.strip() or native_description
            source_ref = source_ref or body.conversation_id
            if title.casefold() in {'untitled visual', 'conversation'}:
                title = conversation_title
        try:
            return {'visualization': service.create(owner_id=owner_id, title=title, visual_type=visual_type, mode=body.mode, description=description, context=context, graph=body.graph, project_id=body.project_id, conversation_id=body.conversation_id, source_kind=body.source_kind, source_ref=source_ref)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/compare')
    def compare(
        body: CompareBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return service.compare(owner_id, body.before_id, body.after_id)
        except KeyError as exc:
            not_found(exc)

    @router.get('/{visual_id}')
    def get_visual(
        visual_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        item = service.get(owner_id, visual_id)
        if item is None:
            raise HTTPException(404, 'Visualization not found')
        return {'visualization': item}

    @router.patch('/{visual_id}')
    def patch_visual(
        visual_id: str,
        body: VisualPatchBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return {'visualization': service.update(owner_id, visual_id, title=body.title, mode=body.mode, graph=body.graph, reason=body.reason)}
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete('/{visual_id}')
    def delete_visual(
        visual_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        if not service.delete(owner_id, visual_id):
            raise HTTPException(404, 'Visualization not found')
        return {'ok': True}

    @router.post('/{visual_id}/refresh')
    def refresh_visual(
        visual_id: str,
        body: VisualRefreshBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        current = service.get(owner_id, visual_id)
        if current is None:
            raise HTTPException(404, 'Visualization not found')
        context = dict(body.context)
        description = body.description
        if current.get('source_kind') == 'project' and current.get('project_id'):
            _, native_context = project_visual_context(current['project_id'])
            context = {**native_context, **context}
        elif current.get('source_kind') == 'conversation' and current.get('conversation_id') and description is None:
            _, description = conversation_description(current['conversation_id'])
        try:
            return {'visualization': service.refresh(owner_id, visual_id, description=description, context=context, reason=body.reason)}
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('/{visual_id}/revisions')
    def revisions(
        visual_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return {'revisions': service.revisions(owner_id, visual_id)}
        except KeyError as exc:
            not_found(exc)

    @router.post('/{visual_id}/reach')
    def reach(
        visual_id: str,
        body: ReachBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return service.reach(owner_id, visual_id, body.origin, body.direction)
        except KeyError as exc:
            raise HTTPException(404, f'Visualization or node not found: {exc.args[0]}') from exc

    @router.post('/{visual_id}/path')
    def path(
        visual_id: str,
        body: PathBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return service.path(owner_id, visual_id, body.source, body.target)
        except KeyError as exc:
            raise HTTPException(404, f'Visualization or node not found: {exc.args[0]}') from exc

    @router.get('/{visual_id}/artifact', response_class=HTMLResponse)
    def artifact(
        visual_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        owner_id = require_owner(pa_device, pa_token)
        try:
            return HTMLResponse(service.artifact(owner_id, visual_id), headers={'Cache-Control': 'no-store'})
        except KeyError as exc:
            not_found(exc)

    return router