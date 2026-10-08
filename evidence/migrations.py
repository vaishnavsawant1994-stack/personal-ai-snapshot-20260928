from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

EVIDENCE_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_evidence_schema(connection: sqlite3.Connection) -> int:
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.execute("SELECT version FROM evidence_schema_migrations")
        }
        if 1 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    goal_id TEXT,
                    plan_id TEXT,
                    work_order_id TEXT,
                    source_type TEXT NOT NULL,
                    verification_state TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    verified INTEGER NOT NULL CHECK(verified IN (0, 1)),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    work_order_id TEXT,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claim_evidence (
                    claim_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    relationship TEXT NOT NULL DEFAULT 'supports',
                    PRIMARY KEY(claim_id, evidence_id),
                    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
                    FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS retests (
                    id TEXT PRIMARY KEY,
                    claim_id TEXT,
                    work_order_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_project_work_order
                    ON evidence(project_id, work_order_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_verification
                    ON evidence(verification_state, provenance);
                CREATE INDEX IF NOT EXISTS idx_receipts_execution
                    ON receipts(execution_id);
                CREATE INDEX IF NOT EXISTS idx_claims_project_state
                    ON claims(project_id, state);
                """
            )
            connection.execute(
                "INSERT INTO evidence_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (1, "initial_evidence_claim_foundation", _now()),
            )
    return EVIDENCE_SCHEMA_VERSION
