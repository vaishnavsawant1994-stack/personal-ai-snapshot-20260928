from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from evidence import (
    ClaimState,
    DomainClaimGate,
    DomainClaimType,
    EvidenceProvenance,
    EvidenceStore,
    VerificationState,
)

from .models import GoalSpec, Milestone, WorkOrder, WorkPlan
from .reviewer import PlanReview


class CompletionState(StrEnum):
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CompletionBlocker:
    kind: str
    message: str
    work_order_id: str | None = None
    milestone_id: str | None = None
    claim_id: str | None = None
    evidence_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "work_order_id": self.work_order_id,
            "milestone_id": self.milestone_id,
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class WorkOrderCompletionDecision:
    work_order_id: str
    state: CompletionState
    passed: bool
    score: float
    reasons: tuple[str, ...] = ()
    blockers: tuple[CompletionBlocker, ...] = ()
    evidence_count: int = 0
    verified_claim_ids: tuple[str, ...] = ()
    required_claims: int = 0
    review_state: str = "not_required"
    domain_claim_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "state": self.state.value,
            "passed": self.passed,
            "score": self.score,
            "reasons": list(self.reasons),
            "blocking_items": [item.to_dict() for item in self.blockers],
            "evidence_count": self.evidence_count,
            "verified_claims": list(self.verified_claim_ids),
            "required_claims": self.required_claims,
            "review_state": self.review_state,
            "domain_claim_type": self.domain_claim_type,
        }


@dataclass(frozen=True)
class MilestoneCompletionDecision:
    milestone_id: str
    passed: bool
    score: float
    reasons: tuple[str, ...] = ()
    blockers: tuple[CompletionBlocker, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "passed": self.passed,
            "score": self.score,
            "reasons": list(self.reasons),
            "blocking_items": [item.to_dict() for item in self.blockers],
        }


@dataclass(frozen=True)
class CompletionReport:
    plan_id: str
    goal_id: str
    project_id: str | None
    state: CompletionState
    complete: bool
    completion_score: float
    completion_reasons: tuple[str, ...]
    blocking_items: tuple[CompletionBlocker, ...]
    work_orders: tuple[WorkOrderCompletionDecision, ...]
    milestones: tuple[MilestoneCompletionDecision, ...]
    verified_claims: tuple[str, ...]
    required_claims: int
    review_state: str
    authority: str = "deterministic_completion_judge"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "project_id": self.project_id,
            "completion_state": self.state.value,
            "complete": self.complete,
            "completion_score": self.completion_score,
            "completion_reasons": list(self.completion_reasons),
            "blocking_items": [item.to_dict() for item in self.blocking_items],
            "work_orders": [item.to_dict() for item in self.work_orders],
            "milestones": [item.to_dict() for item in self.milestones],
            "verified_claims": list(self.verified_claims),
            "required_claims": self.required_claims,
            "review_state": self.review_state,
            "authority": self.authority,
        }


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _minimum_provenance(value: str) -> EvidenceProvenance:
    try:
        return EvidenceProvenance(str(value))
    except ValueError:
        return EvidenceProvenance.TOOL_VERIFIED


def _criterion_key(value: str) -> str:
    return " ".join(str(value).lower().split())


