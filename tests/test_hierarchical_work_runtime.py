from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime
from future_intelligence.work_orchestration.planner import InvalidStrategicPlan


class _Gate:
    pass


class _Models:
    def json(self, _prompt, **_kwargs):
        return {
            "summary": "Research then summarize",
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
                    "success_criteria": ["notes contain evidence"],
                    "verification_required": False,
                },
                {
                    "id": "summarize",
                    "title": "Summarize",
                    "objective": "Summarize findings",
                    "worker_type": "reviewer",
                    "dependencies": ["research"],
                    "required_capabilities": ["research"],
                    "expected_output": "final summary",
                    "success_criteria": ["summary addresses the goal"],
                    "verification_required": False,
                },
            ],
            "milestones": [
                {
                    "id": "m1",
                    "title": "Research complete",
                    "objective": "Produce final research summary",
                    "work_order_ids": ["research", "summarize"],
                    "success_criteria": ["summary addresses the goal"],
                }
            ],
        }


class _BlockedToolModels:
    def json(self, _prompt, **_kwargs):
        return {
            "summary": "Try blocked tool",
            "work_orders": [
                {
                    "id": "blocked",
                    "title": "Blocked",
                    "objective": "Attempt blocked tool",
                    "worker_type": "tool",
                    "required_capabilities": ["research"],
                    "requested_tool": "blocked_tool",
                    "expected_output": "never created",
                    "success_criteria": ["never runs"],
                }
            ],
        }


class _Tool:
    def __init__(self, name, prohibited=False):
        self.name = name
        self.prohibited = prohibited


class _Registry:
    def all(self):
        return [_Tool("allowed_tool"), _Tool("blocked_tool", prohibited=True)]


class _Executor:
    tools = _Registry()


class _Operations:
    executor = _Executor()


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)


def test_hierarchical_plan_lowers_into_existing_p10_and_preserves_enrichment(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        path=tmp_path / "autonomy.sqlite3",
        models=_Models(),
    )
    goal = autonomy.create_goal(
        "Research a topic",
        desired_outcome="Evidence-based summary",
        allowed_capabilities=["research"],
        success_criteria=["summary addresses the goal"],
    )

    result = autonomy.propose_hierarchical_plan(goal["id"])
    assert result["created"] is True
    assert result["review"]["status"] == "ready"
    assert result["authority"] == "existing_p10_p6_runtime"

    p10_plan = result["p10_plan"]
    assert p10_plan["tasks"][1]["dependencies"] == ["research"]

    stored = autonomy.work_plan(p10_plan["id"])
    assert stored["critic"]["hierarchical_planning"] is True
    assert stored["milestones"][0]["title"] == "Research complete"
    assert stored["latest_review"]["status"] == "ready"

    autonomy.mark_task(p10_plan["id"], "research", "COMPLETED", verified=True)
    after = autonomy.work_plan(p10_plan["id"])
    assert after["critic"]["hierarchical_planning"] is True
    assert after["milestones"][0]["title"] == "Research complete"
    assert after["work_orders"][0]["status"] == "completed"


def test_hierarchical_status_exposes_planning_only_authority(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        path=tmp_path / "status.sqlite3",
        models=_Models(),
    )
    status = autonomy.status()["hierarchical_planning"]
    assert status["installed"] is True
    assert status["authority"] == "planning_only"
    assert status["execution_authority"] == "existing_p10_p6_runtime"


def test_prohibited_registry_tool_is_not_available_to_strategic_planner(tmp_path):
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        operations=_Operations(),
        path=tmp_path / "prohibited.sqlite3",
        models=_BlockedToolModels(),
    )
    goal = autonomy.create_goal(
        "Research safely",
        desired_outcome="Safe research",
        allowed_capabilities=["research"],
        success_criteria=["safe result"],
    )

    with pytest.raises(InvalidStrategicPlan, match="unavailable tool blocked_tool"):
        autonomy.propose_hierarchical_plan(goal["id"])
