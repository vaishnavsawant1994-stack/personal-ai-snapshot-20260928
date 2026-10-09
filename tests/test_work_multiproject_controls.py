from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from projects.autonomy_modes import ProjectAutonomyModeStore
from projects.store import ProjectStore
from tools.registry import Risk, Tool, ToolRegistry


def test_concurrent_project_mode_updates_remain_scoped(tmp_path):
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    rows = [projects.create(name=f"Project {index}", goal=f"Goal {index}") for index in range(5)]
    desired = ["active", "shadow", "assisted", "active", "shadow"]

    def set_mode(item):
        project, mode = item
        # Each simulated worker/runtime gets its own DB connection lifecycle.
        return ProjectAutonomyModeStore(projects.path).set(project["id"], mode).mode.value

    with ThreadPoolExecutor(max_workers=5) as pool:
        actual = list(pool.map(set_mode, zip(rows, desired)))
    assert actual == desired

    reloaded = ProjectAutonomyModeStore(projects.path)
    assert [reloaded.get(project["id"]).mode.value for project in rows] == desired


def test_emergency_stop_overrides_multiple_active_projects_and_persists(tmp_path):
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    project_a = projects.create(name="Project A", goal="A")
    project_b = projects.create(name="Project B", goal="B")
    modes = ProjectAutonomyModeStore(projects.path)
    modes.set(project_a["id"], "active")
    modes.set(project_b["id"], "active")

    settings = SimpleNamespace(autonomy_mode="act", data_dir=tmp_path / "runtime")
    registry = ToolRegistry(settings)
    tool = Tool("read.safe", "read safe state", lambda _params: {"ok": True}, risk=Risk.READ_ONLY)
    registry.register(tool)
    assert registry.authorize(tool, parameters={}).allowed is True

    assert registry.set_emergency_stop(True) is True
    decision = registry.authorize(tool, parameters={})
    assert decision.allowed is False
    assert "emergency stop" in decision.reason.lower()

    # Project mode remains durable, but cannot override the global safety authority.
    assert modes.get(project_a["id"]).mode.value == "active"
    assert modes.get(project_b["id"]).mode.value == "active"

    restarted_registry = ToolRegistry(settings)
    restarted_registry.register(tool)
    assert restarted_registry.emergency_stop is True
    restarted = restarted_registry.authorize(tool, parameters={})
    assert restarted.allowed is False
    assert "emergency stop" in restarted.reason.lower()
