from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime
from future_intelligence.work_orchestration.replanning_runtime import install as install_replanning_runtime
from future_intelligence.work_orchestration.replanner import ReplanSafetyError, prepare_safe_replacement


class _Gate:
    pass


class _Models:
    def __init__(self):
        self.mode = "initial"

    def json(self, _prompt, **_kwargs):
        if self.mode == "initial":
            return {
                "summary": "Research and summarize",
                "assumptions": [],
                "work_orders": [
                    {
                        "id": "research",
                        "title": "Research",
                        "objective": "Research the topic",
                        "worker_type": "research",
                        "dependencies": [],
                        "required_capabilities": ["research"],
                        "expected_output": "research notes",
                        "success_criteria": ["notes are complete"],
                        "verification_required": False,
                    },
                    {
                        "id": "summarize",
                        "title": "Summarize",
                        "objective": "Summarize the research",
                        "worker_type": "research",
                        "dependencies": ["research"],
                        "required_capabilities": ["research"],
                        "expected_output": "summary",
                        "success_criteria": ["summary addresses the goal"],
                        "verification_required": False,
                    },
                ],
                "milestones": [
                    {
                        "id": "m1",
                        "title": "Complete",
                        "objective": "Produce the summary",
                        "work_order_ids": ["research", "summarize"],
                        "success_criteria": ["summary addresses the goal"],
                    }
                ],
            }
        return {
            "summary": "Use completed research and produce a revised deliverable",
            "assumptions": [],
            "work_orders": [
                {
                    "id": "draft-v2",
                    "title": "Draft revised result",
                    "objective": "Produce the revised result",
                    "worker_type": "research",
                    "dependencies": [],
                    "required_capabilities": ["research"],
                    "expected_output": "revised result",
                    "success_criteria": ["result addresses the changed conditions"],
                    "verification_required": False,
                }
            ],
            "milestones": [
                {
                    "id": "m2",
                    "title": "Revised result",
                    "objective": "Produce revised result",
                    "work_order_ids": ["draft-v2"],
                    "success_criteria": ["result addresses the changed conditions"],
                }
            ],
        }


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)
install_replanning_runtime(AdvancedAutonomy)


def test_versioned_replan_preserves_completed_work_and_records_delta(tmp_path):
    models = _Models()
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "autonomy.sqlite3", models=models)
    goal = autonomy.create_goal(
        "Research a topic",
        desired_outcome="Evidence-based result",
        allowed_capabilities=["research"],
        success_criteria=["result addresses the goal"],
    )
    initial = autonomy.propose_hierarchical_plan(goal["id"])
    assert initial["created"] is True
    plan_id = initial["p10_plan"]["id"]
    first_work_id = initial["work_plan"]["id"]

    autonomy.mark_task(plan_id, "research", "COMPLETED", verified=True, result_ref="research-result")
    before_rows = autonomy._work_bridge.work.list_orders(first_work_id)
    assert len(before_rows) == 2

    models.mode = "replan"
    result = autonomy.replan_hierarchical_plan(
        plan_id,
        reason="The requested output changed after research completed",
    )

    assert result["created"] is True
    assert result["work_plan"]["version"] == 2
    assert result["work_plan"]["supersedes_plan_id"] == first_work_id
    assert result["p10_plan"]["replan_count"] == 1
    task_by_id = {task["id"]: task for task in result["p10_plan"]["tasks"]}
    assert task_by_id["research"]["status"] == "COMPLETED"
    assert task_by_id["research"]["result_ref"] == "research-result"
    assert "draft-v2" in task_by_id
    assert "summarize" not in task_by_id

    old = autonomy._work_bridge.work.get_plan(first_work_id)
    assert old is not None and old.version == 1
    assert len(autonomy._work_bridge.work.list_orders(first_work_id)) == 2

    kinds = {(change["kind"], change["task_id"]) for change in result["delta"]["changes"]}
    assert ("remove", "summarize") in kinds
    assert ("add", "draft-v2") in kinds
    history = autonomy.replan_history(plan_id)
    assert len(history) == 1
    assert history[0]["from_version"] == 1
    assert history[0]["to_version"] == 2


def test_safe_replan_blocks_active_and_executed_id_reuse():
    with pytest.raises(ReplanSafetyError, match="cannot replan while work is active"):
        prepare_safe_replacement(
            {"tasks": [{"id": "a", "status": "RUNNING", "objective": "A"}]},
            [{"id": "b", "objective": "B", "dependencies": []}],
        )

    with pytest.raises(ReplanSafetyError, match="cannot be reused"):
        prepare_safe_replacement(
            {"tasks": [{"id": "a", "status": "FAILED", "objective": "A", "result_ref": "op-1"}]},
            [{"id": "a", "objective": "Retry A", "dependencies": []}],
        )


def test_completed_task_is_immutable_but_may_be_omitted_from_model_replan():
    current = {
        "tasks": [
            {
                "id": "done",
                "status": "COMPLETED",
                "objective": "Finished work",
                "dependencies": [],
                "required_capabilities": [],
                "result_ref": "verified-1",
            }
        ]
    }
    merged = prepare_safe_replacement(current, [{"id": "next", "objective": "Next", "dependencies": []}])
    assert [item["id"] for item in merged] == ["done", "next"]
    assert merged[0]["status"] == "COMPLETED"

    with pytest.raises(ReplanSafetyError, match="completed task done is immutable"):
        prepare_safe_replacement(
            current,
            [{"id": "done", "objective": "Changed finished work", "dependencies": []}],
        )
