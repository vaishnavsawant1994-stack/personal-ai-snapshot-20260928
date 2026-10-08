from __future__ import annotations

import pytest

from future_intelligence.work_orchestration.context_pack import ContextPack
from future_intelligence.work_orchestration.models import GoalSpec, ResourceScope
from future_intelligence.work_orchestration.planner import InvalidStrategicPlan, StrategicWorkPlanner
from future_intelligence.work_orchestration.lowering import lower_to_p10_tasks


def _goal():
    return GoalSpec(
        id="g1",
        title="Release",
        objective="Prepare and deploy a release",
        desired_outcome="Verified release",
        success_criteria=("deployment verified",),
        resource_scope=ResourceScope(
            allowed_destinations=("production",),
            metadata={"allowed_capabilities": ["build", "deploy"], "risk": "medium"},
        ),
    )


def _valid_payload():
    return {
        "summary": "Build then deploy",
        "assumptions": ["repository is available"],
        "work_orders": [
            {
                "id": "build",
                "title": "Build",
                "objective": "Build release artifact",
                "worker_type": "coding",
                "dependencies": [],
                "required_capabilities": ["build"],
                "requested_tool": "build_tool",
                "parameters": {"target": "release"},
                "expected_output": "release artifact",
                "success_criteria": ["artifact exists"],
                "verification_required": True,
                "retry_limit": 1,
            },
            {
                "id": "deploy",
                "title": "Deploy",
                "objective": "Deploy the release",
                "worker_type": "tool",
                "dependencies": ["build"],
                "required_capabilities": ["deploy"],
                "requested_tool": "deploy_tool",
                "parameters": {"environment": "production"},
                "expected_output": "deployed release",
                "success_criteria": ["deployment verified"],
                "approval_required": True,
                "verification_required": True,
            },
        ],
        "milestones": [
            {
                "id": "m1",
                "title": "Release shipped",
                "objective": "Complete verified deployment",
                "work_order_ids": ["build", "deploy"],
                "success_criteria": ["deployment verified"],
            }
        ],
    }


def test_strategic_planner_builds_reviewed_dag_and_lowering_preserves_authority_boundary():
    planner = StrategicWorkPlanner(lambda _prompt, _system: _valid_payload())
    plan, review = planner.propose(
        _goal(),
        ContextPack(goal_id="g1", query="release", available_tools=("build_tool", "deploy_tool")),
        available_tools=("build_tool", "deploy_tool"),
    )

    assert review.status.value == "ready"
    assert plan.status.value == "ready"
    assert plan.work_orders[1].dependencies == ("build",)
    assert plan.work_orders[0].evidence_contract.requirements[0].min_provenance == "tool_verified"

    tasks = lower_to_p10_tasks(plan, _goal())
    assert tasks[1]["dependencies"] == ["build"]
    assert tasks[1]["requested_tool"] == "deploy_tool"
    assert tasks[1]["verification_required"] is True
    assert tasks[1]["approval_required"] is True


def test_strategic_planner_rejects_capability_expansion():
    payload = _valid_payload()
    payload["work_orders"][0]["required_capabilities"] = ["admin-everything"]
    planner = StrategicWorkPlanner(lambda _prompt, _system: payload)
    with pytest.raises(InvalidStrategicPlan, match="expands goal capabilities"):
        planner.propose(
            _goal(),
            ContextPack(goal_id="g1", query="release"),
            available_tools=("build_tool", "deploy_tool"),
        )


def test_strategic_planner_rejects_unavailable_tool():
    payload = _valid_payload()
    payload["work_orders"][0]["requested_tool"] = "invented_tool"
    planner = StrategicWorkPlanner(lambda _prompt, _system: payload)
    with pytest.raises(InvalidStrategicPlan, match="unavailable tool"):
        planner.propose(
            _goal(),
            ContextPack(goal_id="g1", query="release"),
            available_tools=("build_tool", "deploy_tool"),
        )
