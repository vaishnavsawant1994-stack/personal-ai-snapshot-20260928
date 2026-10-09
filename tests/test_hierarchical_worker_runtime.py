from __future__ import annotations

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime


class _Gate:
    pass


class _UnknownWorkerModel:
    def json(self, _prompt, **_kwargs):
        return {
            "summary": "Invalid role",
            "work_orders": [
                {
                    "id": "one",
                    "title": "One",
                    "objective": "Read material",
                    "worker_type": "superuser",
                    "required_capabilities": ["read"],
                    "expected_output": "notes",
                    "success_criteria": ["notes exist"],
                    "verification_required": False,
                }
            ],
        }


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)


def test_unknown_worker_is_held_before_p10_plan_creation(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        path=tmp_path / "unknown-worker.sqlite3",
        models=_UnknownWorkerModel(),
    )
    goal = autonomy.create_goal(
        "Read material",
        desired_outcome="Notes",
        allowed_capabilities=["read"],
        success_criteria=["notes exist"],
    )
    result = autonomy.propose_hierarchical_plan(goal["id"])
    assert result["created"] is False
    assert result["review"]["status"] == "hold"
    assert any("unknown worker role superuser" in blocker for blocker in result["review"]["blockers"])
    assert result["workers"]["authority"] == "proposal_only"


def test_runtime_status_exposes_metadata_only_capability_authority(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        path=tmp_path / "status.sqlite3",
        models=_UnknownWorkerModel(),
    )
    status = autonomy.status()["hierarchical_planning"]
    assert status["workers"]["authority"] == "proposal_only"
    assert status["capabilities"]["authority"] == "metadata_only"
    assert status["capabilities"]["execution_authority"] == "existing_tool_registry"
