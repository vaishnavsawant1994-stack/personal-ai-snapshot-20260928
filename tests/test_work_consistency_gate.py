from __future__ import annotations

import pytest

from qualification.work_consistency import WorkConsistencyError, WorkConsistencyGate


def _order(order_id, task_id, *, status="completed", passed=True, dependencies=()):
    return {
        "id": order_id,
        "status": status,
        "dependencies": list(dependencies),
        "resource_scope": {"metadata": {"p10_task_id": task_id}},
        "completion": {
            "work_order_id": order_id,
            "state": "complete" if passed else "verifying",
            "passed": passed,
        },
    }


def _project_snapshot(*, dependency_passed=True, live_state="RUNNING"):
    first = _order("order-1", "task-1", status="completed" if dependency_passed else "verifying", passed=dependency_passed)
    second = _order("order-2", "task-2", status="queued", passed=False, dependencies=("order-1",))
    return {
        "project_id": "project-1",
        "p10_plan": {
            "id": "plan-1",
            "state": "RUNNING",
            "tasks": [
                {"id": "task-1", "status": "COMPLETED", "dependencies": []},
                {"id": "task-2", "status": "WAITING", "dependencies": ["task-1"]},
            ],
        },
        "work_plan": {
            "id": "work-plan-1",
            "status": "running",
            "completion": {"complete": False, "completion_state": "in_progress"},
            "work_orders": [first, second],
        },
        "live_work": {
            "state": live_state,
            "ready_task_ids": ["task-2"] if dependency_passed else [],
        },
    }


def _baseline():
    snapshot = _project_snapshot()
    attention = {
        "counts": {"total": 1, "approval": 1, "recovery": 0, "review": 0, "blocked": 0, "urgent": 1},
        "items": [
            {
                "id": "attn-1",
                "kind": "approval_required",
                "approval_id": "approval-1",
                "project_id": "project-1",
                "work_order_id": "order-2",
            }
        ],
    }
    living = {
        "state": "waiting_approval",
        "attention_count": 1,
        "needs_attention": True,
    }
    global_work = {
        "counts": {"completed": 1},
        "work_orders": [
            {"project_id": "project-1", "work_order_id": "order-1", "status": "COMPLETED"},
            {"project_id": "project-1", "work_order_id": "order-2", "status": "WAITING_APPROVAL"},
        ],
    }
    return snapshot, attention, living, global_work


def test_consistency_gate_accepts_coherent_canonical_surfaces():
    snapshot, attention, living, global_work = _baseline()
    report = WorkConsistencyGate.assert_consistent(
        global_work=global_work,
        attention=attention,
        living=living,
        project_snapshots=[snapshot],
        approval_bindings={
            "approval-1": {"project_id": "project-1", "work_order_id": "order-2"}
        },
    )
    assert report.passed is True
    assert report.authority == "read_only_qualification_gate"
    assert report.checks > 0


def test_gate_fails_when_attention_count_disagrees_with_items():
    snapshot, attention, living, global_work = _baseline()
    attention["counts"]["total"] = 0
    report = WorkConsistencyGate.evaluate(
        global_work=global_work, attention=attention, living=living, project_snapshots=[snapshot]
    )
    assert "attention_count_mismatch" in {item.code for item in report.issues}
    assert "living_attention_mismatch" in {item.code for item in report.issues}


def test_gate_fails_when_living_vishnu_claims_completion_during_recovery():
    snapshot, attention, living, global_work = _baseline()
    attention = {
        "counts": {"total": 1, "recovery": 1},
        "items": [{"id": "r1", "kind": "recovery_required", "project_id": "project-1"}],
    }
    living = {"state": "completed", "attention_count": 1, "needs_attention": True}
    report = WorkConsistencyGate.evaluate(
        global_work=global_work, attention=attention, living=living, project_snapshots=[snapshot]
    )
    assert "living_completed_during_recovery" in {item.code for item in report.issues}


def test_gate_fails_when_live_work_completed_before_completion_judge():
    snapshot, attention, living, global_work = _baseline()
    snapshot["live_work"]["state"] = "COMPLETED"
    snapshot["work_plan"]["completion"] = {
        "complete": False,
        "completion_state": "verifying",
    }
    report = WorkConsistencyGate.evaluate(
        global_work=global_work, attention=attention, living=living, project_snapshots=[snapshot]
    )
    codes = {item.code for item in report.issues}
    assert "live_completed_without_completion_judge" in codes
    assert "completion_state_surface_contradiction" in codes


def test_gate_fails_when_dependency_is_ready_without_canonical_dependency_proof():
    snapshot, attention, living, global_work = _baseline()
    snapshot = _project_snapshot(dependency_passed=False)
    snapshot["live_work"]["ready_task_ids"] = ["task-2"]
    report = WorkConsistencyGate.evaluate(
        global_work=global_work, attention=attention, living=living, project_snapshots=[snapshot]
    )
    assert "dependency_readiness_mismatch" in {item.code for item in report.issues}


def test_gate_fails_when_work_order_completed_without_passing_completion_decision():
    snapshot, attention, living, global_work = _baseline()
    snapshot["work_plan"]["work_orders"][0]["completion"]["passed"] = False
    report = WorkConsistencyGate.evaluate(
        global_work=global_work, attention=attention, living=living, project_snapshots=[snapshot]
    )
    assert "work_order_completed_without_proof" in {item.code for item in report.issues}


def test_gate_fails_cross_project_approval_misbinding():
    snapshot, attention, living, global_work = _baseline()
    report = WorkConsistencyGate.evaluate(
        global_work=global_work,
        attention=attention,
        living=living,
        project_snapshots=[snapshot],
        approval_bindings={
            "approval-1": {"project_id": "project-OTHER", "work_order_id": "order-X"}
        },
    )
    assert "approval_cross_project_misbinding" in {item.code for item in report.issues}


def test_gate_fails_completed_event_without_proof_or_with_rejected_claim():
    snapshot, attention, living, global_work = _baseline()
    snapshot["work_plan"]["work_orders"][0]["completion"]["passed"] = False
    event = {
        "event_name": "work.order.completed",
        "event_id": "event-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "work_order_id": "order-1",
    }
    report = WorkConsistencyGate.evaluate(
        global_work=global_work,
        attention=attention,
        living=living,
        project_snapshots=[snapshot],
        canonical_events=[event],
        claim_states={"order-1": "rejected"},
    )
    codes = {item.code for item in report.issues}
    assert "completion_event_without_proof" in codes
    assert "completion_event_with_rejected_claim" in codes


def test_assert_consistent_raises_structured_error_on_contradiction():
    snapshot, attention, living, global_work = _baseline()
    living["attention_count"] = 0
    with pytest.raises(WorkConsistencyError) as captured:
        WorkConsistencyGate.assert_consistent(
            global_work=global_work,
            attention=attention,
            living=living,
            project_snapshots=[snapshot],
        )
    assert captured.value.report.passed is False
    assert any(item.code == "living_attention_mismatch" for item in captured.value.report.issues)
