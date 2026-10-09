from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .migrations import migrate_work_schema

WORK_DURABILITY_SCHEMA_VERSION = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_work_durability_schema(connection: sqlite3.Connection) -> int:
    """Add causal execution history without replacing existing Work/P10 tables."""

    migrate_work_schema(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM work_schema_migrations")
        }
        if 3 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_attempts (
                    id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
                    parent_attempt_id TEXT,
                    worker_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    runtime_epoch INTEGER NOT NULL CHECK(runtime_epoch >= 0),
                    execution_id TEXT,
                    failure_code TEXT,
                    failure_class TEXT,
                    retry_disposition TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(work_order_id, attempt_number)
                );

                CREATE TABLE IF NOT EXISTS work_leases (
                    work_order_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE,
                    lease_token TEXT NOT NULL UNIQUE,
                    worker_id TEXT NOT NULL,
                    runtime_epoch INTEGER NOT NULL CHECK(runtime_epoch >= 0),
                    claimed_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE,
                    FOREIGN KEY(attempt_id) REFERENCES work_attempts(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS work_events (
                    id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    attempt_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_workspaces (
                    id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    attempt_id TEXT,
                    repository TEXT NOT NULL,
                    base_revision TEXT NOT NULL,
                    working_revision TEXT,
                    branch_ref TEXT,
                    review_ref TEXT,
                    state TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_work_attempts_order_number
                    ON work_attempts(work_order_id, attempt_number DESC);
                CREATE INDEX IF NOT EXISTS idx_work_attempts_status_started
                    ON work_attempts(status, started_at, id);
                CREATE INDEX IF NOT EXISTS idx_work_leases_expiry
                    ON work_leases(expires_at, work_order_id);
                CREATE INDEX IF NOT EXISTS idx_work_events_order_created
                    ON work_events(work_order_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_work_events_attempt_created
                    ON work_events(attempt_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_work_workspaces_order_state
                    ON work_workspaces(work_order_id, state, updated_at, id);
                """
            )
            connection.execute(
                "INSERT INTO work_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (3, "durable_work_attempts_leases_events_workspaces", _now()),
            )
    return WORK_DURABILITY_SCHEMA_VERSION
