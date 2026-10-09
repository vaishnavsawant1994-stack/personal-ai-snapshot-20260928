from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


EVOLUTION_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_evolution_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS evolution_schema_migrations(
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evolution_candidates(
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            candidate_hash TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evolution_candidate_evidence(
            candidate_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            PRIMARY KEY(candidate_id, evidence_id),
            FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE CASCADE,
            FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS evolution_decisions(
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_evolution_candidates_status
            ON evolution_candidates(status, updated_at, id);
        CREATE INDEX IF NOT EXISTS idx_evolution_candidate_evidence_evidence
            ON evolution_candidate_evidence(evidence_id, candidate_id);
        CREATE INDEX IF NOT EXISTS idx_evolution_decisions_candidate
            ON evolution_decisions(candidate_id, created_at, id);
        """
    )
    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO evolution_schema_migrations(version, applied_at) VALUES (?, ?)",
            (EVOLUTION_SCHEMA_VERSION, _now()),
        )
