from __future__ import annotations

import pytest

from future_intelligence.autonomy import AdvancedAutonomy
from future_intelligence.autonomy_runtime import install as install_p10_runtime
from future_intelligence.work_orchestration.p10_runtime import install as install_work_runtime
from future_intelligence.work_orchestration.project_mode_runtime import install as install_project_mode_runtime
from projects.store import ProjectStore
from server.project_autonomy_api import ProjectAutonomyService, project_autonomy_router


class _Gate:
    pass


class _Registry:
    def authenticate(self, _device_id, _token):
        return True


install_p10_runtime(AdvancedAutonomy)
install_work_runtime(AdvancedAutonomy)
install_project_mode_runtime(AdvancedAutonomy)


def _service(tmp_path):
    store = ProjectStore(tmp_path / "projects.sqlite3")
    autonomy = AdvancedAutonomy(gate=_Gate(), path=tmp_path / "autonomy.sqlite3")
    autonomy.project_store = store
    service = ProjectAutonomyService({"advanced_autonomy": autonomy}, store)
    return service, store, autonomy


def _bound_plan(store, autonomy, project_id):
    goal = autonomy.create_goal("Run project", allowed_capabilities=["operation"])
    autonomy._work_bridge.project_goal({**goal, "project_id": project_id})
    plan = autonomy.create_plan(
        goal["id"],
        [{"id": "task", "objective": "Do work", "requested_tool": "operation", "required_capabilities": ["operation"]}],
    )
    autonomy._work_bridge.project_plan(plan, {**goal, "project_id": project_id})
    return plan


def test_service_exposes_mode_semantics_and_existing_authorities(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = store.create(name="Project", goal="Do work")

    result = service.get(project["id"])

    assert result["mode"] == "assisted"
    assert result["semantics"]["manual_execution"] is True
    assert result["semantics"]["automatic_execution"] is False
    assert result["execution_authority"] == "existing_p10_p6_runtime"
    assert result["approval_authority"] == "existing_approval_manager"
    assert result["recovery_authority"] == "existing_recovery_authority"
    assert result["completion_authority"] == "deterministic_completion_judge"


def test_non_active_advance_now_fails_before_mode_mutation(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = store.create(name="Project", goal="Do work")

    with pytest.raises(ValueError, match="advance_now requires active mode"):
        service.set(
            project["id"],
            "shadow",
            device_id="device-1",
            session_id="session-1",
            reauthenticated_at=None,
            advance_now=True,
        )

    assert service.get(project["id"])["mode"] == "assisted"


def test_cross_project_plan_cannot_be_auto_advanced(tmp_path):
    service, store, autonomy = _service(tmp_path)
    first = store.create(name="First", goal="First")
    second = store.create(name="Second", goal="Second")
    plan = _bound_plan(store, autonomy, first["id"])
    service.set(first["id"], "active", device_id="device-1", session_id="session-1", reauthenticated_at=None)

    with pytest.raises(KeyError, match="project work plan not found"):
        service.advance(
            second["id"],
            plan["id"],
            device_id="device-1",
            session_id="session-1",
            reauthenticated_at=None,
        )


def test_active_advance_now_without_plan_is_safe_noop(tmp_path):
    service, store, _autonomy = _service(tmp_path)
    project = store.create(name="Project", goal="Do work")

    result = service.set(
        project["id"],
        "active",
        device_id="device-1",
        session_id="session-1",
        reauthenticated_at=None,
        advance_now=True,
    )

    assert result["mode"] == "active"
    assert result["advance"]["executed_task_ids"] == []
    assert result["advance"]["stop_reason"] == "no_work_plan"


def test_router_exposes_read_mode_trusted_mode_mutation_and_active_advance_only(tmp_path):
    _service_obj, store, autonomy = _service(tmp_path)
    runtime = {"advanced_autonomy": autonomy, "device_registry": _Registry()}
    router = project_autonomy_router(runtime, store)
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or ())

    assert methods_by_path["/iphone/api/projects/{project_id}/work/autonomy"] == {"GET", "PUT"}
    assert methods_by_path["/iphone/api/projects/{project_id}/work/{plan_id}/advance"] == {"POST"}
    assert all("DELETE" not in methods for methods in methods_by_path.values())
    assert not any("approve" in path or "recover" in path or "retry" in path for path in methods_by_path)
