from __future__ import annotations

from evidence import (
    Claim,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    EvidenceStore,
    Receipt,
    VerificationState,
)
from future_intelligence.work_orchestration import (
    CompletionJudge,
    CompletionState,
    EvidenceContract,
    EvidenceRequirement,
    GoalSpec,
    Milestone,
    PlanReview,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkPlan,
)


def _goal(*, success_criteria=()):
    return GoalSpec(
        id="goal-1",
        title="Ship",
        objective="Ship verified work",
        desired_outcome="Verified result",
        success_criteria=tuple(success_criteria),
    )


def _order(*, domain_type=None, domain_expected=None, require_review=False):
    strategy = {"required": True}
    if domain_type:
        strategy["domain_claim_type"] = domain_type
        strategy["domain_expected"] = dict(domain_expected or {})
    return WorkOrder(
        id="plan-1:task-1",
        plan_id="plan-1",
        title="Do work",
        objective="Do the consequential work",
        worker_type="tool",
        resource_scope=ResourceScope(metadata={"p10_task_id": "task-1", "requested_tool": "tool"}),
        expected_output="verified result",
        success_criteria=("verified result",),
        evidence_contract=EvidenceContract(
            requirements=(EvidenceRequirement(kind="governed_operation_verification", min_count=1, min_provenance="tool_verified"),),
            require_review=require_review,
        ),
        verification_strategy=strategy,
        workflow_run_id="exec-1",
    )


def _plan(order, *, require_review=False, milestones=()):
    return WorkPlan(
        id="plan-1",
        goal_id="goal-1",
        version=1,
        summary="Verified work",
        work_orders=(order,),
        milestones=tuple(milestones),
        evidence_contract=EvidenceContract(require_review=require_review),
    )


def _p10(status="COMPLETED", state="COMPLETED"):
    return {"id": "plan-1", "state": state, "tasks": [{"id": "task-1", "status": status, "operation_id": "exec-1"}]}


def _verified_evidence(eid="e1", source_type="p10_governed_operation"):
    return Evidence(
        id=eid,
        work_order_id="plan-1:task-1",
        source_type=source_type,
        source="runtime",
        subject="work",
        observation="verified",
        provenance=EvidenceProvenance.TOOL_VERIFIED,
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )


def _verified_claim(cid="c1"):
    return Claim(
        id=cid,
        work_order_id="plan-1:task-1",
        text="Work completed",
        state=ClaimState.VERIFIED,
        confidence=1.0,
    )


def test_terminal_execution_without_required_evidence_is_not_complete():
    store = EvidenceStore()
    report = CompletionJudge(store).evaluate(_plan(_order()), _goal(), _p10())
    assert report.complete is False
    assert report.state is CompletionState.VERIFYING
    assert any(item.kind == "evidence_missing" for item in report.blocking_items)


def test_verified_evidence_and_claim_allow_completion():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(_verified_claim())
    report = CompletionJudge(store).evaluate(_plan(_order()), _goal(), _p10())
    assert report.complete is True
    assert report.state is CompletionState.COMPLETE
    assert report.completion_score == 100.0
    assert report.verified_claims == ("c1",)


def test_waiting_approval_blocks_completion_even_with_verified_proof():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(_verified_claim())
    report = CompletionJudge(store).evaluate(_plan(_order()), _goal(), _p10(status="WAITING_APPROVAL", state="WAITING_APPROVAL"))
    assert report.complete is False
    assert any(item.kind in {"owner_attention_required", "approval_pending"} for item in report.blocking_items)


def test_recovery_or_uncertain_state_blocks_completion():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(_verified_claim())
    report = CompletionJudge(store).evaluate(_plan(_order()), _goal(), _p10(status="UNCERTAIN", state="UNCERTAIN"))
    assert report.complete is False
    assert any(item.kind == "recovery_required" for item in report.blocking_items)


def test_rejected_claim_blocks_completion():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(Claim(id="bad", work_order_id="plan-1:task-1", text="done", state=ClaimState.REJECTED))
    report = CompletionJudge(store).evaluate(_plan(_order()), _goal(), _p10())
    assert report.complete is False
    assert any(item.kind == "claim_rejected" for item in report.blocking_items)


def test_domain_claim_must_pass_before_completion():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence(source_type="provider_send_confirmation"))
    store.create_claim(_verified_claim())
    order = _order(domain_type="email_sent", domain_expected={"destination": "person@example.com"})
    without_receipt = CompletionJudge(store).evaluate(_plan(order), _goal(), _p10())
    assert without_receipt.complete is False
    assert any(item.kind == "domain_claim_unverified" for item in without_receipt.blocking_items)

    store.record_receipt(
        Receipt(
            id="r1",
            operation="send",
            execution_id="exec-1",
            tool="email",
            destination="person@example.com",
            request_hash="hash",
            remote_id="message-1",
            details={"message_id": "message-1", "destination": "person@example.com"},
            verified=True,
        )
    )
    passed = CompletionJudge(store).evaluate(_plan(order), _goal(), _p10())
    assert passed.complete is True


def test_required_plan_review_blocks_when_missing_or_on_hold():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(_verified_claim())
    plan = _plan(_order(), require_review=True)
    missing = CompletionJudge(store).evaluate(plan, _goal(), _p10())
    assert missing.complete is False
    assert missing.review_state == "missing"

    hold = PlanReview(
        id="review-1",
        plan_id="plan-1",
        plan_version=1,
        status=ReadinessStatus.HOLD,
        score=50.0,
        blockers=("unsafe",),
    )
    rejected = CompletionJudge(store).evaluate(plan, _goal(), _p10(), plan_review=hold)
    assert rejected.complete is False
    assert rejected.review_state == "rejected"

    ready = PlanReview(
        id="review-2",
        plan_id="plan-1",
        plan_version=1,
        status=ReadinessStatus.READY,
        score=100.0,
    )
    accepted = CompletionJudge(store).evaluate(plan, _goal(), _p10(), plan_review=ready)
    assert accepted.complete is True


def test_milestone_and_goal_criteria_must_trace_to_verified_work():
    store = EvidenceStore()
    store.record_evidence(_verified_evidence())
    store.create_claim(_verified_claim())
    order = _order()
    milestone = Milestone(
        id="m1",
        title="Verified",
        objective="Finish",
        success_criteria=("verified result",),
        work_order_ids=(order.id,),
    )
    report = CompletionJudge(store).evaluate(
        _plan(order, milestones=(milestone,)),
        _goal(success_criteria=("verified result",)),
        _p10(),
    )
    assert report.complete is True

    missing = CompletionJudge(store).evaluate(
        _plan(order, milestones=(Milestone(id="m2", title="Other", objective="Other", success_criteria=("different proof",), work_order_ids=(order.id,)),)),
        _goal(success_criteria=("untraced goal criterion",)),
        _p10(),
    )
    assert missing.complete is False
    kinds = {item.kind for item in missing.blocking_items}
    assert "milestone_criterion_untraced" in kinds
    assert "goal_criterion_untraced" in kinds
