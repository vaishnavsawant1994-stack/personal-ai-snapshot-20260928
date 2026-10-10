from __future__ import annotations

from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from visual_intelligence.deep_repository import DeepGitHubRepositoryAnalyzer
from visual_intelligence.file_sources import decode_file_payload, extract_source_text
from visual_intelligence.github_repository import GitHubRepositoryAnalyzer
from visual_intelligence.models import VisualMode, VisualType
from visual_intelligence.native_maps import build_knowledge_graph, build_live_work_graph, build_memory_graph


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


class FileVisualBody(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    content_base64: str = Field(min_length=1, max_length=9_000_000)
    title: str | None = Field(default=None, max_length=160)
    type: VisualType = VisualType.ARCHITECTURE
    mode: VisualMode = VisualMode.MANUAL


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


class EditBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=1200)


class KnowledgeMapBody(BaseModel):
    title: str = Field(default='Knowledge Map', min_length=1, max_length=160)
    query: str = Field(default='', max_length=1000)
    limit: int = Field(default=120, ge=1, le=250)


class MemoryMapBody(BaseModel):
    title: str = Field(default='Memory Map', min_length=1, max_length=160)
    node_type: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=150, ge=1, le=500)
    include_sensitive: bool = False


class LiveWorkMapBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=160)


