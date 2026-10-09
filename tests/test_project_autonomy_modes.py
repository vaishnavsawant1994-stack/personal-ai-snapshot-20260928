from __future__ import annotations

import sqlite3

import pytest

from projects.autonomy_modes import ProjectAutonomyMode, ProjectAutonomyModeStore
from projects.store import ProjectStore


def test_project_autonomy_mode_defaults_to_assisted_and_persists(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.sqlite3")
    project = project_store.create(name="Launch", goal="Launch safely")
    modes = ProjectAutonomyModeStore(project_store.path)

    default = modes.get(project["id"])
    assert default.mode is ProjectAutonomyMode.ASSISTED
    assert default.updated_by == "default"

    shadow = modes.set(project["id"], "shadow")
    assert shadow.mode is ProjectAutonomyMode.SHADOW

    reloaded = ProjectAutonomyModeStore(project_store.path).get(project["id"])
    assert reloaded.mode is ProjectAutonomyMode.SHADOW

    active = modes.set(project["id"], ProjectAutonomyMode.ACTIVE)
    assert active.mode is ProjectAutonomyMode.ACTIVE


def test_invalid_mode_and_foreign_project_are_rejected(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.sqlite3")
    project = project_store.create(name="Launch", goal="Launch safely")
    modes = ProjectAutonomyModeStore(project_store.path)

    with pytest.raises(ValueError):
        modes.set(project["id"], "unbounded")
    with pytest.raises(KeyError, match="project not found"):
        modes.set("missing-project", "active")


def test_mode_store_contains_no_session_or_credential_fields(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.sqlite3")
    project = project_store.create(name="Launch", goal="Launch safely")
    modes = ProjectAutonomyModeStore(project_store.path)
    modes.set(project["id"], "active")

    with sqlite3.connect(project_store.path) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(project_autonomy_modes)")}
        row = con.execute("SELECT * FROM project_autonomy_modes WHERE project_id=?", (project["id"],)).fetchone()

    assert columns == {"project_id", "mode", "updated_at", "updated_by"}
    assert all("token" not in str(value).lower() and "session" not in str(value).lower() for value in row)
