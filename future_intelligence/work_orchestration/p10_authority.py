from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from evidence import Evidence, EvidenceProvenance, VerificationState

from .attempt_parking import cancel_parked_attempt, park_attempt, resume_parked_attempt
from .attempts import WorkAttemptStatus
from .failure_policy import FailureClass, WorkFailure
from .models import WorkOrderStatus


@dataclass(frozen=True)
class CanonicalTaskClaim:
    plan_id: str
    task_id: str
    work_order_id: str
    attempt_id: str
    lease_token: str


class P10CanonicalWorkAuthority:
    """Canonical Work attempt/lease authority around the qualified P10/P6 executor.

    P10 remains a compatibility orchestration document, while dispatch permission,
    causal attempts, leases and completion proof are recorded in canonical Work.
    No tool permission is granted here; P6/E3/E8 still own effects and approvals.
    """

    mode = "canonical_authority"

    def __init__(self, bridge, *, events=None, runtime_epoch: int | None = None) -> None:
        self.bridge = bridge
        self.work = bridge.work
        self.evidence = bridge.evidence
        self.events = events
        self.runtime_epoch = int(runtime_epoch if runtime_epoch is not None else time.time())
        self.bridge.mode = self.mode

    def _emit(self, event: str, **payload: Any) -> None:
        if self.events is not None:
            self.events.emit(event, **payload)

    def _order_id(self, plan_id: str, task_id: str) -> str:
        projected = self.bridge.work_plan_for_p10(plan_id)
        if projected is None:
            raise RuntimeError("canonical Work plan is unavailable")
        order_id = f"{projected.id}:{task_id}"
        if self.work.get_order(order_id) is None:
            raise KeyError(f"canonical WorkOrder not found for P10 task {task_id}")
        return order_id

    @staticmethod
    def _claim_value(plan_id: str, task_id: str, claim) -> CanonicalTaskClaim:
        return CanonicalTaskClaim(
            plan_id=plan_id,
            task_id=task_id,
            work_order_id=claim.attempt.work_order_id,
            attempt_id=claim.attempt.id,
            lease_token=claim.lease.lease_token,
        )

    def claim(self, plan_id: str, task_id: str, *, retry_limit: int = 0) -> CanonicalTaskClaim:
        order_id = self._order_id(plan_id, task_id)
        claim = self.work.claim_work_order(
            order_id,
            worker_id="p10-canonical-worker",
            runtime_epoch=self.runtime_epoch,
            lease_seconds=300,
            execution_id=f"p10:{plan_id}:{task_id}",
        )
        if claim is None:
            raise RuntimeError("canonical WorkOrder is not dispatchable or is already leased")
        self._emit(
            "work.canonical_claimed",
            plan_id=plan_id,
            task_id=task_id,
            work_order_id=order_id,
            attempt_id=claim.attempt.id,
            retry_limit=int(retry_limit),
        )
        return self._claim_value(plan_id, task_id, claim)

    def _adopt_legacy_waiting_claim(self, plan_id: str, task_id: str) -> CanonicalTaskClaim:
        """Bind canonical Work to a pre-E9 durable approval without redispatch.

        Older P10 state can survive a restart with an operation/approval identity
        but no canonical WorkAttempt. We momentarily make only the local WorkOrder
        claimable, create its first attempt/lease, and preserve the existing P10
        operation id for the original approval continuation. No external effect is
        dispatched by this migration step.
        """
        order_id = self._order_id(plan_id, task_id)
        if self.work.list_attempts(order_id):
            raise RuntimeError("legacy approval adoption requires no existing Work attempts")
        order = self.work.get_order(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.status is not WorkOrderStatus.WAITING_APPROVAL:
            raise RuntimeError("legacy approval adoption requires WAITING_APPROVAL WorkOrder")
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self.work.connection.execute("BEGIN IMMEDIATE")
        try:
            self.work._set_order_status_locked(order_id, WorkOrderStatus.QUEUED, now=now)
            self.work._append_work_event_locked(
                order_id,
                "work.legacy_waiting_approval_adoption_prepared",
                {"p10_plan_id": plan_id, "p10_task_id": task_id, "external_dispatch": False},
                created_at=now,
            )
            self.work.connection.commit()
        except Exception:
            self.work.connection.rollback()
            raise
        try:
            claim = self.work.claim_work_order(
                order_id,
                worker_id="p10-canonical-worker",
                runtime_epoch=self.runtime_epoch,
                lease_seconds=300,
                execution_id=f"p10:{plan_id}:{task_id}:legacy-approval-resume",
            )
            if claim is None:
                raise RuntimeError("legacy pending approval could not be adopted into canonical Work")
        except Exception:
            # Fail closed and restore the compatibility projection if claiming
            # failed before any external approval continuation ran.
            stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            self.work.connection.execute("BEGIN IMMEDIATE")
            try:
                self.work._set_order_status_locked(order_id, WorkOrderStatus.WAITING_APPROVAL, now=stamp)
                self.work.connection.commit()
            except Exception:
                self.work.connection.rollback()
            raise
        self._emit(
            "work.legacy_waiting_approval_adopted",
            plan_id=plan_id,
            task_id=task_id,
            work_order_id=order_id,
            attempt_id=claim.attempt.id,
            external_dispatch=False,
        )
        return self._claim_value(plan_id, task_id, claim)

    def latest_waiting_claim(self, plan_id: str, task_id: str) -> CanonicalTaskClaim:
        order_id = self._order_id(plan_id, task_id)
        attempts = self.work.list_attempts(order_id)
        if not attempts:
            return self._adopt_legacy_waiting_claim(plan_id, task_id)
        attempt = attempts[-1]
        if attempt.status not in {WorkAttemptStatus.WAITING_APPROVAL, WorkAttemptStatus.WAITING_RESOURCE}:
            raise RuntimeError("canonical Work attempt is not waiting")
        resumed = resume_parked_attempt(
            self.work,
            attempt.id,
            worker_id="p10-canonical-worker",
            runtime_epoch=self.runtime_epoch,
            lease_seconds=300,
        )
        return self._claim_value(plan_id, task_id, resumed)

    def _completion_evidence(self, p10_plan: dict[str, Any], p10_goal: dict[str, Any], task: dict[str, Any], claim: CanonicalTaskClaim) -> Evidence:
        external = bool(task.get("operation_plan_id") and task.get("result_ref"))
        source = str(task.get("result_ref") or f"p10:{p10_plan['id']}:{task['id']}:read-only")
        if external:
            # Deliberately share the qualified bridge's evidence identity. The
            # subsequent ClaimGate observation links this exact record instead of
            # creating a second proof for the same verified external outcome.
            digest = hashlib.sha256(
                f"{p10_plan['id']}|{task['id']}|{source}|verified".encode("utf-8")
            ).hexdigest()[:32]
            evidence_id = f"ev-{digest}"
        else:
            digest = hashlib.sha256(
                f"{claim.work_order_id}|{claim.attempt_id}|{source}|completed".encode("utf-8")
            ).hexdigest()[:32]
            evidence_id = f"ev-canonical-{digest}"
        existing = self.evidence.get_evidence(evidence_id)
        if existing is not None:
            return existing
        item = Evidence(
            id=evidence_id,
            project_id=p10_goal.get("project_id"),
            goal_id=str(p10_plan.get("goal_id") or "") or None,
            plan_id=claim.plan_id,
            work_order_id=claim.work_order_id,
            worker_run_id=claim.attempt_id,
            tool_name=str(task.get("requested_tool") or task.get("action") or "") or None,
            source_type="p10_governed_operation" if external else "p10_read_only_orchestration",
            source=source,
            subject=str(task.get("objective") or claim.task_id),
            observation=(
                "Qualified P10/P6 execution reached a VERIFIED or RECOVERED external outcome."
                if external
                else "Deterministic read-only P10 orchestration completed without an external side effect."
            ),
            artifact_ref=source,
            provenance=EvidenceProvenance.TOOL_VERIFIED if external else EvidenceProvenance.OBSERVED,
            verification_state=VerificationState.VERIFIED,
            verification_reason=(
                "Inherited from the qualified P10/P6 completion invariant."
                if external
                else "No external side effect was dispatched; orchestration completion was observed locally."
            ),
            confidence=1.0,
            data_classification=str(p10_goal.get("privacy") or "internal"),
        )
        self.evidence.record_evidence(item)
        return item

    def settle(self, p10_plan: dict[str, Any], p10_goal: dict[str, Any], task: dict[str, Any], claim: CanonicalTaskClaim) -> None:
        status = str(task.get("status") or "").upper()
        retry_limit = max(0, int(task.get("retry_limit", 0)))
        if status == "WAITING_APPROVAL":
            park_attempt(
                self.work,
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.WAITING_APPROVAL,
                metadata={"p10_plan_id": claim.plan_id, "p10_task_id": claim.task_id},
            )
            self._emit("work.canonical_waiting_approval", work_order_id=claim.work_order_id, attempt_id=claim.attempt_id)
            return
        if status in {"WAITING_RESOURCE", "RUNNING"}:
            park_attempt(
                self.work,
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.WAITING_RESOURCE,
                metadata={"p10_plan_id": claim.plan_id, "p10_task_id": claim.task_id, "p10_status": status},
            )
            self._emit("work.canonical_waiting_resource", work_order_id=claim.work_order_id, attempt_id=claim.attempt_id)
            return
        if status == "COMPLETED":
            evidence = self._completion_evidence(p10_plan, p10_goal, task, claim)
            self.work.finish_attempt(
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.SUCCEEDED,
                metadata={"p10_status": status, "evidence_id": evidence.id},
                max_attempts=max(1, retry_limit + 1),
            )
            self.work.complete_verified_work_order(
                claim.work_order_id,
                attempt_id=claim.attempt_id,
                evidence_ids=(evidence.id,),
                actor="p10_canonical_work_authority",
            )
            self._emit("work.canonical_completed", work_order_id=claim.work_order_id, attempt_id=claim.attempt_id, evidence_id=evidence.id)
            return
        if status in {"UNCERTAIN", "RECOVERING", "RECOVERY_REQUIRED"}:
            self.work.finish_attempt(
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.RECOVERY_REQUIRED,
                metadata={"p10_status": status},
                max_attempts=max(1, retry_limit + 1),
            )
            self._emit("work.canonical_recovery_required", work_order_id=claim.work_order_id, attempt_id=claim.attempt_id)
            return
        if status == "CANCELLED":
            self.work.finish_attempt(
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.CANCELLED,
                metadata={"p10_status": status},
                max_attempts=max(1, retry_limit + 1),
            )
            return
        if status == "FAILED":
            self.work.finish_attempt(
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.FAILED,
                failure=WorkFailure(FailureClass.UNKNOWN, "p10_task_failed", "P10 compatibility execution reported failure"),
                metadata={"p10_status": status},
                max_attempts=max(1, retry_limit + 1),
            )
            return
        self.work.finish_attempt(
            claim.attempt_id,
            lease_token=claim.lease_token,
            status=WorkAttemptStatus.RECOVERY_REQUIRED,
            metadata={"p10_status": status or "UNKNOWN"},
            max_attempts=max(1, retry_limit + 1),
        )

    def recover_exception(self, claim: CanonicalTaskClaim, exc: BaseException) -> None:
        try:
            self.work.finish_attempt(
                claim.attempt_id,
                lease_token=claim.lease_token,
                status=WorkAttemptStatus.RECOVERY_REQUIRED,
                metadata={"exception_type": type(exc).__name__},
            )
        finally:
            self._emit("work.canonical_recovery_required", work_order_id=claim.work_order_id, attempt_id=claim.attempt_id, error_type=type(exc).__name__)

    def cancel_waiting(self, plan_id: str, task_id: str, *, reason: str) -> None:
        order_id = self._order_id(plan_id, task_id)
        attempts = self.work.list_attempts(order_id)
        if not attempts:
            return
        latest = attempts[-1]
        if latest.status in {WorkAttemptStatus.WAITING_APPROVAL, WorkAttemptStatus.WAITING_RESOURCE}:
            cancel_parked_attempt(self.work, latest.id, actor="p10_owner_action", reason=reason)
