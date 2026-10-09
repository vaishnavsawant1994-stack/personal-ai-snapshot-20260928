from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

IDENTITY_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_identity_schema(connection: sqlite3.Connection) -> int:
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM identity_schema_migrations")
        }
        if 1 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity_self_versions (
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS identity_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS software_body_revisions (
                    revision_id TEXT PRIMARY KEY,
                    git_revision TEXT NOT NULL,
                    body_version INTEGER NOT NULL,
                    work_contract_version INTEGER,
                    evidence_contract_version INTEGER,
                    evolution_contract_version INTEGER,
                    continuity_contract_version INTEGER,
                    extension_contract_version INTEGER,
                    manifest_hash TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    superseded_at TEXT
                );

                CREATE TABLE IF NOT EXISTS identity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_identity_self_hash
                    ON identity_self_versions(payload_hash, version);
                CREATE INDEX IF NOT EXISTS idx_body_revision_status_created
                    ON software_body_revisions(status, created_at, revision_id);
                CREATE INDEX IF NOT EXISTS idx_identity_events_type_created
                    ON identity_events(event_type, created_at, id);
                """
            )
            connection.execute(
                "INSERT INTO identity_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (1, "persistent_body_and_private_self_foundation", _now()),
            )
    return IDENTITY_SCHEMA_VERSION
