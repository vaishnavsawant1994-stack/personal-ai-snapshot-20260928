from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from models.contracts import HandoffContext


class InvalidHandoff(ValueError):
    pass


def build_handoff(*, execution_id: str, agent_id: str, task_id: str, goal: str, current_plan: dict, current_task: dict, project_id: str | None = None, completed_tasks=(), failed_tasks=(), blocked_tasks=(), success_criteria=(), important_context: str = '', files_read=(), files_changed=(), tool_results=None, decisions=(), constraints=(), project_instructions: str = '', relevant_memory=(), previous_model: str | None = None, previous_provider: str | None = None, next_model: str | None = None, next_provider: str | None = None, handoff_reason: str = '', token_budget_remaining: int | None = None, cost_budget_remaining: float | None = None, verification_state=None, checkpoint_reference: str | None = None) -> HandoffContext:
    for name, value in {'execution_id': execution_id, 'agent_id': agent_id, 'task_id': task_id}.items():
        if not str(value or '').strip():
            raise InvalidHandoff(f'{name} is required')
    return HandoffContext(
        execution_id=str(execution_id), agent_id=str(agent_id), task_id=str(task_id), project_id=str(project_id) if project_id else None,
        goal=str(goal or '')[:4000], current_plan=dict(current_plan or {}), current_task=dict(current_task or {}),
        completed_tasks=tuple(map(str, completed_tasks or ())), failed_tasks=tuple(map(str, failed_tasks or ())), blocked_tasks=tuple(map(str, blocked_tasks or ())),
        success_criteria=tuple(str(item)[:1000] for item in (success_criteria or ())), important_context=str(important_context or '')[:24000],
        files_read=tuple(str(item)[:1000] for item in (files_read or ())), files_changed=tuple(str(item)[:1000] for item in (files_changed or ())),
        tool_results=dict(tool_results or {}), decisions=tuple(str(item)[:2000] for item in (decisions or ())), constraints=tuple(str(item)[:2000] for item in (constraints or ())),
        project_instructions=str(project_instructions or '')[:12000], relevant_memory=tuple(str(item)[:4000] for item in (relevant_memory or ())),
        previous_model=previous_model, previous_provider=previous_provider, next_model=next_model, next_provider=next_provider,
        handoff_reason=str(handoff_reason or '')[:1000], token_budget_remaining=token_budget_remaining, cost_budget_remaining=cost_budget_remaining,
        verification_state=dict(verification_state or {}), checkpoint_reference=checkpoint_reference,
    )


def handoff_prompt(handoff: HandoffContext) -> str:
    """Serialize the minimum execution state for a replacement intelligence resource.

    The envelope is context only; it never grants tool permissions or approvals.
    """
    payload: dict[str, Any] = asdict(handoff)
    return (
        'VISHNU MODEL HANDOFF — trusted execution-state metadata, not authorization.\n'
        'Continue the same agent/task. Do not claim unverified work completed and do not bypass tools, approvals, policy, budgets, or verification.\n'
        + json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    )


def public_handoff(handoff: HandoffContext) -> dict[str, Any]:
    data = asdict(handoff)
    # Tool outputs can contain private data; expose only their keys in activity/audit projections.
    data['tool_results'] = sorted(str(key) for key in handoff.tool_results)
    data['important_context'] = ''
    data['project_instructions'] = ''
    data['relevant_memory'] = []
    return data
