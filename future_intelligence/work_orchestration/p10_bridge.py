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
    """Compatibility bridge from P10 documents into canonical Work/Evidence.

    Direct construction remains observe-only for backwards compatibility. E9's
    `P10CanonicalWorkAuthority` promotes the same bridge to `canonical_authority`
    before runtime backfill/dispatch; the bridge never grants tool permissions.
    """

    mode = "observe_only"

    def __init__(self, connection: sqlite3.Connection, *, lock: RLock | None = None) -> None:
        self.connection = connection
        self.lock = lock or RLock()
        self.work = DurableWorkStore(connection=connection)
        self.evidence = EvidenceStore(connection=connection)

    @property
    def execution_authority(self) -> str:
        return "canonical_work" if self.mode == "canonical_authority" else "p10_existing_runtime"

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
                    "authority": self.execution_authority,
                }
            ),
            priority=int(p10_goal.get("priority", 50)),
            deadline=p10_goal.get("deadline"),
            data_classification=str(p10_goal.get("privacy") or "internal"),
            budget=ExecutionBudget(max_attempts=1),
            approval_policy={"authority": self.execution_authority, "projection_mode": self.mode},
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

            task_ids = [str(task["id"]) for task in p10_plan.get("tasks", [])]
            order_ids = {task_id: f"{work_plan_id}:{task_id}" for task_id in task_ids}
            orders: list[WorkOrder] = []
            for task in p10_plan.get("tasks", []):
                task_id = str(task["id"])
                objective = str(task.get("objective") or task_id)
                verification_required = bool(task.get("verification_required"))
                contract = EvidenceContract(
                    requirements=(
                        (
                            EvidenceRequirement(
                                kind="governed_operation_verification",
                                required=True,
                                min_count=1,
                                min_provenance=EvidenceProvenance.TOOL_VERIFIED.value,
                            ),
                        )
                        if verification_required
                        else ()
                    ),
                    require_review=False,
                    require_retest=False,
                )
                requested_tool = str(task.get("requested_tool") or task.get("action") or "").strip()
                worker_type = "tool" if requested_tool else "orchestrator"
                status = _ORDER_STATUS.get(str(task.get("status") or "WAITING").upper(), WorkOrderStatus.BLOCKED)
                orders.append(
                    WorkOrder(
                        id=order_ids[task_id],
                        plan_id=work_plan_id,
                        project_id=goal.project_id,
                        title=objective[:160] or task_id,
                        objective=objective,
                        worker_type=worker_type,
                        status=status,
                        priority=goal.priority,
                        dependencies=tuple(order_ids[str(dep)] for dep in task.get("dependencies", []) if str(dep) in order_ids),
                        allowed_capabilities=tuple(str(x) for x in task.get("required_capabilities", [])),
                        resource_scope=ResourceScope(
                            metadata={
                                "p10_task_id": task_id,
                                "requested_tool": requested_tool or None,
                                "execution_authority": self.execution_authority,
                            }
                        ),
                        expected_output=objective,
                        evidence_contract=contract,
                        verification_strategy={
                            "authority": "p10_p6_governed_verification",
                            "execution_authority": self.execution_authority,
                            "required": verification_required,
                            "projection_mode": self.mode,
                        },
                        approval_policy={"required": bool(task.get("approval_required")), "authority": "existing_owner_approval_governance"},
                        retry_policy={"max_retries": int(task.get("retry_limit", 0)), "authority": "canonical_work_failure_policy" if self.mode == "canonical_authority" else "p10_existing_runtime"},
                        workflow_id=task.get("operation_plan_id"),
                        workflow_run_id=task.get("operation_id") or task.get("result_ref"),
                        created_at=created_at,
                        updated_at=_iso(p10_plan.get("updated_at")),
                    )
                )

            p10_state = str(p10_plan.get("state") or "CREATED").upper()
            status = _PLAN_STATUS.get(p10_state, WorkPlanStatus.HOLD)
            readiness = (
                ReadinessStatus.READY
                if status in {WorkPlanStatus.READY, WorkPlanStatus.RUNNING, WorkPlanStatus.COMPLETED}
                else ReadinessStatus.DEGRADED
                if status is WorkPlanStatus.DEGRADED
                else ReadinessStatus.HOLD
            )
            projected = WorkPlan(
                id=work_plan_id,
                goal_id=goal.id,
                project_id=goal.project_id,
                version=version,
                summary=str(p10_goal.get("description") or "P10 work plan")[:1000],
                work_orders=tuple(orders),
                evidence_contract=EvidenceContract(require_review=False),
                critic={
                    "projection": "p10_compatibility_document",
                    "source_p10_state": p10_state,
                    "projection_mode": self.mode,
                    "observe_only": self.mode == "observe_only",
                    "execution_authority": self.execution_authority,
                },
                readiness=readiness,
                status=status,
                supersedes_plan_id=supersedes,
                created_at=created_at,
            )
            return self.work.save_plan(projected, source_p10_plan_id=source_plan_id)

    def backfill(self) -> dict[str, int]:
        with self.lock:
            goals = [json.loads(row[0]) for row in self.connection.execute("SELECT document FROM p10_goals ORDER BY updated_at, id").fetchall()]
            goal_by_id = {str(goal["id"]): goal for goal in goals}
            for goal in goals:
                self.project_goal(goal)
            plans = [json.loads(row[0]) for row in self.connection.execute("SELECT document FROM p10_plans ORDER BY updated_at, id").fetchall()]
            for plan in plans:
                goal = goal_by_id.get(str(plan.get("goal_id")))
                if goal is not None:
                    self.project_plan(plan, goal)
            return {"goals": len(goals), "plans": len(plans)}

    def observe_governed_completion(self, p10_plan: dict[str, Any], p10_goal: dict[str, Any], task: dict[str, Any]) -> dict[str, Any] | None:
        if str(task.get("status") or "").upper() != "COMPLETED":
            return None
        if not task.get("operation_plan_id") or not task.get("result_ref"):
            return None
        projected = self.project_plan(p10_plan, p10_goal)
        task_id = str(task["id"]);order_id = f"{projected.id}:{task_id}";order = self.work.get_order(order_id)
        if order is None:
            return None
        source = str(task.get("result_ref"));digest = hashlib.sha256(f"{p10_plan['id']}|{task_id}|{source}|verified".encode("utf-8")).hexdigest()[:32];evidence_id = f"ev-{digest}";item = self.evidence.get_evidence(evidence_id)
        if item is None:
            item = Evidence(
                id=evidence_id,
                project_id=projected.project_id,
                goal_id=projected.goal_id,
                plan_id=projected.id,
                work_order_id=order_id,
                tool_name=str(task.get("requested_tool") or task.get("action") or "") or None,
                source_type="p10_governed_operation",
                source=source,
                subject=order.objective,
                observation="The governed P10/P6 compatibility execution path marked this task complete only after a VERIFIED or RECOVERED operation outcome.",
                artifact_ref=source,
                provenance=EvidenceProvenance.TOOL_VERIFIED,
                verification_state=VerificationState.VERIFIED,
                verification_reason="Inherited from the qualified P10/P6 verification invariant; canonical Work supplies durable dispatch/attempt authority but does not invent verification.",
                confidence=1.0,
                data_classification=str(p10_goal.get("privacy") or "internal"),
            )
            with self.lock:
                self.evidence.record_evidence(item)
        claim_id = f"claim-{hashlib.sha256(order_id.encode('utf-8')).hexdigest()[:32]}";claim = self.evidence.get_claim(claim_id)
        if claim is None:
            claim = Claim(id=claim_id, project_id=projected.project_id, work_order_id=order_id, text=f"Work order completed: {order.objective}", state=ClaimState.PROPOSED, confidence=0.0)
            with self.lock:
                self.evidence.create_claim(claim)
        try:
            with self.lock:
                self.evidence.link_evidence(claim_id, evidence_id)
        except sqlite3.IntegrityError:
            pass
        supporting = self.evidence.evidence_for_claim(claim_id);decision = ClaimGate.evaluate(claim, supporting)
        with self.lock:
            claim = self.evidence.update_claim_state(claim_id, decision.state, confidence=1.0 if decision.passed else max(claim.confidence, 0.5))
        return {"mode": self.mode, "work_plan_id": projected.id, "work_order_id": order_id, "evidence_id": evidence_id, "claim_id": claim_id, "claim_state": claim.state.value, "passed": decision.passed, "reasons": list(decision.reasons)}

    def work_plan_for_p10(self, p10_plan_id: str) -> WorkPlan | None:
        with self.lock:
            return self.work.latest_plan_for_source(p10_plan_id)

    def evidence_for_task(self, p10_plan_id: str, task_id: str) -> list[Evidence]:
        projected = self.work_plan_for_p10(p10_plan_id)
        if projected is None:
            return []
        return self.evidence.list_evidence(work_order_id=f"{projected.id}:{task_id}")

    def status(self) -> dict[str, Any]:
        with self.lock:
            base = self.work.status()
            base.update({
                "evidence": int(self.connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
                "claims": int(self.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0]),
                "mode": self.mode,
                "execution_authority": self.execution_authority,
                "durability_schema": 3,
            })
            return base
