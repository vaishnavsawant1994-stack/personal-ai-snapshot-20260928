from __future__ import annotations

import sqlite3
import time

import pytest

from approvals.projection import ApprovalsProjection
from evidence.models import (
    Claim,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    Receipt,
    VerificationState,
)
from evidence.store import EvidenceStore
from future_intelligence.work_orchestration.completion import CompletionJudge, CompletionState
from future_intelligence.work_orchestration.models import (
    EvidenceContract,
    EvidenceRequirement,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)
from future_intelligence.work_orchestration.replanning import (
    PlanDelta,
    PlanDeltaAction,
    PlanDeltaItem,
    PlanDeltaStore,
)
from future_intelligence.work_orchestration.store import WorkStore
from security.approvals import ApprovalManager


@pytest.mark.parametrize(
    ("tool_name", "destination"),
    [
        ("gmail.send", "mailto:owner@example.test"),
        ("content.publish", "https://example.test/post"),
        ("vercel.deploy", "https://example.test/deploy"),
        ("files.delete", "file:///tmp/example.txt"),
        ("external_record.create", "https://example.test/records"),
    ],
)
def test_interrupted_consequential_dispatch_never_blindly_redispatches(
    tmp_path, tool_name: str, destination: str
):
    """A restart after dispatch ownership is uncertain must become recovery-required."""
    path = tmp_path / "approvals.sqlite3"
    params = {"resource": "bounded-test"}
    now = time.time()

    before_restart = ApprovalManager(ttl_seconds=3600, path=path)
    ticket = before_restart.create(
        "exec-1",
        tool_name,
        params,
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
        destination=destination,
        data_classification="internal",
    )
    before_restart.approve(
        ticket.id,
        "exec-1",
        tool_name,
        params,
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
        destination=destination,
        data_classification="internal",
    )

    dispatch = before_restart.begin_dispatch(
        ticket.id, now=now, worker_id="runtime-before-restart", lease_seconds=5
    )
    assert dispatch["dispatch"] is True
    side_effect_count = 1  # represents the one external dispatch whose response was lost

    # New process/runtime against the same durable approval database.
    after_restart = ApprovalManager(ttl_seconds=3600, path=path)
    still_owned = after_restart.begin_dispatch(
        ticket.id, now=now + 1, worker_id="runtime-after-restart", lease_seconds=5
    )
    assert still_owned["dispatch"] is False
    assert still_owned["status"] == "dispatching"
    assert side_effect_count == 1

    # Once the original dispatch lease is no longer trustworthy, fail closed.
    recovery = after_restart.begin_dispatch(
        ticket.id, now=now + 6, worker_id="runtime-after-restart", lease_seconds=5
    )
    assert recovery["dispatch"] is False
    assert recovery["status"] == "recovery_required"
    assert side_effect_count == 1

    # Owner-visible projection must not hide the recovery state after restart.
    projected = ApprovalsProjection(after_restart).detail(
        ticket.id,
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
    )
    assert projected is not None
    assert projected["status"] == "recovery_required"
    assert projected["failure_code"] == "dispatch_lease_expired"

    # Further restarts remain fenced; no runtime can claim a second dispatch.
    another_restart = ApprovalManager(ttl_seconds=3600, path=path)
    again = another_restart.begin_dispatch(
        ticket.id, now=now + 20, worker_id="runtime-third", lease_seconds=5
    )
    assert again["dispatch"] is False
    assert again["status"] == "recovery_required"
    assert side_effect_count == 1


def test_pending_and_approved_owner_decisions_survive_restart(tmp_path):
    path = tmp_path / "approvals.sqlite3"
    params = {"message": "safe test"}

    first = ApprovalManager(ttl_seconds=3600, path=path)
    pending = first.create(
        "exec-pending",
        "gmail.send",
        params,
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
        destination="mailto:test@example.test",
    )
    first.save_context(pending.id, {"execution_id": "exec-pending", "index": 0})

    restarted = ApprovalManager(ttl_seconds=3600, path=path)
    assert restarted.record(pending.id)["status"] == "pending"
    assert restarted.context(pending.id)["execution_id"] == "exec-pending"

    restarted.approve(
        pending.id,
        "exec-pending",
        "gmail.send",
        params,
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
        destination="mailto:test@example.test",
    )

    approved_restart = ApprovalManager(ttl_seconds=3600, path=path)
    assert approved_restart.record(pending.id)["status"] == "approved"
    claimed = approved_restart.begin_dispatch(pending.id, worker_id="runtime-2")
    assert claimed["dispatch"] is True

    concurrent_restart = ApprovalManager(ttl_seconds=3600, path=path)
    second_claim = concurrent_restart.begin_dispatch(pending.id, worker_id="runtime-3")
    assert second_claim["dispatch"] is False
    assert second_claim["status"] == "dispatching"


def test_completed_dispatch_is_idempotent_after_restart(tmp_path):
    path = tmp_path / "approvals.sqlite3"
    params = {"record": "safe"}
    manager = ApprovalManager(ttl_seconds=3600, path=path)
    ticket = manager.create("exec-done", "external_record.create", params)
    manager.approve(ticket.id, "exec-done", "external_record.create", params)
    assert manager.begin_dispatch(ticket.id, worker_id="runtime-1")["dispatch"] is True
    expected = {"status": "completed", "remote_id": "record-1", "verified": True}
    assert manager.complete_dispatch(ticket.id, expected) == expected

    restarted = ApprovalManager(ttl_seconds=3600, path=path)
    record = restarted.record(ticket.id)
    assert record["status"] == "completed"
    assert record["outcome"] == expected
    replay = restarted.begin_dispatch(ticket.id, worker_id="runtime-2")
    assert replay["dispatch"] is False
    assert replay["status"] == "completed"
    assert replay["outcome"] == expected


