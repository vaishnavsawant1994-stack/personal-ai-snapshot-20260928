from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.project_mode_runtime import install as install_project_mode_runtime
from projects.store import ProjectStore


class _Gate:
    pass


class _ApprovalOperations:
    def create_plan(self, *_args, **_kwargs):
        return {"id": "operation-plan-1"}

    def execute(self, *_args, **_kwargs):
        return {"approval_required": True}


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_project_mode_runtime(AdvancedAutonomy)


def _project_bound_autonomy(tmp_path, *, operations=None, task_count=1):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    project = store.create(name="Launch", goal="Launch safely")
    autonomy = AdvancedAutonomy(
        gate=_Gate(),
        operations=operations,
        path=tmp_path / "autonomy.sqlite3",
    )
    autonomy.project_store = store
    goal = autonomy.create_goal(
        "Launch safely",
        desired_outcome="Finished launch",
        allowed_capabilities=["operation"],
    )
    autonomy._work_bridge.project_goal({**goal, "project_id": project["id"]})
    tasks = [
        {
            "id": f"task-{index + 1}",
            "objective": f"Do step {index + 1}",
            "requested_tool": "operation",
            "required_capabilities": ["operation"],
            "verification_required": True,
            "dependencies": ([f"task-{index}"] if index else []),
        }
        for index in range(task_count)
    ]
    plan = autonomy.create_plan(goal["id"], tasks)
    autonomy._work_bridge.project_plan(plan, {**goal, "project_id": project["id"]})
    return autonomy, store, project, plan


def test_shadow_mode_blocks_existing_manual_execute_path(tmp_path):
    autonomy, _store, project, plan = _project_bound_autonomy(tmp_path)
    autonomy.set_project_autonomy_mode(project["id"], "shadow")

    with pytest.raises(PermissionError, match="shadow mode"):
        autonomy.execute_task(plan["id"], "task-1")

    persisted = autonomy.plan(plan["id"])
    assert persisted["tasks"][0]["status"] == "WAITING"


def test_assisted_allows_manual_but_rejects_automatic_dispatch(tmp_path):
    autonomy, _store, project, plan = _project_bound_autonomy(tmp_path)
    assert autonomy.project_autonomy_mode(project["id"])["mode"] == "assisted"

    with pytest.raises(PermissionError, match="active mode"):
        autonomy.execute_task(plan["id"], "task-1", _project_automatic=True)

    result = autonomy.execute_task(plan["id"], "task-1")
    assert result["tasks"][0]["status"] == "COMPLETED"


def test_active_mode_bounded_advance_uses_existing_p10_path(tmp_path):
    autonomy, _store, project, plan = _project_bound_autonomy(tmp_path, task_count=2)
    autonomy.set_project_autonomy_mode(project["id"], "active")

    result = autonomy.advance_project_plan(plan["id"], max_steps=10)

    assert result["mode"] == "active"
    assert result["executed_task_ids"] == ["task-1", "task-2"]
    assert result["stop_reason"] == "plan_state:completed"
    persisted = autonomy.plan(plan["id"])
    assert [item["status"] for item in persisted["tasks"]] == ["COMPLETED", "COMPLETED"]


def test_active_mode_stops_immediately_on_existing_approval_gate(tmp_path):
    autonomy, _store, project, plan = _project_bound_autonomy(
        tmp_path,
        operations=_ApprovalOperations(),
    )
    autonomy.set_project_autonomy_mode(project["id"], "active")

    result = autonomy.advance_project_plan(
        plan["id"],
        device_id="device-1",
        session_id="session-1",
    )

    assert result["executed_task_ids"] == ["task-1"]
    assert result["stop_reason"] == "task_state:waiting_approval"
    persisted = autonomy.plan(plan["id"])
    assert persisted["tasks"][0]["status"] == "WAITING_APPROVAL"


def test_emergency_stop_overrides_active_mode(tmp_path):
    autonomy, _store, project, plan = _project_bound_autonomy(tmp_path)
    autonomy.set_project_autonomy_mode(project["id"], "active")
    autonomy.emergency_stop("test")

    with pytest.raises(PermissionError, match="Emergency Stop"):
        autonomy.advance_project_plan(plan["id"])


def test_non_project_p10_plan_keeps_existing_execution_behavior(tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "autonomy.sqlite3")
    autonomy.project_store = store
    goal = autonomy.create_goal("Internal work", allowed_capabilities=["operation"])
    plan = autonomy.create_plan(
        goal["id"],
        [{"id": "internal", "objective": "Do internal work", "requested_tool": "operation", "required_capabilities": ["operation"]}],
    )

    result = autonomy.execute_task(plan["id"], "internal")
    assert result["tasks"][0]["status"] == "COMPLETED"
