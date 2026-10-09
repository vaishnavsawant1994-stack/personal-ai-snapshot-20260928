from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

EVIDENCE_SCHEMA_VERSION = 3


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
            applied.add(1)

        if 2 not in applied:
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_evidence_work_order_state_created
                    ON evidence(work_order_id, verification_state, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_claims_work_order_state_updated
                    ON claims(work_order_id, state, updated_at DESC, id);
                CREATE INDEX IF NOT EXISTS idx_receipts_execution_verified_created
                    ON receipts(execution_id, verified, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_claim_evidence_evidence
                    ON claim_evidence(evidence_id, claim_id);
                CREATE INDEX IF NOT EXISTS idx_retests_work_order_status_created
                    ON retests(work_order_id, status, created_at, id);
                """
            )
            connection.execute(
                "INSERT INTO evidence_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (2, "indexed_work_evidence_read_paths", _now()),
            )
            applied.add(2)

        if 3 not in applied:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_lifecycle (
                    evidence_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','linked','resolved','dismissed','superseded')),
                    reason TEXT,
                    superseded_by_id TEXT,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE,
                    FOREIGN KEY(superseded_by_id) REFERENCES evidence(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evidence_ingestion_cursors (
                    source_type TEXT NOT NULL,
                    partition_key TEXT NOT NULL,
                    cursor_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_type, partition_key)
                );

                CREATE TABLE IF NOT EXISTS evidence_ingestion_runs (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    partition_key TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('running','completed','failed')),
                    provider TEXT,
                    model TEXT,
                    output_hash TEXT,
                    error_code TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS receipt_context (
                    receipt_id TEXT PRIMARY KEY,
                    work_order_id TEXT,
                    attempt_id TEXT,
                    approval_id TEXT,
                    idempotency_key TEXT,
                    verification_method TEXT,
                    verified_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_receipt_context_idempotency
                    ON receipt_context(idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_evidence_lifecycle_status
                    ON evidence_lifecycle(status, updated_at, evidence_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_ingestion_runs_source_started
                    ON evidence_ingestion_runs(source_type, partition_key, started_at, id);
                CREATE INDEX IF NOT EXISTS idx_receipt_context_work_attempt
                    ON receipt_context(work_order_id, attempt_id, created_at);
                """
            )
            connection.execute(
                "INSERT INTO evidence_schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (3, "evidence_ingestion_lifecycle_and_receipt_context", _now()),
            )
    return EVIDENCE_SCHEMA_VERSION
