from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

EVOLUTION_SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_evolution_schema(connection: sqlite3.Connection) -> int:
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM evolution_schema_migrations")
        }
        if 1 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_candidates (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evolution_candidate_evidence (
                    candidate_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    PRIMARY KEY(candidate_id, evidence_id),
                    FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evolution_reviews (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    reviewer_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evolution_decisions (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_evolution_candidates_status_risk
                    ON evolution_candidates(status, risk_level, updated_at, id);
                CREATE INDEX IF NOT EXISTS idx_evolution_candidate_evidence_evidence
                    ON evolution_candidate_evidence(evidence_id, candidate_id);
                CREATE INDEX IF NOT EXISTS idx_evolution_reviews_candidate_created
                    ON evolution_reviews(candidate_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_evolution_decisions_candidate_created
                    ON evolution_decisions(candidate_id, created_at, id);
                """
            )
            connection.execute(
                "INSERT INTO evolution_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (1, "read_only_candidate_curation_foundation", _now()),
            )
            applied.add(1)

        if 2 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_handoffs (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    work_order_id TEXT NOT NULL UNIQUE,
                    goal_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    base_body_revision TEXT NOT NULL,
                    approved_decision_id TEXT NOT NULL UNIQUE,
                    handoff_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES evolution_candidates(id) ON DELETE RESTRICT,
                    FOREIGN KEY(approved_decision_id) REFERENCES evolution_decisions(id) ON DELETE RESTRICT
                );

                CREATE TRIGGER IF NOT EXISTS evolution_handoffs_immutable_update
                BEFORE UPDATE ON evolution_handoffs
                BEGIN
                    SELECT RAISE(ABORT, 'evolution handoffs are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS evolution_handoffs_immutable_delete
                BEFORE DELETE ON evolution_handoffs
                BEGIN
                    SELECT RAISE(ABORT, 'evolution handoffs are immutable');
                END;

                CREATE INDEX IF NOT EXISTS idx_evolution_handoffs_created
                    ON evolution_handoffs(created_at, id);
                """
            )
            connection.execute(
                "INSERT INTO evolution_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (2, "owner_approved_immutable_work_handoffs", _now()),
            )
    return EVOLUTION_SCHEMA_VERSION
