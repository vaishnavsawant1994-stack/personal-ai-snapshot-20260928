from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime
from future_intelligence.work_orchestration.versioned_replanning import install as install_versioned_replanning


class _Gate:
    pass


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)
install_versioned_replanning(AdvancedAutonomy)


def _autonomy(tmp_path):
    return AdvancedAutonomy(gate=_Gate(), path=tmp_path / "autonomy.sqlite3")


def _goal_and_plan(autonomy):
    goal = autonomy.create_goal(
        "Prepare an evidence-based launch brief",
        desired_outcome="A verified launch brief",
        allowed_capabilities=["research"],
        success_criteria=["brief is supported by evidence"],
    )
    plan = autonomy.create_plan(
        goal["id"],
        [
            {
                "id": "research",
                "objective": "Research the launch inputs",
                "required_capabilities": ["research"],
            },
            {
                "id": "draft",
                "objective": "Draft the launch brief",
                "dependencies": ["research"],
                "required_capabilities": ["research"],
            },
        ],
    )
    return goal, plan


def test_versioned_replan_preserves_completed_work_and_records_semantic_delta(tmp_path):
    autonomy = _autonomy(tmp_path)
    _goal, plan = _goal_and_plan(autonomy)
    first = autonomy.work_plan(plan["id"])

    autonomy.mark_task(plan["id"], "research", "COMPLETED", verified=True)
    replanned = autonomy.replan(
        plan["id"],
        [
            {
                "id": "review",
                "objective": "Review the evidence before drafting",
                "dependencies": ["research"],
                "required_capabilities": ["research"],
            }
        ],
        reason="new evidence requires an explicit review step",
        trigger="evidence_changed",
    )

    assert replanned["replan_count"] == 1
    assert [task["id"] for task in replanned["tasks"]] == ["research", "review"]
    assert replanned["tasks"][0]["status"] == "COMPLETED"
    assert replanned["tasks"][1]["status"] == "WAITING"
    assert replanned["replan_history"][0]["preserved_completed_task_ids"] == ["research"]
    assert "draft" in replanned["replan_history"][0]["retired_task_ids"]

    versions = autonomy.work_plan_versions(plan["id"])
    assert [item["version"] for item in versions] == [1, 2]
    assert versions[0]["id"] == first["id"]
    assert versions[1]["supersedes_plan_id"] == versions[0]["id"]

    deltas = autonomy.work_plan_deltas(plan["id"])
    assert len(deltas) == 1
    actions = {(item["action"], item["task_id"]) for item in deltas[0]["items"]}
    assert ("remove", "draft") in actions
    assert ("add", "review") in actions
    assert deltas[0]["preserved_completed_task_ids"] == ["research"]

    old_orders = autonomy._work_bridge.work.list_orders(versions[0]["id"])
    new_orders = autonomy._work_bridge.work.list_orders(versions[1]["id"])
    assert len(old_orders) == 2
    assert len(new_orders) == 2
    assert {order.resource_scope.metadata["p10_task_id"] for order in old_orders} == {"research", "draft"}
    assert {order.resource_scope.metadata["p10_task_id"] for order in new_orders} == {"research", "review"}


def test_replan_refuses_to_rewrite_active_work(tmp_path):
    autonomy = _autonomy(tmp_path)
    _goal, plan = _goal_and_plan(autonomy)
    autonomy.mark_task(plan["id"], "research", "RUNNING")

    with pytest.raises(RuntimeError, match="must resolve before replanning"):
        autonomy.replan(
            plan["id"],
            [{"id": "replacement", "objective": "Replace active work", "required_capabilities": ["research"]}],
        )

    assert len(autonomy.work_plan_versions(plan["id"])) == 1
    assert autonomy.work_plan_deltas(plan["id"]) == []


def test_replan_retires_failed_work_without_leaving_it_in_active_graph(tmp_path):
    autonomy = _autonomy(tmp_path)
    _goal, plan = _goal_and_plan(autonomy)
    autonomy.mark_task(plan["id"], "research", "FAILED", result_ref="failure-1")

    replanned = autonomy.replan(
        plan["id"],
        [{"id": "repair", "objective": "Repair the failed research step", "required_capabilities": ["research"]}],
        reason="repair after failure",
        trigger="tool_failure",
    )

    assert [task["id"] for task in replanned["tasks"]] == ["repair"]
    assert replanned["state"] == "READY"
    assert replanned["retired_tasks"][-2]["id"] == "research"
    assert replanned["retired_tasks"][-2]["status"] == "FAILED"


def test_replan_cannot_reuse_executed_or_terminal_task_identity(tmp_path):
    autonomy = _autonomy(tmp_path)
    _goal, plan = _goal_and_plan(autonomy)
    autonomy.mark_task(plan["id"], "research", "FAILED")

    with pytest.raises(ValueError, match="cannot reuse immutable execution task ids"):
        autonomy.replan(
            plan["id"],
            [{"id": "research", "objective": "Pretend the failed task is new", "required_capabilities": ["research"]}],
        )


def test_completed_plan_is_not_reopened_by_replan(tmp_path):
    autonomy = _autonomy(tmp_path)
    goal = autonomy.create_goal("One step", allowed_capabilities=["research"])
    plan = autonomy.create_plan(
        goal["id"],
        [{"id": "only", "objective": "Finish it", "required_capabilities": ["research"]}],
    )
    autonomy.mark_task(plan["id"], "only", "COMPLETED", verified=True)

    with pytest.raises(RuntimeError, match="terminal plan cannot be replanned"):
        autonomy.replan(plan["id"], [])


def test_status_exposes_versioned_replanning_as_planning_only(tmp_path):
    autonomy = _autonomy(tmp_path)
    status = autonomy.status()["versioned_replanning"]
    assert status["installed"] is True
    assert status["authority"] == "planning_only"
    assert status["active_work_rewrite"] == "blocked"
    assert status["completed_work"] == "immutable"
