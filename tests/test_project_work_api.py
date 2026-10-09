from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.hierarchical_runtime import install as install_hierarchical_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.versioned_replanning import install as install_versioned_replanning
from projects.store import ProjectStore
from server.project_work_api import ProjectWorkService


class _Gate:
    pass


class _Models:
    def json(self, _prompt, **_kwargs):
        return {
            "summary": "Research the project and produce the requested deliverable",
            "assumptions": [],
            "work_orders": [
                {
                    "id": "research",
                    "title": "Research",
                    "objective": "Collect and synthesize the project evidence",
                    "worker_type": "research",
                    "dependencies": [],
                    "required_capabilities": ["research"],
                    "expected_output": "evidence-backed deliverable",
                    "success_criteria": ["deliverable is complete"],
                    "verification_required": False,
                }
            ],
            "milestones": [
                {
                    "id": "m1",
                    "title": "Deliverable ready",
                    "objective": "Complete the requested deliverable",
                    "work_order_ids": ["research"],
                    "success_criteria": ["deliverable is complete"],
                }
            ],
        }


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_hierarchical_runtime(AdvancedAutonomy)
install_versioned_replanning(AdvancedAutonomy)


def _service(tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        path=tmp_path / "autonomy.sqlite3",
        models=_Models(),
    )
    return ProjectWorkService({"advanced_autonomy": autonomy}, store), store, autonomy


def _project(store, name="Research launch"):
    return store.create(
        name=name,
        goal="Research the launch question and prepare a final deliverable",
        description="Use the project workspace as the bounded context.",
        project_type="research",
        success_criteria="deliverable is complete",
        instructions="Prefer evidence-backed conclusions.",
    )


def test_project_work_snapshot_is_empty_before_planning(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = _project(store)

    snapshot = service.snapshot(project["id"])

    assert snapshot["state"] == "not_planned"
    assert snapshot["project_id"] == project["id"]
    assert snapshot["work_plan"] is None
    assert snapshot["live_work"]["state"] == "NOT_PLANNED"
    assert snapshot["legacy_project_task_runner_preserved"] is True


def test_project_plan_binds_goal_and_workplan_without_rewriting_existing_project_tasks(tmp_path):
    service, store, autonomy = _service(tmp_path)
    project = _project(store)
    project = store.add_task(
        project["id"],
        title="Owner-created task",
        description="This legacy Project task must remain untouched.",
        owner="owner",
    )
    legacy = next(task for task in project["tasks"] if task["title"] == "Owner-created task")

    result = service.create_plan(project["id"], playbook_id="research_project")
    snapshot = service.snapshot(project["id"])
    persisted_project = store.get(project["id"])
    persisted_legacy = next(task for task in persisted_project["tasks"] if task["id"] == legacy["id"])

    assert result["created"] is True
    assert result["project_id"] == project["id"]
    assert result["playbook"]["id"] == "research_project"
    assert snapshot["state"] == "planned"
    assert snapshot["work_plan"]["project_id"] == project["id"]
    assert snapshot["work_plan"]["critic"]["playbook_id"] == "research_project"
    assert snapshot["p10_plan"]["goal_id"] == result["goal_id"]
    assert snapshot["live_work"]["ready_task_ids"] == ["research"]
    assert persisted_legacy["status"] == legacy["status"]
    assert persisted_legacy["execution_workflow_id"] is None
    goal_record = autonomy._work_bridge.work.latest_project_goal_record(project["id"])
    assert goal_record["source_p10_goal_id"] == result["goal_id"]


def test_project_plan_reuses_matching_goal_and_can_force_a_new_goal(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = _project(store)

    first = service.create_plan(project["id"])
    second = service.create_plan(project["id"])
    third = service.create_plan(project["id"], force_new_goal=True)

    assert second["goal_id"] == first["goal_id"]
    assert third["goal_id"] != first["goal_id"]


def test_project_input_change_creates_new_session_bound_goal(tmp_path):
    service, store, autonomy = _service(tmp_path)
    project = _project(store)
    first = service.create_plan(project["id"], session_id="session-a")
    first_goal = autonomy.goal(first["goal_id"], owner_id="owner")
    assert first_goal["session_id"] == "session-a"

    store.update(
        project["id"],
        {
            "success_criteria": "deliverable is complete and independently reviewed",
            "instructions": "Require an explicit review before completion.",
        },
    )
    second = service.create_plan(project["id"], session_id="session-b")
    second_goal = autonomy.goal(second["goal_id"], owner_id="owner")

    assert second["goal_id"] != first["goal_id"]
    assert second_goal["session_id"] == "session-b"
    assert second_goal["success_criteria"] == ["deliverable is complete and independently reviewed"]
    assert second_goal["constraints"] == ["Require an explicit review before completion."]


def test_live_work_execute_uses_existing_p10_path_and_updates_snapshot(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = _project(store)
    created = service.create_plan(project["id"])
    plan_id = created["p10_plan"]["id"]

    snapshot = service.execute_task(
        project["id"],
        plan_id,
        "research",
        device_id="device-1",
        session_id="session-1",
        reauthenticated_at=None,
    )

    assert snapshot["live_work"]["state"] == "COMPLETED"
    assert snapshot["live_work"]["task_counts"]["COMPLETED"] == 1
    assert snapshot["p10_plan"]["tasks"][0]["result_ref"] == "read-only-orchestration"


def test_project_live_controls_pause_resume_and_cancel_existing_p10_plan(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = _project(store)
    created = service.create_plan(project["id"])
    plan_id = created["p10_plan"]["id"]

    paused = service.pause(project["id"], plan_id)
    assert paused["live_work"]["state"] == "PAUSED"
    resumed = service.resume(project["id"], plan_id)
    assert resumed["live_work"]["state"] == "READY"
    cancelled = service.cancel(
        project["id"],
        plan_id,
        reason="owner stopped this project",
        device_id="device-1",
        session_id="session-1",
    )
    assert cancelled["live_work"]["state"] == "CANCELLED"


def test_project_work_plan_cannot_be_controlled_from_another_project(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    first = _project(store, "First")
    second = _project(store, "Second")
    created = service.create_plan(first["id"])

    with pytest.raises(KeyError, match="project work plan not found"):
        service.pause(second["id"], created["p10_plan"]["id"])


def test_project_work_history_exposes_one_grouped_source_with_versioned_work(tmp_path):
    service, store, autonomy = _service(tmp_path)
    project = _project(store)
    created = service.create_plan(project["id"])
    plan_id = created["p10_plan"]["id"]
    autonomy.replan(
        plan_id,
        [
            {
                "id": "review",
                "objective": "Review the research deliverable",
                "required_capabilities": ["review"],
            }
        ],
        reason="owner requested review",
        trigger="owner_instruction",
    )

    history = service.history(project["id"])

    assert history["authority"] == "history_only"
    assert len(history["plans"]) == 1
    source = history["plans"][0]
    assert source["source_p10_plan_id"] == plan_id
    assert source["work_plan"]["version"] == 2
    assert [version["version"] for version in source["versions"]] == [1, 2]
    assert source["deltas"][0]["reason"] == "owner requested review"
