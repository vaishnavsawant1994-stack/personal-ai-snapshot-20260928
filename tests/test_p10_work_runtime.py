from __future__ import annotations

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime


class _Gate:
    pass


class _VerifiedOperations:
    def create_plan(self, *_args, **_kwargs):
        return {"id": "operation-plan-1"}

    def execute(self, *_args, **_kwargs):
        return {
            "operation": {
                "operation_id": "operation-1",
                "outcome_state": "VERIFIED",
                "status": "verified",
            }
        }


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)


def test_runtime_projects_and_observes_verified_governed_completion(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        operations=_VerifiedOperations(),
        path=tmp_path / "autonomy.sqlite3",
    )
    goal = autonomy.create_goal(
        "Deploy the release",
        desired_outcome="Verified deployment",
        allowed_capabilities=["deploy"],
        success_criteria=["deployment verified"],
    )
    plan = autonomy.create_plan(
        goal["id"],
        [
            {
                "id": "deploy",
                "objective": "Deploy release",
                "requested_tool": "deploy",
                "required_capabilities": ["deploy"],
                "verification_required": True,
            }
        ],
    )

    projected = autonomy.work_plan(plan["id"])
    assert projected["version"] == 1
    assert projected["work_orders"][0]["status"] == "queued"

    result = autonomy.execute_task(plan["id"], "deploy")
    assert result["tasks"][0]["status"] == "COMPLETED"

    evidence = autonomy.work_evidence(plan["id"], "deploy")
    assert len(evidence) == 1
    assert evidence[0]["provenance"] == "tool_verified"
    assert evidence[0]["verification_state"] == "verified"

    status = autonomy.status()["work_orchestration"]
    assert status["mode"] == "canonical_authority"
    assert status["evidence"] == 1
    assert status["claims"] == 1


def test_manual_verified_mark_does_not_manufacture_tool_evidence(tmp_path):
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "manual.sqlite3")
    goal = autonomy.create_goal("Review a local note", desired_outcome="Reviewed note")
    plan = autonomy.create_plan(
        goal["id"],
        [{"id": "review", "objective": "Review note", "verification_required": False}],
    )

    result = autonomy.mark_task(plan["id"], "review", "COMPLETED", verified=True)
    assert result["state"] == "COMPLETED"
    assert autonomy.work_evidence(plan["id"], "review") == []


def test_replan_creates_new_work_plan_version(tmp_path):
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "replan.sqlite3")
    goal = autonomy.create_goal("Research topic", desired_outcome="Verified research")
    plan = autonomy.create_plan(goal["id"], [{"id": "a", "objective": "First pass"}])
    assert autonomy.work_plan(plan["id"])["version"] == 1

    autonomy.replan(
        plan["id"],
        [{"id": "b", "objective": "Second pass"}],
        reason="new evidence",
    )
    projected = autonomy.work_plan(plan["id"])
    assert projected["version"] == 2
    assert projected["supersedes_plan_id"] == plan["id"]
