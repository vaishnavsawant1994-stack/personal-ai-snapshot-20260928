from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


AGENT_CONTINUITY_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_agent_continuity_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_continuity_schema_migrations(
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS continuation_authority(
            slot INTEGER PRIMARY KEY CHECK(slot = 1),
            epoch INTEGER NOT NULL,
            host_id TEXT NOT NULL,
            token_hash TEXT,
            checkpoint_id TEXT,
            status TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            fenced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS continuity_checkpoints(
            id TEXT PRIMARY KEY,
            source_host_id TEXT NOT NULL,
            authority_epoch INTEGER NOT NULL,
            checkpoint_hash TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS continuity_transfer_grants(
            id TEXT PRIMARY KEY,
            checkpoint_id TEXT NOT NULL,
            source_host_id TEXT NOT NULL,
            target_host_id TEXT NOT NULL,
            source_epoch INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            UNIQUE(checkpoint_id, target_host_id),
            FOREIGN KEY(checkpoint_id) REFERENCES continuity_checkpoints(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS continuity_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            host_id TEXT,
            checkpoint_id TEXT,
            epoch INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_continuity_checkpoints_created
            ON continuity_checkpoints(created_at, id);
        CREATE INDEX IF NOT EXISTS idx_continuity_transfer_status
            ON continuity_transfer_grants(status, expires_at, id);
        CREATE INDEX IF NOT EXISTS idx_continuity_events_created
            ON continuity_events(created_at, id);
        """
    )
    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO agent_continuity_schema_migrations(version, applied_at) VALUES (?, ?)",
            (AGENT_CONTINUITY_SCHEMA_VERSION, _now()),
        )
