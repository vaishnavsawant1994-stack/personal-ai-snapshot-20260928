from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

WORK_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_work_schema(connection: sqlite3.Connection) -> int:
    """Apply additive work-orchestration schema migrations.

    Existing P10 tables are deliberately left untouched. This schema is an
    additive normalized projection so legacy autonomy readers/writers remain
    backwards compatible while orchestration evolves.
    """
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS work_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM work_schema_migrations")
        }
        if 1 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_goals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    source_p10_goal_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_plans (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    project_id TEXT,
                    source_p10_plan_id TEXT,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(goal_id, version),
                    FOREIGN KEY(goal_id) REFERENCES work_goals(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS work_orders (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    project_id TEXT,
                    project_task_id TEXT,
                    worker_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES work_plans(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS work_order_dependencies (
                    work_order_id TEXT NOT NULL,
                    depends_on_id TEXT NOT NULL,
                    PRIMARY KEY(work_order_id, depends_on_id),
                    CHECK(work_order_id <> depends_on_id),
                    FOREIGN KEY(work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE,
                    FOREIGN KEY(depends_on_id) REFERENCES work_orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plan_reviews (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL CHECK(plan_version >= 1),
                    status TEXT NOT NULL,
                    score REAL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES work_plans(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plan_deltas (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    from_plan_id TEXT,
                    to_plan_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(goal_id) REFERENCES work_goals(id) ON DELETE CASCADE,
                    FOREIGN KEY(from_plan_id) REFERENCES work_plans(id) ON DELETE SET NULL,
                    FOREIGN KEY(to_plan_id) REFERENCES work_plans(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_work_goals_project
                    ON work_goals(project_id);
                CREATE INDEX IF NOT EXISTS idx_work_plans_goal_status
                    ON work_plans(goal_id, status);
                CREATE INDEX IF NOT EXISTS idx_work_plans_project
                    ON work_plans(project_id);
                CREATE INDEX IF NOT EXISTS idx_work_orders_plan_status
                    ON work_orders(plan_id, status);
                CREATE INDEX IF NOT EXISTS idx_work_orders_project
                    ON work_orders(project_id);
                """
            )
            connection.execute(
                "INSERT INTO work_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (1, "initial_work_orchestration_foundation", _now()),
            )
    return WORK_SCHEMA_VERSION