def _canonical_work_fixture():
    goal = GoalSpec(
        id="goal-1",
        title="Restart qualification",
        objective="Prove durable Work state",
        desired_outcome="No orchestration state is lost across restart",
        project_id="project-1",
    )
    order = WorkOrder(
        id="order-1",
        plan_id="plan-1",
        project_id="project-1",
        title="Persist verified result",
        objective="Persist evidence-backed completion state",
        worker_type="project",
        status=WorkOrderStatus.COMPLETED,
        resource_scope=ResourceScope(metadata={"p10_task_id": "task-1"}),
        evidence_contract=EvidenceContract(
            requirements=(EvidenceRequirement(kind="result", min_provenance="tool_verified"),),
            require_review=False,
        ),
    )
    plan = WorkPlan(
        id="plan-1",
        goal_id=goal.id,
        version=1,
        summary="Durable qualification plan",
        project_id="project-1",
        work_orders=(order,),
        readiness=ReadinessStatus.READY,
        status=WorkPlanStatus.READY,
    )
    return goal, order, plan


def test_work_plan_replan_evidence_claim_receipt_and_completion_survive_restart(tmp_path):
    work_db = tmp_path / "work.sqlite3"
    evidence_db = tmp_path / "evidence.sqlite3"
    goal, order, plan = _canonical_work_fixture()

    work = WorkStore(work_db)
    work.upsert_goal(goal, source_p10_goal_id="p10-goal-1")
    work.save_plan(plan, source_p10_plan_id="p10-plan-1")
    delta = PlanDelta(
        id="delta-1",
        goal_id=goal.id,
        source_p10_plan_id="p10-plan-1",
        from_plan_id=None,
        to_plan_id=plan.id,
        reason="restart qualification",
        trigger="test",
        items=(
            PlanDeltaItem(
                PlanDeltaAction.ADD,
                "task-1",
                after={"title": order.title, "worker_type": order.worker_type},
            ),
        ),
    )
    PlanDeltaStore(work.connection).record(delta)
    work.close()

    evidence = EvidenceStore(evidence_db)
    item = Evidence(
        id="evidence-1",
        project_id="project-1",
        goal_id=goal.id,
        plan_id=plan.id,
        work_order_id=order.id,
        source_type="tool_result",
        source="qualified-test-tool",
        subject="result",
        observation="The expected bounded result was verified.",
        provenance=EvidenceProvenance.TOOL_VERIFIED,
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    receipt = Receipt(
        id="receipt-1",
        operation="external_record.create",
        execution_id="exec-1",
        tool="external_record.create",
        destination="https://example.test/records",
        request_hash="request-hash-1",
        remote_id="record-1",
        verified=True,
    )
    claim = Claim(
        id="claim-1",
        project_id="project-1",
        work_order_id=order.id,
        text="The bounded result is complete.",
        state=ClaimState.VERIFIED,
        confidence=1.0,
    )
    evidence.record_evidence(item)
    evidence.record_receipt(receipt)
    evidence.create_claim(claim)
    evidence.link_evidence(claim.id, item.id)

    before = CompletionJudge(evidence).evaluate_work_order(
        order, {"id": "task-1", "status": "COMPLETED", "operation_id": "exec-1"}
    )
    assert before.passed is True
    assert before.state is CompletionState.COMPLETE
    evidence.close()

    # Simulate a complete process restart by reconstructing every store from disk.
    work_after = WorkStore(work_db)
    restored_goal = work_after.get_goal(goal.id)
    restored_plan = work_after.get_plan(plan.id)
    restored_order = work_after.get_order(order.id)
    restored_delta = PlanDeltaStore(work_after.connection).latest_for_source("p10-plan-1")
    assert restored_goal == goal
    assert restored_plan == plan
    assert restored_order == order
    assert restored_delta == delta

    evidence_after = EvidenceStore(evidence_db)
    assert evidence_after.get_evidence(item.id) == item
    assert evidence_after.get_receipt(receipt.id) == receipt
    assert evidence_after.get_claim(claim.id) == claim
    assert [value.id for value in evidence_after.evidence_for_claim(claim.id)] == [item.id]

    after = CompletionJudge(evidence_after).evaluate_work_order(
        restored_order,
        {"id": "task-1", "status": "COMPLETED", "operation_id": "exec-1"},
    )
    assert after.passed is True
    assert after.state is CompletionState.COMPLETE
    assert after.verified_claim_ids == (claim.id,)


def test_failed_evidence_write_does_not_corrupt_prior_durable_proof(tmp_path):
    path = tmp_path / "evidence.sqlite3"
    store = EvidenceStore(path)
    original = Evidence(
        id="evidence-stable",
        work_order_id="order-1",
        source_type="tool_result",
        source="qualified-test-tool",
        subject="stable result",
        observation="Already committed proof remains durable.",
        provenance=EvidenceProvenance.TOOL_VERIFIED,
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    store.record_evidence(original)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_evidence(original)
    store.close()

    restarted = EvidenceStore(path)
    assert restarted.get_evidence(original.id) == original
    assert len(restarted.list_evidence(work_order_id="order-1")) == 1
