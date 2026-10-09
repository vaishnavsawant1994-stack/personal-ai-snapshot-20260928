from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from future_intelligence.work_orchestration.models import (
    EvidenceContract,
    ExecutionBudget,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_STATUS = {
    "started": WorkOrderStatus.RUNNING,
    "step.completed": WorkOrderStatus.RUNNING,
    "approval_required": WorkOrderStatus.WAITING_APPROVAL,
    "recovery_required": WorkOrderStatus.RECOVERY_REQUIRED,
    "failed": WorkOrderStatus.FAILED,
    "cancelled": WorkOrderStatus.CANCELLED,
    "budget_exceeded": WorkOrderStatus.BLOCKED,
    "completed": WorkOrderStatus.COMPLETED,
}


class AutomationWorkBridge:
    """Stable automation occurrence -> canonical Work projection.

    Existing AutomationEngine definitions, budgets and approval semantics remain
    authoritative for workflow execution. Each concrete occurrence receives one
    deterministic Work identity for global visibility, history and convergence.
    """

    mode = "canonical_occurrence_projection"

    def __init__(self, *, engine, work_store, events) -> None:
        self.engine = engine
        self.work = work_store
        self.events = events
        self._subscriptions = []
        for suffix in (
            "started",
            "step.completed",
            "approval_required",
            "recovery_required",
            "failed",
            "cancelled",
            "budget_exceeded",
            "completed",
        ):
            self._subscriptions.append(events.subscribe(f"workflow.{suffix}", self._on_event))

    def close(self) -> None:
        for unsubscribe in self._subscriptions:
            try:
                unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()

    def _run(self, run_id: str) -> dict[str, Any]:
        try:
            return dict(self.engine._run(run_id))
        except Exception:
            return {"id": run_id}

    def _workflow(self, workflow_id: str) -> dict[str, Any]:
        try:
            return dict(self.engine.workflow(workflow_id))
        except Exception:
            return {"id": workflow_id, "title": "Automation workflow", "trigger": {}, "steps": []}

    @staticmethod
    def _suffix(event_name: str) -> str:
        return str(event_name).removeprefix("workflow.")

    def _identity(self, run: dict[str, Any]) -> str:
        # User-supplied idempotency keys are already unique per workflow. If an
        # older occurrence has no key, the durable run id remains stable.
        return str(run.get("idempotency_key") or run.get("id") or "unknown")[:160]

    def _on_event(self, event: dict[str, Any]) -> None:
        run_id = str(event.get("run_id") or "").strip()
        workflow_id = str(event.get("workflow_id") or "").strip()
        if not run_id or not workflow_id:
            return
        try:
            self.record(run_id, workflow_id, event_type=self._suffix(str(event.get("event") or "")))
        except Exception as exc:
            self.events.emit(
                "automation.work_projection_failed",
                run_id=run_id,
                workflow_id=workflow_id,
                error_type=type(exc).__name__,
            )

    def record(self, run_id: str, workflow_id: str, *, event_type: str) -> dict[str, str]:
        run = self._run(run_id)
        workflow = self._workflow(workflow_id)
        occurrence = self._identity(run)
        suffix = _slug("automation", workflow_id, occurrence)
        goal_id = f"goal-auto-{suffix}"
        plan_id = f"plan-auto-{suffix}"
        order_id = f"work-auto-{suffix}"
        stamp = str(run.get("started_at") or _now())
        status = _STATUS.get(event_type, WorkOrderStatus.RUNNING)
        title = str(workflow.get("title") or "Automation workflow")[:160]
        trigger = dict(workflow.get("trigger") or {})
        objective = f"Run automation workflow: {title}"
        goal = GoalSpec(
            id=goal_id,
            title=title,
            objective=objective,
            desired_outcome=f"Complete the scheduled or triggered workflow occurrence {occurrence}",
            success_criteria=("workflow occurrence reaches its governed terminal state",),
            resource_scope=ResourceScope(
                metadata={
                    "automation_workflow_id": workflow_id,
                    "automation_run_id": run_id,
                    "occurrence_identity": occurrence,
                    "trigger_type": trigger.get("type"),
                    "authority": "automation_engine",
                }
            ),
            budget=ExecutionBudget(max_attempts=1),
            approval_policy={"authority": "existing_automation_governance"},
            created_from="automation_occurrence",
            created_at=stamp,
            updated_at=_now(),
        )
        order = WorkOrder(
            id=order_id,
            plan_id=plan_id,
            title=title,
            objective=objective,
            worker_type="automation",
            status=status,
            resource_scope=goal.resource_scope,
            expected_output="governed workflow result",
            evidence_contract=EvidenceContract(require_review=False),
            verification_strategy={
                "authority": "automation_engine",
                "workflow_run_id": run_id,
                "terminal_event": event_type,
            },
            approval_policy={"authority": "automation_engine"},
            retry_policy={"authority": "automation_budget_manager"},
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            created_at=stamp,
            updated_at=_now(),
        )
        terminal = status in {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}
        failed = status in {WorkOrderStatus.FAILED, WorkOrderStatus.BLOCKED, WorkOrderStatus.RECOVERY_REQUIRED}
        plan = WorkPlan(
            id=plan_id,
            goal_id=goal_id,
            version=1,
            summary=objective,
            work_orders=(order,),
            critic={
                "projection": "automation_occurrence",
                "execution_authority": "automation_engine",
                "canonical_work_identity": True,
            },
            readiness=ReadinessStatus.HOLD if failed else ReadinessStatus.READY,
            status=(
                WorkPlanStatus.COMPLETED
                if status is WorkOrderStatus.COMPLETED
                else WorkPlanStatus.CANCELLED
                if status is WorkOrderStatus.CANCELLED
                else WorkPlanStatus.HOLD
                if failed
                else WorkPlanStatus.RUNNING
            ),
            created_at=stamp,
        )
        self.work.upsert_goal(goal)
        self.work.save_plan(plan)
        try:
            self.work.append_work_event(
                order_id,
                f"automation.{event_type}",
                {"workflow_id": workflow_id, "run_id": run_id, "occurrence_identity": occurrence},
            )
        except Exception:
            # Event history is additive; a Work identity must still be visible if
            # an older schema lacks the durability event table.
            pass
        self.events.emit(
            "automation.work_projected",
            workflow_id=workflow_id,
            run_id=run_id,
            work_order_id=order_id,
            status=status.value,
        )
        return {"goal_id": goal_id, "plan_id": plan_id, "work_order_id": order_id}
