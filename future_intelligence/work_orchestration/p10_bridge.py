from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from evidence import (
    Claim,
    ClaimGate,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    EvidenceStore,
    VerificationState,
)
from .durable_store import DurableWorkStore
from .models import (
    EvidenceContract,
    EvidenceRequirement,
    ExecutionBudget,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)


def _iso(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(timezone.utc).isoformat()


_PLAN_STATUS = {
    "CREATED": WorkPlanStatus.DRAFT,
    "VALIDATING": WorkPlanStatus.REVIEWING,
    "READY": WorkPlanStatus.READY,
    "WAITING": WorkPlanStatus.RUNNING,
    "WAITING_APPROVAL": WorkPlanStatus.RUNNING,
    "RUNNING": WorkPlanStatus.RUNNING,
    "VERIFYING": WorkPlanStatus.RUNNING,
    "RECOVERING": WorkPlanStatus.DEGRADED,
    "PAUSED": WorkPlanStatus.HOLD,
    "BLOCKED": WorkPlanStatus.HOLD,
    "COMPLETED": WorkPlanStatus.COMPLETED,
    "FAILED": WorkPlanStatus.HOLD,
    "CANCELLED": WorkPlanStatus.CANCELLED,
    "UNCERTAIN": WorkPlanStatus.HOLD,
}

_ORDER_STATUS = {
    "WAITING": WorkOrderStatus.QUEUED,
    "READY": WorkOrderStatus.QUEUED,
    "RUNNING": WorkOrderStatus.RUNNING,
    "WAITING_APPROVAL": WorkOrderStatus.WAITING_APPROVAL,
    "WAITING_RESOURCE": WorkOrderStatus.WAITING_RESOURCE,
    "RETRYING": WorkOrderStatus.RETRYING,
    "VERIFYING": WorkOrderStatus.VERIFYING,
    "RECOVERING": WorkOrderStatus.RECOVERY_REQUIRED,
    "BLOCKED": WorkOrderStatus.BLOCKED,
    "PAUSED": WorkOrderStatus.PAUSED,
    "UNCERTAIN": WorkOrderStatus.RECOVERY_REQUIRED,
    "COMPLETED": WorkOrderStatus.COMPLETED,
    "FAILED": WorkOrderStatus.FAILED,
    "CANCELLED": WorkOrderStatus.CANCELLED,
}


class P10WorkBridge:
    """Observe-only bridge from the qualified P10 runtime into Work/Evidence.

    DurableWorkStore is intentionally a drop-in persistence upgrade here: it
    installs attempt/lease/event/workspace schema and exposes durability APIs,
    while this bridge remains observe-only and does not take execution authority
    away from the existing P10 runtime.
    """

    mode = "observe_only"

    def __init__(self, connection: sqlite3.Connection, *, lock: RLock | None = None) -> None:
        self.connection = connection
        self.lock = lock or RLock()
        self.work = DurableWorkStore(connection=connection)
        self.evidence = EvidenceStore(connection=connection)

    def project_goal(self, p10_goal: dict[str, Any]) -> GoalSpec:
        description = str(p10_goal.get("description") or "").strip()
        if not description:
            raise ValueError("P10 goal description required for projection")
        desired = str(p10_goal.get("desired_outcome") or "").strip() or description
        title = description.splitlines()[0][:160] or "P10 goal"
        spec = GoalSpec(
            id=str(p10_goal["id"]),
            project_id=p10_goal.get("project_id"),
            title=title,
            objective=description,
            desired_outcome=desired,
            deliverables=tuple(str(x) for x in p10_goal.get("deliverables", [])[:30]),
            success_criteria=tuple(str(x) for x in p10_goal.get("success_criteria", [])[:30]),
            constraints=tuple(str(x) for x in p10_goal.get("constraints", [])[:30]),
            resource_scope=ResourceScope(
                metadata={
                    "allowed_capabilities": list(p10_goal.get("allowed_capabilities") or []),
                    "prohibited_actions": list(p10_goal.get("prohibited_actions") or []),
                    "authority": "p10_existing_runtime",
                }
            ),
            priority=int(p10_goal.get("priority", 50)),
            deadline=p10_goal.get("deadline"),
            data_classification=str(p10_goal.get("privacy") or "internal"),
            budget=ExecutionBudget(max_attempts=1),
            approval_policy={"authority": "existing_runtime", "projection_mode": self.mode},
            created_from="p10",
            created_at=_iso(p10_goal.get("created_at")),
            updated_at=_iso(p10_goal.get("updated_at")),
        )
        with self.lock:
            return self.work.upsert_goal(spec, source_p10_goal_id=str(p10_goal["id"]))

    def project_plan(
        self,
        p10_plan: dict[str, Any],
        p10_goal: dict[str, Any],
        *,
        force_new_version: bool = False,
    ) -> WorkPlan:
        goal = self.project_goal(p10_goal)
        source_plan_id = str(p10_plan["id"])
        with self.lock:
            existing = self.work.latest_plan_for_source(source_plan_id)
            if existing is not None and not force_new_version:
                version = existing.version
                work_plan_id = existing.id
                supersedes = existing.supersedes_plan_id
                created_at = existing.created_at
            else:
                version = self.work.next_plan_version(goal.id)
                work_plan_id = source_plan_id if version == 1 else f"{source_plan_id}:v{version}"
                supersedes = existing.id if existing is not None else None
                created_at = _iso(p10_plan.get("created_at"))

        p10_tasks = list(p10_plan.get("tasks") or [])
        work_orders: list[WorkOrder] = []
        for task in p10_tasks:
            task_id = str(task.get("id") or "")
            if not task_id:
                continue
            status = _ORDER_STATUS.get(str(task.get("status") or "").upper(), WorkOrderStatus.QUEUED)
            work_orders.append(
                WorkOrder(
                    id=task_id,
                    plan_id=work_plan_id,
                    project_id=goal.project_id,
                    project_task_id=task_id,
                    title=str(task.get("title") or task.get("description") or task_id)[:200],
                    objective=str(task.get("description") or task.get("title") or task_id),
                    worker_type=str(task.get("worker_type") or task.get("tool") or "p10"),
                    status=status,
                    priority=int(task.get("priority", goal.priority)),
                    dependencies=tuple(str(x) for x in task.get("dependencies", []) if str(x)),
                    allowed_capabilities=tuple(str(x) for x in task.get("allowed_capabilities", []) if str(x)),
                    resource_scope=ResourceScope(
                        metadata={
                            "authority": "p10_existing_runtime",
                            "projection_mode": self.mode,
                        }
                    ),
                    expected_output=str(task.get("expected_output") or ""),
                    success_criteria=tuple(str(x) for x in task.get("success_criteria", []) if str(x)),
                    evidence_contract=EvidenceContract(
                        requirements=(
                            EvidenceRequirement(kind="verified_execution", required=True, min_count=1),
                        ),
                        require_review=True,
                    ),
                    verification_strategy={"authority": "existing_runtime"},
                    approval_policy={"authority": "existing_runtime"},
                    retry_policy={"authority": "existing_runtime"},
                    time_budget_seconds=task.get("time_budget_seconds"),
                    cost_budget=task.get("cost_budget"),
                    workflow_id=p10_plan.get("workflow_id"),
                    workflow_run_id=p10_plan.get("workflow_run_id"),
                    created_at=_iso(task.get("created_at") or p10_plan.get("created_at")),
                    updated_at=_iso(task.get("updated_at") or p10_plan.get("updated_at")),
                )
            )

        status = _PLAN_STATUS.get(str(p10_plan.get("status") or "").upper(), WorkPlanStatus.DRAFT)
        readiness = (
            ReadinessStatus.READY
            if status in {WorkPlanStatus.READY, WorkPlanStatus.RUNNING, WorkPlanStatus.COMPLETED}
            else ReadinessStatus.DEGRADED
            if status is WorkPlanStatus.DEGRADED
            else ReadinessStatus.HOLD
        )
        plan = WorkPlan(
            id=work_plan_id,
            goal_id=goal.id,
            version=version,
            summary=str(p10_plan.get("summary") or p10_plan.get("title") or goal.title),
            project_id=goal.project_id,
            work_orders=tuple(work_orders),
            assumptions=tuple(str(x) for x in p10_plan.get("assumptions", []) if str(x)),
            evidence_contract=EvidenceContract(
                requirements=(EvidenceRequirement(kind="verified_execution", required=True),),
                require_review=True,
            ),
            critic={"authority": "p10_existing_runtime", "projection_mode": self.mode},
            readiness=readiness,
            status=status,
            supersedes_plan_id=supersedes,
            created_at=created_at,
        )
        with self.lock:
            return self.work.save_plan(plan, source_p10_plan_id=source_plan_id)

    def backfill(self) -> dict[str, int]:
        goals = int(self.connection.execute("SELECT COUNT(*) FROM work_goals").fetchone()[0])
        plans = int(self.connection.execute("SELECT COUNT(*) FROM work_plans").fetchone()[0])
        return {"goals": goals, "plans": plans}

    def work_plan_for_p10(self, plan_id: str) -> WorkPlan | None:
        return self.work.latest_plan_for_source(str(plan_id))

    def observe_governed_completion(
        self,
        p10_plan: dict[str, Any],
        p10_goal: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any] | None:
        plan = self.project_plan(p10_plan, p10_goal)
        task_id = str(task.get("id") or "")
        order = next((item for item in plan.work_orders if item.project_task_id == task_id or item.id == task_id), None)
        if order is None:
            return None
        result = task.get("result") or {}
        verified = bool(result.get("verified"))
        observation = str(
            result.get("verification_reason")
            or result.get("reason")
            or ("P10 task completion was verified" if verified else "P10 task completion is unverified")
        )
        evidence_id = f"ev:{hashlib.sha256(f'{plan.id}:{task_id}:{json.dumps(result, sort_keys=True, default=str)}'.encode()).hexdigest()[:24]}"
        evidence = Evidence(
            id=evidence_id,
            project_id=order.project_id,
            goal_id=plan.goal_id,
            plan_id=plan.id,
            work_order_id=order.id,
            worker_run_id=str(task.get("worker_run_id") or "") or None,
            tool_name=str(task.get("tool") or "") or None,
            source_type="p10_governed_completion",
            source="p10_runtime",
            subject=f"work_order:{order.id}",
            observation=observation,
            provenance=EvidenceProvenance.TOOL_VERIFIED if verified else EvidenceProvenance.OBSERVED,
            verification_state=VerificationState.VERIFIED if verified else VerificationState.UNVERIFIED,
            verification_reason=observation,
            confidence=1.0 if verified else 0.5,
            data_classification=str(p10_goal.get("privacy") or "internal"),
        )
        claim_id = f"claim:{hashlib.sha256(f'{plan.id}:{task_id}:completion'.encode()).hexdigest()[:24]}"
        claim = Claim(
            id=claim_id,
            project_id=order.project_id,
            work_order_id=order.id,
            text=f"Work order {order.id} completed successfully",
            state=ClaimState.VERIFIED if verified else ClaimState.PROPOSED,
            confidence=1.0 if verified else 0.25,
        )
        with self.lock:
            try:
                self.evidence.record_evidence(evidence)
            except sqlite3.IntegrityError:
                pass
            try:
                self.evidence.create_claim(claim)
            except sqlite3.IntegrityError:
                pass
            try:
                self.evidence.link_evidence(claim.id, evidence.id)
            except sqlite3.IntegrityError:
                pass
            gate = ClaimGate(self.evidence)
            report = gate.evaluate(claim.id, order.evidence_contract)
        return {
            "mode": self.mode,
            "work_order_id": order.id,
            "evidence_id": evidence.id,
            "claim_id": claim.id,
            "claim_state": report.claim_state.value,
            "passed": report.passed,
        }

    def evidence_for_task(self, plan_id: str, task_id: str) -> list[Evidence]:
        plan = self.work_plan_for_p10(plan_id)
        if plan is None:
            return []
        order = next((item for item in plan.work_orders if item.project_task_id == str(task_id) or item.id == str(task_id)), None)
        if order is None:
            return []
        return self.evidence.list_evidence(work_order_id=order.id)

    def status(self) -> dict[str, Any]:
        work = self.work.status()
        evidence = len(self.evidence.list_evidence())
        claims = len(self.evidence.list_claims())
        return {
            "mode": self.mode,
            **work,
            "evidence": evidence,
            "claims": claims,
            "durability_schema": 3,
        }
