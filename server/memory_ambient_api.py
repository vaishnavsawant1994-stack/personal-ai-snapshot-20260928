from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from security.request_context import current_trusted_request


class AmbientSettingsPatch(BaseModel):
    enabled: bool | None = None
    sources: dict[str, bool] | None = None
    pause_until: float | None = None
    retention: str | None = None


class ConversationExclusion(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200)


def memory_ambient_router(runtime):
    router = APIRouter(prefix='/iphone/api/memory/ambient', tags=['memory-ambient'])
    registry = runtime['device_registry']
    governed = runtime['second_brain']
    memory = runtime['memory']
    continuity = runtime.get('continuity')
    projects = runtime.get('project_store')
    knowledge = runtime.get('knowledge')
    knowledge_store = runtime.get('knowledge_store')

    def require_owner(scope: str):
        context = current_trusted_request()
        if context is None or not registry.is_active(context.device_id):
            raise HTTPException(401, 'Trusted owner session required')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return context

    @router.get('')
    def overview():
        context = require_owner('memory:read')
        governed.expire_ambient_memories(owner_id='owner')
        candidates = governed.candidates(status='pending', limit=200, owner_id='owner')
        rows = memory.search('', limit=1000)
        # Respect the existing device sensitivity policy before returning any records.
        # Candidate and memory visibility is already owner-scoped by the canonical stores;
        # sensitive records still follow the device authorization used by Memory APIs.
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, 'memory:sensitive'):
            rows = [row for row in rows if str(row.get('sensitivity') or '').lower() not in {'sensitive', 'secret'}]
        project_cache = {}
        def source_label(metadata):
            project_id, source_id = str(metadata.get('project_id') or ''), str(metadata.get('source_id') or '')
            if project_id and projects is not None:
                if project_id not in project_cache:
                    project_cache[project_id] = projects.get(project_id)
                project = project_cache.get(project_id)
                if not project: return ''
                if metadata.get('ambient_source') == 'files':
                    file = next((item for item in project.get('files', []) if str(item.get('id')) == source_id), None)
                    return str(file.get('title') or 'Project file') if file else ''
                return str(project.get('name') or 'Project')
            if metadata.get('ambient_source') == 'files' and knowledge_store is not None and source_id:
                document = knowledge_store.detail(source_id, include_history=False)
                if document and document.get('access_class') in allowed_knowledge_classes(context.device_id):
                    return str(document.get('title') or document.get('filename') or 'Knowledge file')
            return ''
        for item in candidates:
            item['source_label'] = source_label(item.get('candidate', {}).get('metadata') or {})
        for item in rows:
            try: item['source_label'] = source_label(json.loads(item.get('metadata_json') or '{}'))
            except (TypeError, ValueError): item['source_label'] = ''
        events = [safe_event(item) for item in memory.audit_entries(limit=500)
                  if item.get('category') in {'owner-product', 'memory'} and
                  ('memory' in str(item.get('action') or '') or 'candidate' in str(item.get('action') or ''))][:100]
        return {'settings': governed.ambient_settings(owner_id='owner'), 'candidates': candidates,
                'memories': rows, 'activity': events}

    @router.post('/scan')
    def scan_enabled_sources():
        """Generate review-only candidates from owner-authorized project/file sources."""
        context = require_owner('memory:write')
        settings = governed.ambient_settings(owner_id='owner')
        if not settings.get('enabled') or not settings.get('memory_enabled'):
            raise HTTPException(409, 'Enable Ambient Memory and Memory before scanning sources')
        if settings.get('pause_until') and float(settings['pause_until']) > __import__('time').time():
            raise HTTPException(409, 'Ambient Memory capture is paused')
        if projects is None:
            if not settings['sources'].get('files') or runtime.get('knowledge_store') is None:
                raise HTTPException(503, 'Project sources are not available on this installation')
        model_router = getattr(governed._brain, 'models', None)
        if model_router is None or (hasattr(model_router, 'eligible_providers') and not model_router.eligible_providers('json', 'sensitive')):
            raise HTTPException(503, 'No configured model is allowed to process private memory sources')
        created = 0
        scanned_projects = scanned_files = 0
        for summary in (projects.list(status='all') if projects is not None else [])[:60]:
            project_id = str(summary.get('id') or '')
            if not project_id or summary.get('is_walkthrough'):
                continue
            project = projects.get(project_id)
            if not project:
                continue
            if settings['sources'].get('projects') and governed.ambient_can_capture('projects', owner_id='owner'):
                pieces = [project.get(key) for key in ('name', 'goal', 'description', 'success_criteria', 'context_notes')]
                for item in (project.get('tasks') or [])[:80]:
                    pieces.extend((item.get('title'), item.get('description'), item.get('context_notes')))
                for item in (project.get('milestones') or [])[:40]:
                    pieces.extend((item.get('title'), item.get('outcome'), item.get('completion_criteria')))
                text = '\n'.join(str(part).strip() for part in pieces if str(part or '').strip())[:24000]
                if text:
                    scanned_projects += 1
                    candidates = governed._brain.extract_candidates(text, sensitivity='sensitive')
                    for candidate in candidates:
                        candidate_id = governed.remember_ambient(candidate, source_type='projects', project_id=project_id,
                            source_id=project_id, owner_id='owner')
                        created += int(bool(candidate_id))
            if settings['sources'].get('files') and governed.ambient_can_capture('files', owner_id='owner'):
                for item in (project.get('files') or [])[:100]:
                    if item.get('kind') == 'link' or item.get('indexing_state') not in {'indexed', 'ready'}:
                        continue
                    indexed = projects.file_index(project_id, str(item.get('id') or ''))
                    text = str((indexed or {}).get('extracted_text') or '').strip()[:24000]
                    if not text:
                        continue
                    scanned_files += 1
                    candidates = governed._brain.extract_candidates('Source document: ' + str(item.get('title') or 'Project file') + '\n' + text, sensitivity='sensitive')
                    for candidate in candidates:
                        candidate_id = governed.remember_ambient(candidate, source_type='files', project_id=project_id,
                            source_id=str(item['id']), owner_id='owner')
                        created += int(bool(candidate_id))
        if settings['sources'].get('files') and knowledge_store is not None and knowledge is not None and governed.ambient_can_capture('files', owner_id='owner'):
            allowed = allowed_knowledge_classes(context.device_id)
            for document in knowledge.list(limit=100, owner_id='owner', access_classes=allowed):
                detail = knowledge_store.detail(str(document.get('id') or ''), include_history=False)
                text = '\n'.join(str(chunk.get('content') or '') for chunk in (detail or {}).get('chunks', [])[:60])[:24000]
                if not text.strip():
                    continue
                scanned_files += 1
                candidates = governed._brain.extract_candidates('Source document: ' + str(document.get('title') or document.get('filename') or 'Knowledge file') + '\n' + text, sensitivity='sensitive')
                for candidate in candidates:
                    candidate_id = governed.remember_ambient(candidate, source_type='files', source_id=str(document['id']), owner_id='owner')
                    created += int(bool(candidate_id))
        if created:
            memory.audit('owner-product', 'memory.ambient.sources_scanned', {
                'device_id': context.device_id, 'candidates_created': created,
                'projects_scanned': scanned_projects, 'files_scanned': scanned_files,
            })
        return {'candidates_created': created, 'projects_scanned': scanned_projects,
                'files_scanned': scanned_files, 'requires_owner_review': True}

    @router.patch('/settings')
    def update_settings(body: AmbientSettingsPatch):
        context = require_owner('memory:write')
        # Explicit null is meaningful for pause_until: it clears an active pause.
        changes = body.model_dump(exclude_unset=True)
        try:
            settings = governed.update_ambient_settings(changes, owner_id='owner')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        memory.audit('owner-product', 'memory.ambient.settings_updated',
                     {'device_id': context.device_id, 'changed': sorted(changes)})
        return settings

    @router.post('/exclusions')
    def exclude_conversation(body: ConversationExclusion):
        context = require_owner('memory:write')
        if continuity is None or continuity.thread(body.conversation_id) is None:
            raise HTTPException(404, 'Conversation not found')
        try:
            settings = governed.exclude_conversation(body.conversation_id, owner_id='owner')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        memory.audit('owner-product', 'memory.ambient.conversation_excluded',
                     {'device_id': context.device_id, 'conversation_id': body.conversation_id})
        return settings

    @router.delete('/exclusions/{conversation_id}')
    def include_conversation(conversation_id: str):
        context = require_owner('memory:write')
        settings = governed.include_conversation(conversation_id, owner_id='owner')
        memory.audit('owner-product', 'memory.ambient.conversation_included',
                     {'device_id': context.device_id, 'conversation_id': conversation_id})
        return settings

    @router.get('/activity')
    def activity(limit: int = 100):
        context = require_owner('memory:read')
        safe_limit = max(1, min(int(limit), 200))
        events = [safe_event(item) for item in memory.audit_entries(limit=1000)
                  if item.get('category') in {'owner-product', 'memory'} and
                  ('memory' in str(item.get('action') or '') or 'candidate' in str(item.get('action') or ''))]
        return {'activity': events[:safe_limit]}

    def safe_event(item):
        # The Ambient activity view needs labels and timestamps only. Never
        # return arbitrary audit payloads that could contain private content.
        return {key: item[key] for key in ('id', 'category', 'action', 'created_at') if key in item}

    def allowed_knowledge_classes(device_id):
        classes = {'owner', 'trusted-devices'}
        if hasattr(registry, 'authorize') and registry.authorize(device_id, 'knowledge:private'):
            classes.add('private')
        return classes

    return router