def visualizations_router(runtime):
    router = APIRouter(prefix='/iphone/api/visualizations', tags=['visualize'])
    service = runtime['visual_intelligence']
    registry = runtime['device_registry']
    projects = runtime.get('project_store')
    continuity = runtime.get('continuity')
    knowledge = runtime.get('knowledge')
    life_graph = runtime.get('second_brain_life_graph')
    repository_analyzer = GitHubRepositoryAnalyzer()
    deep_repository_analyzer = DeepGitHubRepositoryAnalyzer()

    def require_owner(pa_device: str | None, pa_token: str | None) -> str:
        if not pa_device or not pa_token or not registry.authenticate(pa_device, pa_token):
            raise HTTPException(401, 'Vishnu owner session is not enrolled or has been revoked')
        if not registry.is_active(pa_device):
            raise HTTPException(401, 'Vishnu owner device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(pa_device, 'ai:chat'):
            raise HTTPException(403, 'This device cannot access Visualize')
        return 'owner'

    def has_scope(device_id: str | None, scope: str) -> bool:
        if not device_id:
            return False
        if not hasattr(registry, 'authorize'):
            return True
        return bool(registry.authorize(device_id, scope))

    def require_scope(device_id: str | None, scope: str):
        if not device_id:
            raise HTTPException(401, 'Trusted device is required')
        if not has_scope(device_id, scope):
            raise HTTPException(403, f'This device cannot access {scope}')

    def not_found(exc: KeyError):
        raise HTTPException(404, 'Visualization not found') from exc

    def graph_metadata(item: dict[str, Any]) -> dict[str, Any]:
        graph = item.get('graph') or {}
        metadata = graph.get('metadata') if isinstance(graph, dict) else {}
        return dict(metadata or {})

    def required_visual_scopes(item: dict[str, Any]) -> list[str]:
        source_kind = str(item.get('source_kind') or '')
        metadata = graph_metadata(item)
        scopes: list[str] = []
        if source_kind == 'knowledge':
            scopes.append('knowledge:read')
            access_classes = {str(value) for value in (metadata.get('access_classes') or [])}
            if 'private' in access_classes:
                scopes.append('knowledge:private')
        elif source_kind == 'memory':
            scopes.append('memory:read')
            sensitivities = {str(value) for value in (metadata.get('allowed_sensitivities') or ['normal'])}
            if sensitivities.intersection({'sensitive', 'secret'}):
                scopes.append('memory:sensitive')
        return scopes

    def can_access_visual(item: dict[str, Any], device_id: str | None) -> bool:
        return all(has_scope(device_id, scope) for scope in required_visual_scopes(item))

    def enforce_visual_access(item: dict[str, Any], device_id: str | None) -> dict[str, Any]:
        for scope in required_visual_scopes(item):
            require_scope(device_id, scope)
        return item

    def get_authorized_visual(owner_id: str, visual_id: str, device_id: str | None) -> dict[str, Any]:
        item = service.get(owner_id, visual_id)
        if item is None:
            raise HTTPException(404, 'Visualization not found')
        return enforce_visual_access(item, device_id)

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
        rows = service.list(owner_id, project_id=project_id, limit=limit)
        return {'visualizations': [item for item in rows if can_access_visual(item, pa_device)]}

    @router.post('')
    def create_visual(body: VisualCreateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        title = body.title
        description = body.description
        context = dict(body.context)
        visual_type = body.type
        source_ref = body.source_ref
        graph = body.graph
        if body.source_kind == 'project' and body.project_id and graph is None:
            project_name, native_context = project_visual_context(body.project_id)
            context = {**native_context, **context}
            visual_type = VisualType.PROJECT_MAP
            source_ref = source_ref or body.project_id
            if title.casefold() in {'untitled visual', 'project map'}:
                title = f'{project_name} · Project Map'
        elif body.source_kind == 'conversation' and body.conversation_id and graph is None:
            conversation_title, native_description = conversation_description(body.conversation_id)
            description = description.strip() or native_description
            source_ref = source_ref or body.conversation_id
            if title.casefold() in {'untitled visual', 'conversation'}:
                title = conversation_title
        elif body.source_kind == 'github' and source_ref and graph is None:
            try:
                depth = str(context.get('analysis_depth') or 'deep').casefold()
                repository_graph = (
                    repository_analyzer.analyze(source_ref, title=None if title.casefold() == 'untitled visual' else title)
                    if depth == 'tree'
                    else deep_repository_analyzer.analyze(source_ref, title=None if title.casefold() == 'untitled visual' else title)
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            graph = repository_graph
            visual_type = VisualType.ARCHITECTURE
            title = repository_graph.title
        try:
            return {'visualization': service.create(
                owner_id=owner_id,
                title=title,
                visual_type=visual_type,
                mode=body.mode,
                description=description,
                context=context,
                graph=graph,
                project_id=body.project_id,
                conversation_id=body.conversation_id,
                source_kind=body.source_kind,
                source_ref=source_ref,
            )}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/from-file')
    def create_visual_from_file(body: FileVisualBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        try:
            raw = decode_file_payload(body.filename, body.content_base64)
            description, metadata = extract_source_text(body.filename, raw)
            title = str(body.title or PurePath(body.filename).stem or 'File visual').strip()[:160]
            item = service.create(owner_id=owner_id, title=title, visual_type=body.type, mode=body.mode, description=description, context={'file': metadata}, source_kind='files', source_ref=body.filename)
            return {'visualization': item, 'source': metadata}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/knowledge-map')
    def create_knowledge_map(body: KnowledgeMapBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        require_scope(pa_device, 'knowledge:read')
        if knowledge is None:
            raise HTTPException(503, 'Knowledge store is unavailable')
        access_classes = {'owner', 'trusted-devices'}
        if has_scope(pa_device, 'knowledge:private'):
            access_classes.add('private')
        graph = build_knowledge_graph(knowledge, access_classes=access_classes, query=body.query, limit=body.limit, title=body.title)
        return {'visualization': service.create(owner_id=owner_id, title=body.title, visual_type=VisualType.PROJECT_MAP, mode=VisualMode.SNAPSHOT, graph=graph, source_kind='knowledge', source_ref=body.query or 'all-authorized-knowledge')}

    @router.post('/memory-map')
    def create_memory_map(body: MemoryMapBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        require_scope(pa_device, 'memory:read')
        if life_graph is None:
            raise HTTPException(503, 'Second Brain Life Graph is unavailable')
        allowed = {'normal'}
        if body.include_sensitive:
            require_scope(pa_device, 'memory:sensitive')
            allowed.update({'sensitive', 'secret'})
        payload = life_graph.graph(type=body.node_type, limit=body.limit, allowed_sensitivities=allowed)
        graph = build_memory_graph(payload, title=body.title)
        graph.metadata['allowed_sensitivities'] = sorted(allowed)
        return {'visualization': service.create(owner_id=owner_id, title=body.title, visual_type=VisualType.PROJECT_MAP, mode=VisualMode.SNAPSHOT, graph=graph, source_kind='memory', source_ref=body.node_type or 'life-graph')}

    @router.post('/live-work-map')
    def create_live_work_map(body: LiveWorkMapBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        if projects is None:
            raise HTTPException(503, 'Project workspace is unavailable')
        project = projects.get(body.project_id)
        if not project:
            raise HTTPException(404, 'Project not found')
        graph = build_live_work_graph(project, title=body.title)
        return {'visualization': service.create(owner_id=owner_id, title=graph.title, visual_type=VisualType.PROJECT_MAP, mode=VisualMode.LIVE, graph=graph, project_id=body.project_id, source_kind='live_work', source_ref=body.project_id)}

    @router.post('/compare')
    def compare(body: CompareBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, body.before_id, pa_device)
        get_authorized_visual(owner_id, body.after_id, pa_device)
        try:
            return service.compare(owner_id, body.before_id, body.after_id)
        except KeyError as exc:
            not_found(exc)

    @router.get('/{visual_id}')
    def get_visual(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        return {'visualization': get_authorized_visual(owner_id, visual_id, pa_device)}

    @router.patch('/{visual_id}')
    def patch_visual(visual_id: str, body: VisualPatchBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return {'visualization': service.update(owner_id, visual_id, title=body.title, mode=body.mode, graph=body.graph, reason=body.reason)}
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete('/{visual_id}')
    def delete_visual(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        if not service.delete(owner_id, visual_id):
            raise HTTPException(404, 'Visualization not found')
        return {'ok': True}

    @router.post('/{visual_id}/edit')
    def edit_visual(visual_id: str, body: EditBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.edit(owner_id, visual_id, body.instruction)
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/{visual_id}/repair')
    def repair_visual(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.repair(owner_id, visual_id)
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/{visual_id}/refresh')
    def refresh_visual(visual_id: str, body: VisualRefreshBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        current = get_authorized_visual(owner_id, visual_id, pa_device)
        context = dict(body.context)
        description = body.description

        if current.get('source_kind') == 'project' and current.get('project_id'):
            _, native_context = project_visual_context(current['project_id'])
            context = {**native_context, **context}
        elif current.get('source_kind') == 'conversation' and current.get('conversation_id') and description is None:
            _, description = conversation_description(current['conversation_id'])
        elif current.get('source_kind') == 'github' and current.get('source_ref'):
            try:
                graph = deep_repository_analyzer.analyze(current['source_ref'], title=current['title'])
                return {'visualization': service.update(owner_id, visual_id, graph=graph.to_dict(), reason=body.reason or 'deep repository refresh')}
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif current.get('source_kind') == 'live_work' and current.get('project_id'):
            if projects is None:
                raise HTTPException(503, 'Project workspace is unavailable')
            project = projects.get(current['project_id'])
            if not project:
                raise HTTPException(404, 'Project not found')
            graph = build_live_work_graph(project, title=current['title'])
            return {'visualization': service.update(owner_id, visual_id, graph=graph.to_dict(), reason=body.reason or 'live-work refresh')}
        elif current.get('source_kind') == 'knowledge':
            require_scope(pa_device, 'knowledge:read')
            if knowledge is None:
                raise HTTPException(503, 'Knowledge store is unavailable')
            metadata = graph_metadata(current)
            original_access = {str(value) for value in (metadata.get('access_classes') or ['owner', 'trusted-devices'])}
            access_classes = {'owner', 'trusted-devices'}
            if 'private' in original_access:
                require_scope(pa_device, 'knowledge:private')
                access_classes.add('private')
            source_ref = str(current.get('source_ref') or '')
            query = '' if source_ref == 'all-authorized-knowledge' else source_ref
            graph = build_knowledge_graph(knowledge, access_classes=access_classes, query=query, limit=250, title=current['title'])
            return {'visualization': service.update(owner_id, visual_id, graph=graph.to_dict(), reason=body.reason or 'knowledge refresh')}
        elif current.get('source_kind') == 'memory':
            require_scope(pa_device, 'memory:read')
            if life_graph is None:
                raise HTTPException(503, 'Second Brain Life Graph is unavailable')
            metadata = graph_metadata(current)
            allowed = {str(value) for value in (metadata.get('allowed_sensitivities') or ['normal'])}
            if allowed.intersection({'sensitive', 'secret'}):
                require_scope(pa_device, 'memory:sensitive')
            source_ref = str(current.get('source_ref') or '')
            node_type = None if source_ref in {'', 'life-graph'} else source_ref
            payload = life_graph.graph(type=node_type, limit=500, allowed_sensitivities=allowed)
            graph = build_memory_graph(payload, title=current['title'])
            graph.metadata['allowed_sensitivities'] = sorted(allowed)
            return {'visualization': service.update(owner_id, visual_id, graph=graph.to_dict(), reason=body.reason or 'memory refresh')}

        try:
            return {'visualization': service.refresh(owner_id, visual_id, description=description, context=context, reason=body.reason)}
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('/{visual_id}/revisions')
    def revisions(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return {'revisions': service.revisions(owner_id, visual_id)}
        except KeyError as exc:
            not_found(exc)

    @router.post('/{visual_id}/reach')
    def reach(visual_id: str, body: ReachBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.reach(owner_id, visual_id, body.origin, body.direction)
        except KeyError as exc:
            raise HTTPException(404, f'Visualization or node not found: {exc.args[0]}') from exc

    @router.post('/{visual_id}/path')
    def path(visual_id: str, body: PathBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.path(owner_id, visual_id, body.source, body.target)
        except KeyError as exc:
            raise HTTPException(404, f'Visualization or node not found: {exc.args[0]}') from exc

    @router.get('/{visual_id}/presentation')
    def presentation(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.presentation(owner_id, visual_id)
        except KeyError as exc:
            not_found(exc)

    @router.get('/{visual_id}/scene')
    def scene(visual_id: str, dimension: str = Query(default='3d', pattern='^(2d|3d)$'), pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return service.scene(owner_id, visual_id, dimension=dimension)
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('/{visual_id}/export')
    def export_visual(visual_id: str, format: str = Query(default='html', pattern='^(html|svg|json|png|webp|pdf)$'), pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            data, media_type, filename = service.export(owner_id, visual_id, format)
            return Response(data, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})
        except KeyError as exc:
            not_found(exc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get('/{visual_id}/artifact', response_class=HTMLResponse)
    def artifact(visual_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        owner_id = require_owner(pa_device, pa_token)
        get_authorized_visual(owner_id, visual_id, pa_device)
        try:
            return HTMLResponse(service.artifact(owner_id, visual_id), headers={'Cache-Control': 'no-store'})
        except KeyError as exc:
            not_found(exc)

    return router
