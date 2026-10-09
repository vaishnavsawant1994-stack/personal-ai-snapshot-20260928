from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approvals.projection import ApprovalsProjection
from future_intelligence.work_orchestration.attention import WorkAttentionService
from security.request_context import current_trusted_request


def approvals_center_router(runtime):
    """Read transport for Approvals Center; Stage-2 endpoints own decisions."""
    router = APIRouter(prefix='/iphone/api/approvals-center', tags=['approvals-center'])
    registry = runtime['device_registry']
    manager = runtime['agent_executor'].approvals
    projection = ApprovalsProjection(manager)
    project_store = runtime.get('project_store')
    try:
        attention = WorkAttentionService(runtime, project_store) if project_store is not None else None
    except RuntimeError:
        attention = None

    def require_owner():
        context = current_trusted_request()
        if context is None: raise HTTPException(401, 'Trusted owner session required')
        if not registry.is_active(context.device_id): raise HTTPException(401, 'Trusted device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to inspect governed approvals')
        return context

    def attention_by_approval(context):
        if attention is None:
            return {}
        try:
            snapshot = attention.summary(
                owner_id='owner',
                device_id=context.device_id,
                session_id=context.session_id,
                limit=200,
            )
        except RuntimeError:
            return {}
        return {
            str(item.get('approval_id')): item
            for item in snapshot.get('items') or []
            if item.get('kind') == 'approval_required' and item.get('approval_id')
        }

    @staticmethod
    def enrich(item, context_item):
        result = dict(item)
        if not context_item:
            result['work_context_available'] = False
            return result
        result.update({
            'work_context_available': True,
            'project_id': context_item.get('project_id'),
            'project_name': context_item.get('project_name'),
            'goal_id': context_item.get('goal_id'),
            'plan_id': context_item.get('plan_id'),
            'plan_version': context_item.get('plan_version'),
            'work_order_id': context_item.get('work_order_id'),
            'work_order_title': context_item.get('work_order_title'),
            'worker_type': context_item.get('worker_type'),
            'reason': context_item.get('reason'),
            'expected_effect': context_item.get('expected_effect'),
            'deep_link': context_item.get('deep_link'),
            'attention_id': context_item.get('id'),
            'attention_severity': context_item.get('severity'),
        })
        return result

    @router.get('')
    def approval_list(limit: int = Query(default=50, ge=1, le=100)):
        context = require_owner()
        work_context = attention_by_approval(context)
        items = projection.pending(owner_id='owner', device_id=context.device_id, session_id=context.session_id, limit=limit)
        return {
            'authority': 'approval_manager',
            'decision_endpoint_authority': 'stage_2_approval_api',
            'approvals': [enrich(item, work_context.get(str(item.get('approval_id')))) for item in items],
        }

    @router.get('/{approval_id}')
    def approval_detail(approval_id: str):
        context = require_owner()
        item = projection.detail(approval_id, owner_id='owner', device_id=context.device_id, session_id=context.session_id)
        if item is None: raise HTTPException(404, {'code':'approval_not_found','message':'This approval is missing or unavailable.'})
        work_context = attention_by_approval(context)
        return enrich(item, work_context.get(str(approval_id)))

    return router
