from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectAutonomyMode(StrEnum):
    SHADOW = "shadow"
    ASSISTED = "assisted"
    ACTIVE = "active"


@dataclass(frozen=True)
class ProjectAutonomySettings:
    project_id: str
    mode: ProjectAutonomyMode
    updated_at: str
    updated_by: str = "owner"

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "mode": self.mode.value,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }


class ProjectAutonomyModeStore:
    """Durable per-Project autonomy mode stored in the existing Projects SQLite DB."""

    def __init__(self, project_db_path: str | Path) -> None:
        self.path = Path(project_db_path)
        self._init()

    def con(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init(self) -> None:
        with self.con() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS project_autonomy_modes(
                    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                    mode TEXT NOT NULL DEFAULT 'assisted'
                        CHECK(mode IN ('shadow','assisted','active')),
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL DEFAULT 'owner'
                )
                """
            )

    def get(self, project_id: str) -> ProjectAutonomySettings:
        project_id = str(project_id)
        with self.con() as con:
            if not con.execute("SELECT 1 FROM projects WHERE id=? AND status!='archived'", (project_id,)).fetchone():
                raise KeyError("project not found")
            row = con.execute(
                "SELECT project_id,mode,updated_at,updated_by FROM project_autonomy_modes WHERE project_id=?",
                (project_id,),
            ).fetchone()
        if row is None:
            return ProjectAutonomySettings(project_id, ProjectAutonomyMode.ASSISTED, "", "default")
        return ProjectAutonomySettings(
            project_id=str(row["project_id"]),
            mode=ProjectAutonomyMode(str(row["mode"])),
            updated_at=str(row["updated_at"]),
            updated_by=str(row["updated_by"]),
        )

    def set(self, project_id: str, mode: ProjectAutonomyMode | str, *, updated_by: str = "owner") -> ProjectAutonomySettings:
        project_id = str(project_id)
        resolved = mode if isinstance(mode, ProjectAutonomyMode) else ProjectAutonomyMode(str(mode))
        stamp = _now()
        with self.con() as con:
            if not con.execute("SELECT 1 FROM projects WHERE id=? AND status!='archived'", (project_id,)).fetchone():
                raise KeyError("project not found")
            con.execute(
                """
                INSERT INTO project_autonomy_modes(project_id,mode,updated_at,updated_by)
                VALUES(?,?,?,?)
                ON CONFLICT(project_id) DO UPDATE SET
                    mode=excluded.mode,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (project_id, resolved.value, stamp, str(updated_by)[:120]),
            )
        return ProjectAutonomySettings(project_id, resolved, stamp, str(updated_by)[:120])
