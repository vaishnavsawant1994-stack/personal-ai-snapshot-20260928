from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ACTIVE_INSTANCE_STATES, AgentInstanceState, AgentVersionState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


class AgentWorkforceStore:
    """Durable owner-local workforce state.

    Agent definitions are reusable, but runtime instances are project scoped.
    A live instance can never be reassigned across projects; it must be stopped
    and a fresh instance created so project context cannot silently leak.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str | None = None, *, connection: sqlite3.Connection | None = None):
        if connection is None:
            if path is None:
                raise ValueError("path or connection is required")
            connection = sqlite3.connect(str(path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        self.connection = connection
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self.lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_templates(
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    system_owned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_versions(
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL REFERENCES agent_templates(id),
                    version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    memory_policy TEXT NOT NULL DEFAULT 'project_only',
                    model_policy_json TEXT NOT NULL DEFAULT '{}',
                    parent_version_id TEXT,
                    qualification_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    promoted_at TEXT,
                    UNIQUE(template_id, version)
                );
                CREATE TABLE IF NOT EXISTS agent_instances(
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL REFERENCES agent_templates(id),
                    version_id TEXT NOT NULL REFERENCES agent_versions(id),
                    project_id TEXT,
                    state TEXT NOT NULL,
                    current_work_order_id TEXT,
                    model_provider TEXT,
                    model_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_assignments(
                    id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL REFERENCES agent_instances(id),
                    project_id TEXT NOT NULL,
                    work_order_id TEXT NOT NULL UNIQUE,
                    version_id TEXT NOT NULL REFERENCES agent_versions(id),
                    status TEXT NOT NULL,
                    assigned_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_project_team(
                    project_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL REFERENCES agent_instances(id),
                    role TEXT NOT NULL,
                    is_manager INTEGER NOT NULL DEFAULT 0,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, instance_id)
                );
                CREATE TABLE IF NOT EXISTS agent_evolution_observations(
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL REFERENCES agent_templates(id),
                    version_id TEXT NOT NULL REFERENCES agent_versions(id),
                    project_id TEXT,
                    work_order_id TEXT,
                    kind TEXT NOT NULL,
                    score REAL,
                    summary TEXT NOT NULL,
                    evidence_ref TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_instances_project_state ON agent_instances(project_id, state);
                CREATE INDEX IF NOT EXISTS idx_agent_assignments_project_status ON agent_assignments(project_id, status);
                CREATE INDEX IF NOT EXISTS idx_agent_versions_template_state ON agent_versions(template_id, state);
                CREATE INDEX IF NOT EXISTS idx_agent_observations_template_version ON agent_evolution_observations(template_id, version_id, created_at);
                """
            )

    @staticmethod
    def _template(row: sqlite3.Row) -> dict:
        return dict(row)

    @staticmethod
    def _version(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["capabilities"] = json.loads(value.pop("capabilities_json"))
        value["tools"] = json.loads(value.pop("tools_json"))
        value["model_policy"] = json.loads(value.pop("model_policy_json"))
        value["qualification"] = json.loads(value.pop("qualification_json"))
        return value

    @staticmethod
    def _instance(row: sqlite3.Row) -> dict:
        return dict(row)

    def create_template(self, *, slug: str, name: str, role: str, description: str = "", system_owned: bool = False, template_id: str | None = None) -> dict:
        slug = str(slug).strip().lower().replace(" ", "-")[:100]
        if not slug or not name or not role:
            raise ValueError("slug, name and role are required")
        template_id = template_id or _id("agent")
        created_at = _now()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO agent_templates(id,slug,name,role,description,system_owned,created_at) VALUES(?,?,?,?,?,?,?)",
                (template_id, slug, str(name)[:160], str(role)[:100], str(description)[:4000], int(bool(system_owned)), created_at),
            )
        return self.get_template(template_id)

    def get_template(self, template_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM agent_templates WHERE id=?", (template_id,)).fetchone()
        if row is None:
            raise KeyError(template_id)
        return self._template(row)

    def get_template_by_slug(self, slug: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM agent_templates WHERE slug=?", (slug,)).fetchone()
        return self._template(row) if row else None

    def list_templates(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM agent_templates ORDER BY system_owned DESC,name,id").fetchall()
        return [self._template(row) for row in rows]

    def create_version(
        self,
        template_id: str,
        *,
        version: str,
        state: str = AgentVersionState.CANDIDATE.value,
        instructions: str = "",
        capabilities: list[str] | tuple[str, ...] = (),
        tools: list[str] | tuple[str, ...] = (),
        memory_policy: str = "project_only",
        model_policy: dict | None = None,
        parent_version_id: str | None = None,
        qualification: dict | None = None,
    ) -> dict:
        self.get_template(template_id)
        if state not in {item.value for item in AgentVersionState}:
            raise ValueError("invalid agent version state")
        if memory_policy not in {"project_only", "project_plus_agent", "ephemeral"}:
            raise ValueError("invalid memory policy")
        version_id = _id("agentver")
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO agent_versions(
                    id,template_id,version,state,instructions,capabilities_json,tools_json,memory_policy,
                    model_policy_json,parent_version_id,qualification_json,created_at,promoted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    version_id, template_id, str(version)[:80], state, str(instructions)[:32000],
                    _json(sorted(set(map(str, capabilities)))), _json(sorted(set(map(str, tools)))), memory_policy,
                    _json(model_policy or {}), parent_version_id, _json(qualification or {}), _now(),
                ),
            )
        return self.get_version(version_id)

    def get_version(self, version_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM agent_versions WHERE id=?", (version_id,)).fetchone()
        if row is None:
            raise KeyError(version_id)
        return self._version(row)

    def list_versions(self, template_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM agent_versions WHERE template_id=? ORDER BY created_at DESC,id", (template_id,)).fetchall()
        return [self._version(row) for row in rows]

    def preferred_version(self, template_id: str) -> dict:
        row = self.connection.execute(
            """SELECT * FROM agent_versions WHERE template_id=? AND state IN ('preferred','stable')
               ORDER BY CASE state WHEN 'preferred' THEN 0 ELSE 1 END, promoted_at DESC, created_at DESC LIMIT 1""",
            (template_id,),
        ).fetchone()
        if row is None:
            row = self.connection.execute("SELECT * FROM agent_versions WHERE template_id=? ORDER BY created_at DESC LIMIT 1", (template_id,)).fetchone()
        if row is None:
            raise KeyError(f"no versions for {template_id}")
        return self._version(row)

    def set_version_state(self, version_id: str, state: str, *, qualification: dict | None = None) -> dict:
        if state not in {item.value for item in AgentVersionState}:
            raise ValueError("invalid agent version state")
        version = self.get_version(version_id)
        with self.lock, self.connection:
            if state == AgentVersionState.PREFERRED.value:
                self.connection.execute(
                    "UPDATE agent_versions SET state='stable' WHERE template_id=? AND state='preferred' AND id<>?",
                    (version["template_id"], version_id),
                )
            self.connection.execute(
                "UPDATE agent_versions SET state=?, qualification_json=COALESCE(?,qualification_json), promoted_at=? WHERE id=?",
                (state, _json(qualification) if qualification is not None else None, _now() if state in {'stable','preferred'} else version.get('promoted_at'), version_id),
            )
        return self.get_version(version_id)

    def create_instance(self, template_id: str, *, project_id: str | None, version_id: str | None = None, model_provider: str | None = None, model_id: str | None = None) -> dict:
        version = self.get_version(version_id) if version_id else self.preferred_version(template_id)
        if version["template_id"] != template_id:
            raise ValueError("version does not belong to template")
        instance_id = _id("worker")
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO agent_instances(id,template_id,version_id,project_id,state,current_work_order_id,model_provider,model_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (instance_id, template_id, version["id"], project_id, AgentInstanceState.IDLE.value, None, model_provider, model_id, now, now),
            )
            if project_id:
                role = self.get_template(template_id)["role"]
                self.connection.execute(
                    "INSERT OR IGNORE INTO agent_project_team(project_id,instance_id,role,is_manager,joined_at) VALUES(?,?,?,?,?)",
                    (project_id, instance_id, role, int(role in {'project','project_manager'}), now),
                )
        return self.get_instance(instance_id)

    def get_instance(self, instance_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM agent_instances WHERE id=?", (instance_id,)).fetchone()
        if row is None:
            raise KeyError(instance_id)
        return self._instance(row)

    def list_instances(self, *, template_id: str | None = None, project_id: str | None = None) -> list[dict]:
        clauses, args = [], []
        if template_id:
            clauses.append("template_id=?"); args.append(template_id)
        if project_id:
            clauses.append("project_id=?"); args.append(project_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute("SELECT * FROM agent_instances" + where + " ORDER BY updated_at DESC,id", tuple(args)).fetchall()
        return [self._instance(row) for row in rows]

    def set_instance_state(self, instance_id: str, state: str) -> dict:
        if state not in {item.value for item in AgentInstanceState}:
            raise ValueError("invalid instance state")
        self.get_instance(instance_id)
        with self.lock, self.connection:
            self.connection.execute("UPDATE agent_instances SET state=?,updated_at=? WHERE id=?", (state, _now(), instance_id))
        return self.get_instance(instance_id)

    def assign(self, instance_id: str, *, project_id: str, work_order_id: str) -> dict:
        instance = self.get_instance(instance_id)
        if not project_id or not work_order_id:
            raise ValueError("project_id and work_order_id are required")
        if instance["project_id"] != project_id:
            raise PermissionError("agent instance is bound to a different project")
        if instance["state"] not in {AgentInstanceState.IDLE.value, AgentInstanceState.COMPLETED.value}:
            raise RuntimeError("agent instance is not available")
        assignment_id = _id("assign")
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO agent_assignments(id,instance_id,project_id,work_order_id,version_id,status,assigned_at,completed_at) VALUES(?,?,?,?,?,'assigned',?,NULL)",
                (assignment_id, instance_id, project_id, work_order_id, instance["version_id"], now),
            )
            self.connection.execute(
                "UPDATE agent_instances SET state=?,current_work_order_id=?,updated_at=? WHERE id=?",
                (AgentInstanceState.ASSIGNED.value, work_order_id, now, instance_id),
            )
        return self.get_assignment(assignment_id)

    def get_assignment(self, assignment_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM agent_assignments WHERE id=?", (assignment_id,)).fetchone()
        if row is None:
            raise KeyError(assignment_id)
        return dict(row)

    def finish_assignment(self, assignment_id: str, *, status: str = "completed") -> dict:
        assignment = self.get_assignment(assignment_id)
        now = _now()
        with self.lock, self.connection:
            self.connection.execute("UPDATE agent_assignments SET status=?,completed_at=? WHERE id=?", (status, now, assignment_id))
            self.connection.execute(
                "UPDATE agent_instances SET state=?,current_work_order_id=NULL,updated_at=? WHERE id=?",
                (AgentInstanceState.IDLE.value, now, assignment["instance_id"]),
            )
        return self.get_assignment(assignment_id)

    def list_project_team(self, project_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT t.project_id,t.instance_id,t.role,t.is_manager,t.joined_at,i.template_id,i.version_id,i.state,i.current_work_order_id
               FROM agent_project_team t JOIN agent_instances i ON i.id=t.instance_id WHERE t.project_id=? ORDER BY t.is_manager DESC,t.joined_at,t.instance_id""",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_observation(self, template_id: str, version_id: str, *, kind: str, summary: str, project_id: str | None = None, work_order_id: str | None = None, score: float | None = None, evidence_ref: str | None = None) -> dict:
        version = self.get_version(version_id)
        if version["template_id"] != template_id:
            raise ValueError("version does not belong to template")
        observation_id = _id("obs")
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO agent_evolution_observations(id,template_id,version_id,project_id,work_order_id,kind,score,summary,evidence_ref,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (observation_id, template_id, version_id, project_id, work_order_id, str(kind)[:100], score, str(summary)[:8000], evidence_ref, _now()),
            )
        return dict(self.connection.execute("SELECT * FROM agent_evolution_observations WHERE id=?", (observation_id,)).fetchone())

    def list_observations(self, template_id: str, *, version_id: str | None = None, limit: int = 200) -> list[dict]:
        if version_id:
            rows = self.connection.execute(
                "SELECT * FROM agent_evolution_observations WHERE template_id=? AND version_id=? ORDER BY created_at DESC LIMIT ?",
                (template_id, version_id, max(1, min(1000, int(limit)))),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM agent_evolution_observations WHERE template_id=? ORDER BY created_at DESC LIMIT ?",
                (template_id, max(1, min(1000, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict:
        total_agents = self.connection.execute("SELECT COUNT(*) FROM agent_templates").fetchone()[0]
        total_instances = self.connection.execute("SELECT COUNT(*) FROM agent_instances WHERE state<>'stopped'").fetchone()[0]
        active_instances = self.connection.execute(
            "SELECT COUNT(*) FROM agent_instances WHERE state IN (%s)" % ",".join("?" for _ in ACTIVE_INSTANCE_STATES),
            tuple(sorted(ACTIVE_INSTANCE_STATES)),
        ).fetchone()[0]
        working = self.connection.execute("SELECT COUNT(*) FROM agent_instances WHERE state='working'").fetchone()[0]
        idle = self.connection.execute("SELECT COUNT(*) FROM agent_instances WHERE state='idle'").fetchone()[0]
        projects = self.connection.execute("SELECT COUNT(DISTINCT project_id) FROM agent_instances WHERE project_id IS NOT NULL").fetchone()[0]
        running_tasks = self.connection.execute("SELECT COUNT(*) FROM agent_assignments WHERE completed_at IS NULL").fetchone()[0]
        completed = self.connection.execute("SELECT COUNT(*) FROM agent_assignments WHERE status='completed'").fetchone()[0]
        failed = self.connection.execute("SELECT COUNT(*) FROM agent_assignments WHERE status='failed'").fetchone()[0]
        denominator = completed + failed
        return {
            "total_agents": total_agents,
            "total_instances": total_instances,
            "active_instances": active_instances,
            "working_now": working,
            "idle": idle,
            "projects_using_agents": projects,
            "running_tasks": running_tasks,
            "success_rate": round(completed * 100.0 / denominator, 1) if denominator else None,
        }
