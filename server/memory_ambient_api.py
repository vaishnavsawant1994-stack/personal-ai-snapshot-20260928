from __future__ import annotations

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
        candidates = governed.candidates(status='pending', limit=200, owner_id='owner')
        rows = memory.search('', limit=1000)
        # Respect the existing device sensitivity policy before returning any records.
        # Candidate and memory visibility is already owner-scoped by the canonical stores;
        # sensitive records still follow the device authorization used by Memory APIs.
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, 'memory:sensitive'):
            rows = [row for row in rows if str(row.get('sensitivity') or '').lower() not in {'sensitive', 'secret'}]
        events = [safe_event(item) for item in memory.audit_entries(limit=500)
                  if item.get('category') in {'owner-product', 'memory'} and
                  ('memory' in str(item.get('action') or '') or 'candidate' in str(item.get('action') or ''))][:100]
        return {'settings': governed.ambient_settings(owner_id='owner'), 'candidates': candidates,
                'memories': rows, 'activity': events}

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

    return router