class CompletionJudge:
    """Deterministic completion authority over canonical Work state.

    It does not execute tools, mutate approval/recovery state, or trust client/model
    completion flags. P10 execution may finish first; canonical completion is granted
    only when the required proof/review invariants below pass.
    """

    _PENDING = {
        "WAITING",
        "READY",
        "RUNNING",
        "RETRYING",
        "WAITING_RESOURCE",
        "PAUSED",
    }
    _ATTENTION = {"WAITING_APPROVAL", "BLOCKED"}
    _RECOVERY = {"RECOVERING", "RECOVERY_REQUIRED", "UNCERTAIN"}
    _VERIFYING = {"VERIFYING"}
    _FAILURE = {"FAILED"}
    _CANCELLED = {"CANCELLED"}

    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.evidence_store = evidence_store

    def _task_for_order(self, order: WorkOrder, tasks: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
        task_id = str(order.resource_scope.metadata.get("p10_task_id") or "").strip()
        if not task_id:
            suffix = order.id.rsplit(":", 1)[-1]
            task_id = suffix
        return tasks.get(task_id)

    def _evidence_contract_blockers(self, order: WorkOrder, evidence) -> list[CompletionBlocker]:
        blockers: list[CompletionBlocker] = []
        for requirement in order.evidence_contract.requirements:
            if not requirement.required:
                continue
            minimum = _minimum_provenance(requirement.min_provenance)
            qualifying = [
                item
                for item in evidence
                if item.verification_state is VerificationState.VERIFIED
                and item.provenance.rank >= minimum.rank
            ]
            source_types = tuple(str(x) for x in requirement.metadata.get("source_types", ()))
            if source_types:
                allowed = set(source_types)
                qualifying = [item for item in qualifying if item.source_type in allowed]
            if len(qualifying) < requirement.min_count:
                blockers.append(
                    CompletionBlocker(
                        "evidence_missing",
                        f"requires {requirement.min_count} verified evidence item(s) for {requirement.kind}; found {len(qualifying)}",
                        work_order_id=order.id,
                    )
                )
        return blockers

    def _domain_decision(self, order: WorkOrder, task: Mapping[str, Any], claims, evidence):
        raw_type = order.verification_strategy.get("domain_claim_type") or order.resource_scope.metadata.get("domain_claim_type")
        if not raw_type:
            return None
        try:
            claim_type = DomainClaimType(str(raw_type))
        except ValueError:
            return (False, "unsupported domain claim type", str(raw_type), None)
        expected = order.verification_strategy.get("domain_expected") or order.resource_scope.metadata.get("domain_expected") or {}
        verified_claim = next((item for item in claims if item.state is ClaimState.VERIFIED), None)
        candidate_claim = verified_claim or (claims[0] if claims else None)
        if candidate_claim is None:
            return (False, "required domain claim is missing", claim_type.value, None)
        execution_ids = [
            str(value)
            for value in (task.get("operation_id"), task.get("result_ref"), order.workflow_run_id)
            if value not in (None, "")
        ]
        receipts = []
        seen = set()
        for execution_id in execution_ids:
            for receipt in self.evidence_store.list_receipts(execution_id=execution_id):
                if receipt.id not in seen:
                    seen.add(receipt.id)
                    receipts.append(receipt)
        decision = DomainClaimGate.evaluate(
            claim_type,
            candidate_claim,
            evidence,
            receipts=receipts,
            expected=expected if isinstance(expected, Mapping) else {},
        )
        return (decision.passed, "; ".join(decision.reasons), claim_type.value, decision)

    def evaluate_work_order(self, order: WorkOrder, task: Mapping[str, Any] | None) -> WorkOrderCompletionDecision:
        blockers: list[CompletionBlocker] = []
        reasons: list[str] = []
        checks = 0
        passed_checks = 0

        checks += 1
        if task is None:
            blockers.append(CompletionBlocker("execution_missing", "authoritative P10 task is missing", work_order_id=order.id))
            task_status = "MISSING"
        else:
            task_status = _status(task.get("status"))
            if task_status == "COMPLETED":
                passed_checks += 1
            elif task_status in self._VERIFYING:
                blockers.append(CompletionBlocker("verification_pending", "execution is still verifying", work_order_id=order.id))
            elif task_status in self._RECOVERY:
                blockers.append(CompletionBlocker("recovery_required", "execution requires recovery/reconciliation", work_order_id=order.id))
            elif task_status in self._ATTENTION:
                blockers.append(CompletionBlocker("owner_attention_required", f"execution state is {task_status}", work_order_id=order.id))
            elif task_status in self._FAILURE:
                blockers.append(CompletionBlocker("execution_failed", "execution failed", work_order_id=order.id))
            elif task_status in self._CANCELLED:
                blockers.append(CompletionBlocker("execution_cancelled", "execution was cancelled", work_order_id=order.id))
            else:
                blockers.append(CompletionBlocker("execution_incomplete", f"execution state is {task_status or 'UNKNOWN'}", work_order_id=order.id))

        evidence = self.evidence_store.list_evidence(work_order_id=order.id)
        claims = self.evidence_store.list_claims(work_order_id=order.id)

        evidence_blockers = self._evidence_contract_blockers(order, evidence)
        checks += max(1, len([item for item in order.evidence_contract.requirements if item.required]))
        if evidence_blockers:
            blockers.extend(evidence_blockers)
        else:
            passed_checks += max(1, len([item for item in order.evidence_contract.requirements if item.required]))

        rejected_claims = [item for item in claims if item.state in {ClaimState.REJECTED, ClaimState.DISPUTED}]
        verified_claims = [item for item in claims if item.state is ClaimState.VERIFIED]
        requested_tool = str(order.resource_scope.metadata.get("requested_tool") or "").strip()
        claims_required = 1 if (requested_tool or order.evidence_contract.requirements) else 0
        checks += 1
        if rejected_claims:
            blockers.extend(
                CompletionBlocker("claim_rejected", "required claim is rejected or disputed", work_order_id=order.id, claim_id=item.id)
                for item in rejected_claims
            )
        elif claims_required and not verified_claims:
            blockers.append(CompletionBlocker("claim_unsupported", "required completion claim is not verified", work_order_id=order.id))
        else:
            passed_checks += 1

        domain = self._domain_decision(order, task or {}, claims, evidence)
        domain_type = domain[2] if domain else None
        if domain is not None:
            checks += 1
            if domain[0]:
                passed_checks += 1
            else:
                blockers.append(CompletionBlocker("domain_claim_unverified", domain[1], work_order_id=order.id, claim_id=(claims[0].id if claims else None)))

        checks += 1
        require_review = bool(order.evidence_contract.require_review)
        if require_review:
            if rejected_claims or evidence_blockers or (claims_required and not verified_claims) or (domain is not None and not domain[0]):
                review_state = "rejected"
                blockers.append(CompletionBlocker("review_failed", "deterministic completion review found unresolved proof blockers", work_order_id=order.id))
            else:
                review_state = "passed"
                passed_checks += 1
        else:
            review_state = "not_required"
            passed_checks += 1

        passed = not blockers and task_status == "COMPLETED"
        if passed:
            state = CompletionState.COMPLETE
            reasons.append("execution, evidence, claims, and required review passed")
        elif task_status in self._VERIFYING or any(item.kind in {"evidence_missing", "claim_unsupported", "domain_claim_unverified"} for item in blockers):
            state = CompletionState.VERIFYING
            reasons.append("completion proof is still incomplete")
        elif any(item.kind == "review_failed" for item in blockers):
            state = CompletionState.REVIEWING
            reasons.append("completion review did not pass")
        elif task_status in self._FAILURE:
            state = CompletionState.FAILED
            reasons.append("execution failed")
        elif task_status in self._CANCELLED:
            state = CompletionState.CANCELLED
            reasons.append("execution was cancelled")
        elif blockers:
            state = CompletionState.BLOCKED
            reasons.append("completion is blocked")
        else:
            state = CompletionState.IN_PROGRESS
            reasons.append("work remains in progress")

        score = round(100.0 * passed_checks / max(1, checks), 2)
        return WorkOrderCompletionDecision(
            work_order_id=order.id,
            state=state,
            passed=passed,
            score=score,
            reasons=tuple(reasons),
            blockers=tuple(blockers),
            evidence_count=len(evidence),
            verified_claim_ids=tuple(item.id for item in verified_claims),
            required_claims=claims_required,
            review_state=review_state,
            domain_claim_type=domain_type,
        )

    @staticmethod
    def _criteria_trace(criteria: tuple[str, ...], plan: WorkPlan, allowed_order_ids: set[str] | None = None) -> list[str]:
        if not criteria:
            return []
        text: list[str] = []
        for order in plan.work_orders:
            if allowed_order_ids is not None and order.id not in allowed_order_ids:
                continue
            text.extend(order.success_criteria)
            if order.expected_output:
                text.append(order.expected_output)
        normalized = [_criterion_key(item) for item in text if str(item).strip()]
        missing = []
        for criterion in criteria:
            target = _criterion_key(criterion)
            if not any(target == item or target in item or item in target for item in normalized if item):
                missing.append(criterion)
        return missing

    def evaluate(
        self,
        plan: WorkPlan,
        goal: GoalSpec,
        p10_plan: Mapping[str, Any],
        *,
        plan_review: PlanReview | None = None,
    ) -> CompletionReport:
        tasks = {str(item.get("id")): item for item in p10_plan.get("tasks", []) if isinstance(item, Mapping)}
        order_decisions = tuple(
            self.evaluate_work_order(order, self._task_for_order(order, tasks))
            for order in plan.work_orders
        )
        order_by_id = {item.work_order_id: item for item in order_decisions}
        blockers: list[CompletionBlocker] = [item for decision in order_decisions for item in decision.blockers]

        milestone_decisions: list[MilestoneCompletionDecision] = []
        for milestone in plan.milestones:
            milestone_blockers: list[CompletionBlocker] = []
            for order_id in milestone.work_order_ids:
                decision = order_by_id.get(order_id)
                if decision is None or not decision.passed:
                    milestone_blockers.append(
                        CompletionBlocker("milestone_work_incomplete", f"required WorkOrder {order_id} is not complete", milestone_id=milestone.id, work_order_id=order_id)
                    )
            missing_criteria = self._criteria_trace(milestone.success_criteria, plan, set(milestone.work_order_ids))
            for criterion in missing_criteria:
                milestone_blockers.append(
                    CompletionBlocker("milestone_criterion_untraced", f"success criterion is not traced to required WorkOrders: {criterion}", milestone_id=milestone.id)
                )
            passed = not milestone_blockers and bool(milestone.work_order_ids)
            milestone_decisions.append(
                MilestoneCompletionDecision(
                    milestone_id=milestone.id,
                    passed=passed,
                    score=100.0 if passed else max(0.0, 100.0 - 25.0 * len(milestone_blockers)),
                    reasons=("all required WorkOrders and milestone criteria passed",) if passed else ("milestone completion is blocked",),
                    blockers=tuple(milestone_blockers),
                )
            )
            blockers.extend(milestone_blockers)

        review_state = "not_required"
        if plan.evidence_contract.require_review:
            if plan_review is None:
                review_state = "missing"
                blockers.append(CompletionBlocker("review_missing", "required deterministic plan/review record is missing"))
            elif str(plan_review.status.value) == "hold" or plan_review.blockers:
                review_state = "rejected"
                blockers.append(CompletionBlocker("review_failed", "required deterministic review is on hold/rejected"))
            else:
                review_state = "passed"

        p10_state = _status(p10_plan.get("state"))
        if p10_state != "COMPLETED":
            if p10_state in self._VERIFYING:
                blockers.append(CompletionBlocker("verification_pending", "plan is still verifying"))
            elif p10_state in self._RECOVERY:
                blockers.append(CompletionBlocker("recovery_required", "plan requires recovery/reconciliation"))
            elif p10_state == "WAITING_APPROVAL":
                blockers.append(CompletionBlocker("approval_pending", "plan has a pending approval"))
            elif p10_state in {"FAILED", "BLOCKED"}:
                blockers.append(CompletionBlocker("plan_blocked", f"plan state is {p10_state}"))
            elif p10_state == "CANCELLED":
                blockers.append(CompletionBlocker("plan_cancelled", "plan was cancelled"))
            else:
                blockers.append(CompletionBlocker("plan_incomplete", f"plan state is {p10_state or 'UNKNOWN'}"))

        if plan.milestones:
            if any(not item.passed for item in milestone_decisions):
                blockers.append(CompletionBlocker("milestones_incomplete", "one or more mandatory milestones are incomplete"))
        elif any(not item.passed for item in order_decisions):
            blockers.append(CompletionBlocker("work_orders_incomplete", "one or more required WorkOrders are incomplete"))

        missing_goal_criteria = self._criteria_trace(goal.success_criteria, plan)
        for criterion in missing_goal_criteria:
            blockers.append(CompletionBlocker("goal_criterion_untraced", f"goal success criterion is not traced to verified WorkOrders: {criterion}"))

        if goal.deliverables:
            output_text = [_criterion_key(order.expected_output) for order in plan.work_orders if order.expected_output]
            for deliverable in goal.deliverables:
                target = _criterion_key(deliverable)
                if not any(target == item or target in item or item in target for item in output_text if item):
                    blockers.append(CompletionBlocker("deliverable_untraced", f"required deliverable is not traced to a WorkOrder output: {deliverable}"))

        blockers = list({(item.kind, item.message, item.work_order_id, item.milestone_id, item.claim_id, item.evidence_id): item for item in blockers}.values())
        verified_claims = tuple(dict.fromkeys(claim_id for item in order_decisions for claim_id in item.verified_claim_ids))
        required_claims = sum(item.required_claims for item in order_decisions)
        complete = not blockers and p10_state == "COMPLETED" and all(item.passed for item in order_decisions) and (not milestone_decisions or all(item.passed for item in milestone_decisions)) and review_state in {"passed", "not_required"}

        if complete:
            state = CompletionState.COMPLETE
            reasons = ("all required execution, evidence, claims, milestones, criteria, recovery, and review checks passed",)
        elif p10_state == "CANCELLED":
            state = CompletionState.CANCELLED
            reasons = ("plan was cancelled",)
        elif p10_state == "FAILED":
            state = CompletionState.FAILED
            reasons = ("plan failed",)
        elif any(item.kind in {"verification_pending", "evidence_missing", "claim_unsupported", "domain_claim_unverified"} for item in blockers):
            state = CompletionState.VERIFYING
            reasons = ("execution may be terminal, but completion proof is incomplete",)
        elif any(item.kind in {"review_missing", "review_failed"} for item in blockers):
            state = CompletionState.REVIEWING
            reasons = ("completion review is incomplete or rejected",)
        elif blockers:
            state = CompletionState.BLOCKED
            reasons = ("completion is blocked by unresolved required conditions",)
        else:
            state = CompletionState.IN_PROGRESS
            reasons = ("required work is still in progress",)

        components = [item.score for item in order_decisions]
        components.extend(item.score for item in milestone_decisions)
        completion_score = round(sum(components) / max(1, len(components)), 2)
        if blockers:
            completion_score = min(completion_score, 99.0)
        if complete:
            completion_score = 100.0

        return CompletionReport(
            plan_id=plan.id,
            goal_id=goal.id,
            project_id=plan.project_id or goal.project_id,
            state=state,
            complete=complete,
            completion_score=completion_score,
            completion_reasons=reasons,
            blocking_items=tuple(blockers),
            work_orders=order_decisions,
            milestones=tuple(milestone_decisions),
            verified_claims=verified_claims,
            required_claims=required_claims,
            review_state=review_state,
        )
