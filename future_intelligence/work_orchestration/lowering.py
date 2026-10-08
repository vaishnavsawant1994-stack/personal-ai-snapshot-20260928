from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .models import GoalSpec, WorkOrder, WorkPlan, WorkPlanStatus


def lower_to_p10_tasks(plan: WorkPlan, goal: GoalSpec) -> list[dict[str, Any]]:
    """Lower a reviewed WorkPlan into untrusted P10 task data.

    This function cannot grant tool authority. P10/P6/AgentExecutor continue to
    re-validate capabilities, policy, approval, risk, scope and verification.
    """
    parent_caps = set(str(item) for item in goal.resource_scope.metadata.get("allowed_capabilities", []))
    tasks: list[dict[str, Any]] = []
    for order in plan.work_orders:
        if parent_caps and not set(order.allowed_capabilities).issubset(parent_caps):
            raise PermissionError("work order expands parent capabilities")
        requested_tool = str(order.resource_scope.metadata.get("requested_tool") or "").strip()
        parameters = order.resource_scope.metadata.get("parameters")
        if not isinstance(parameters, Mapping):
            parameters = {}
        verification_required = bool(order.verification_strategy.get("required")) or bool(
            order.evidence_contract.requirements
        )
        tasks.append(
            {
                "id": order.id,
                "objective": order.objective,
                "dependencies": list(order.dependencies),
                "required_capabilities": list(order.allowed_capabilities),
                "requested_tool": requested_tool or None,
                "parameters": dict(parameters),
                "depth": 1,
                "risk": str(goal.resource_scope.metadata.get("risk") or "low"),
                "privacy": goal.data_classification,
                "consequential": bool(order.approval_policy.get("required")),
                "approval_required": bool(order.approval_policy.get("required")),
                "verification_required": verification_required,
                "retry_limit": max(0, min(int(order.retry_policy.get("max_retries", 0)), 3)),
            }
        )
    return tasks


def bind_to_projection(candidate: WorkPlan, projected: WorkPlan) -> WorkPlan:
    """Attach strategic plan semantics to the mutable P10 execution projection."""
    projected_by_task: dict[str, WorkOrder] = {}
    for order in projected.work_orders:
        task_id = str(order.resource_scope.metadata.get("p10_task_id") or "")
        if task_id:
            projected_by_task[task_id] = order

    id_map: dict[str, str] = {}
    for order in candidate.work_orders:
        base = projected_by_task.get(order.id)
        if base is None:
            raise KeyError(f"projection missing P10 task {order.id}")
        id_map[order.id] = base.id

    bound_orders: list[WorkOrder] = []
    for order in candidate.work_orders:
        base = projected_by_task[order.id]
        bound_orders.append(
            replace(
                order,
                id=base.id,
                plan_id=projected.id,
                project_id=projected.project_id or candidate.project_id,
                status=base.status,
                dependencies=tuple(id_map[dependency] for dependency in order.dependencies),
                workflow_id=base.workflow_id,
                workflow_run_id=base.workflow_run_id,
                created_at=base.created_at,
                updated_at=base.updated_at,
            )
        )

    bound_milestones = tuple(
        replace(
            milestone,
            work_order_ids=tuple(id_map[order_id] for order_id in milestone.work_order_ids),
        )
        for milestone in candidate.milestones
    )
    initial_status = (
        WorkPlanStatus.DEGRADED
        if candidate.status is WorkPlanStatus.DEGRADED
        else projected.status
    )
    return WorkPlan(
        id=projected.id,
        goal_id=projected.goal_id,
        project_id=projected.project_id or candidate.project_id,
        version=projected.version,
        summary=candidate.summary,
        milestones=bound_milestones,
        work_orders=tuple(bound_orders),
        assumptions=candidate.assumptions,
        evidence_contract=candidate.evidence_contract,
        critic={
            **dict(projected.critic),
            **dict(candidate.critic),
            "hierarchical_planning": True,
            "source_p10_plan_id": projected.id,
        },
        readiness=candidate.readiness,
        status=initial_status,
        supersedes_plan_id=projected.supersedes_plan_id,
        created_at=projected.created_at,
    )
