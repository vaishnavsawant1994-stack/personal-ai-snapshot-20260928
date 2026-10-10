from __future__ import annotations

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.completion_runtime import install as install_completion_runtime


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
install_completion_runtime(AdvancedAutonomy)


def test_manual_completed_flag_cannot_override_missing_completion_proof(tmp_path):
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "manual.sqlite3")
    goal = autonomy.create_goal(
        "Deploy the release",
        desired_outcome="Verified deployment",
        allowed_capabilities=["deploy"],
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

    autonomy.mark_task(plan["id"], "deploy", "COMPLETED", verified=True)
    projected = autonomy.work_plan(plan["id"])

    assert projected["execution_status"] == "completed"
    assert projected["status"] != "completed"
    assert projected["completion"]["complete"] is False
    assert projected["work_orders"][0]["execution_status"] == "completed"
    assert projected["work_orders"][0]["status"] == "verifying"
    assert autonomy.work_completion(plan["id"])["complete"] is False


def test_governed_verified_execution_can_reach_canonical_completion(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        operations=_VerifiedOperations(),
        path=tmp_path / "verified.sqlite3",
    )
    goal = autonomy.create_goal(
        "Run governed operation",
        desired_outcome="Verified operation",
        allowed_capabilities=["operation"],
    )
    plan = autonomy.create_plan(
        goal["id"],
        [
            {
                "id": "operation",
                "objective": "Run operation",
                "requested_tool": "operation",
                "required_capabilities": ["operation"],
                "verification_required": True,
            }
        ],
    )

    result = autonomy.execute_task(plan["id"], "operation")
    assert result["tasks"][0]["status"] == "COMPLETED"

    projected = autonomy.work_plan(plan["id"])
    assert projected["completion"]["complete"] is True
    assert projected["status"] == "completed"
    assert projected["work_orders"][0]["status"] == "completed"


def test_completion_runtime_status_declares_completion_authority(tmp_path):
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "status.sqlite3")
    status = autonomy.status()["completion_judge"]
    assert status["installed"] is True
    assert status["authority"] == "deterministic_completion_judge"
    assert status["execution_authority"] == "canonical_work"
    assert status["compatibility_execution_path"] == "p10_p6_governed_runtime"
    assert status["client_completion_flags_authoritative"] is False
