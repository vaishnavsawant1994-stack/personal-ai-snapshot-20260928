import pytest

from future_intelligence.work_orchestration.models import (
    EvidenceContract,
    GoalSpec,
    Milestone,
    ResourceScope,
    WorkOrder,
    WorkPlan,
)


def _order(order_id: str, plan_id: str = "plan-1", dependencies=()):
    return WorkOrder(
        id=order_id,
        plan_id=plan_id,
        title=f"Order {order_id}",
        objective="Do the work",
        worker_type="coding",
        dependencies=tuple(dependencies),
        expected_output="Verified result",
    )


def test_goal_and_plan_json_safe_round_trip():
    goal = GoalSpec(
        id="goal-1",
        project_id="project-1",
        title="Ship feature",
        objective="Implement and verify the feature",
        desired_outcome="Production-ready feature",
        success_criteria=("tests pass",),
        resource_scope=ResourceScope(allowed_repositories=("org/repo",)),
    )
    first = _order("wo-1")
    second = _order("wo-2", dependencies=("wo-1",))
    plan = WorkPlan(
        id="plan-1",
        goal_id=goal.id,
        project_id=goal.project_id,
        version=1,
        summary="Implement then verify",
        milestones=(
            Milestone(
                id="m1",
                title="Build",
                objective="Build safely",
                work_order_ids=("wo-1", "wo-2"),
            ),
        ),
        work_orders=(first, second),
        evidence_contract=EvidenceContract(),
    )

    assert GoalSpec.from_dict(goal.to_dict()) == goal
    assert WorkPlan.from_dict(plan.to_dict()) == plan


def test_work_order_rejects_self_dependency():
    with pytest.raises(ValueError, match="cannot depend on itself"):
        _order("wo-1", dependencies=("wo-1",))


def test_plan_rejects_duplicate_work_order_ids():
    with pytest.raises(ValueError, match="ids must be unique"):
        WorkPlan(
            id="plan-1",
            goal_id="goal-1",
            version=1,
            summary="bad",
            work_orders=(_order("wo-1"), _order("wo-1")),
        )


def test_plan_rejects_unknown_dependency():
    with pytest.raises(ValueError, match="unknown dependencies"):
        WorkPlan(
            id="plan-1",
            goal_id="goal-1",
            version=1,
            summary="bad",
            work_orders=(_order("wo-1", dependencies=("missing",)),),
        )


def test_plan_rejects_dependency_cycle():
    with pytest.raises(ValueError, match="contains a cycle"):
        WorkPlan(
            id="plan-1",
            goal_id="goal-1",
            version=1,
            summary="bad",
            work_orders=(
                _order("wo-1", dependencies=("wo-2",)),
                _order("wo-2", dependencies=("wo-1",)),
            ),
        )
