from __future__ import annotations

from future_intelligence.work_orchestration.models import (
    EvidenceContract,
    EvidenceRequirement,
    GoalSpec,
    ResourceScope,
    WorkOrder,
    WorkPlan,
)
from future_intelligence.work_orchestration.reviewer import PlanReviewer


def test_reviewer_holds_scope_expansion_and_degrades_missing_success_criteria():
    goal = GoalSpec(
        id="g1",
        title="Goal",
        objective="Do scoped work",
        desired_outcome="Verified result",
        success_criteria=("verified",),
        resource_scope=ResourceScope(
            allowed_destinations=("internal",),
            metadata={"allowed_capabilities": ["read"]},
        ),
    )
    plan = WorkPlan(
        id="p1",
        goal_id="g1",
        version=1,
        summary="Scoped plan",
        work_orders=(
            WorkOrder(
                id="w1",
                plan_id="p1",
                title="Read",
                objective="Read data",
                worker_type="tool",
                allowed_capabilities=("read",),
                resource_scope=ResourceScope(
                    allowed_destinations=("external",),
                    metadata={"requested_tool": "reader"},
                ),
                expected_output="data",
                evidence_contract=EvidenceContract(
                    requirements=(EvidenceRequirement(kind="verify"),)
                ),
            ),
        ),
    )
    review = PlanReviewer.review(plan, goal, available_tools=("reader",))
    assert review.status.value == "hold"
    assert any("destinations" in item for item in review.blockers)
    assert any("success criteria" in item for item in review.warnings)


def test_reviewer_marks_clean_plan_ready():
    goal = GoalSpec(
        id="g1",
        title="Goal",
        objective="Do work",
        desired_outcome="Verified result",
        success_criteria=("verified",),
        resource_scope=ResourceScope(metadata={"allowed_capabilities": ["read"]}),
    )
    plan = WorkPlan(
        id="p1",
        goal_id="g1",
        version=1,
        summary="Clean plan",
        work_orders=(
            WorkOrder(
                id="w1",
                plan_id="p1",
                title="Read",
                objective="Read data",
                worker_type="tool",
                allowed_capabilities=("read",),
                resource_scope=ResourceScope(metadata={"requested_tool": "reader"}),
                expected_output="data",
                success_criteria=("data verified",),
                evidence_contract=EvidenceContract(
                    requirements=(EvidenceRequirement(kind="verify"),)
                ),
            ),
        ),
    )
    review = PlanReviewer.review(plan, goal, available_tools=("reader",))
    assert review.status.value == "ready"
    assert review.blockers == ()
    assert review.warnings == ()
