from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from .deduplication import evidence_fingerprint
from .models import Evidence, EvidenceProvenance, VerificationState
from .redaction import redact_text
from .store import EvidenceStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class EvidenceStatus(StrEnum):
    ACTIVE = "active"
    LINKED = "linked"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class EvidenceSourceType(StrEnum):
    USER_FEEDBACK = "user_feedback"
    USER_CORRECTION = "user_correction"
    WORK_EXPERIENCE = "work_experience"
    TOOL_FAILURE = "tool_failure"
    VERIFICATION_FAILURE = "verification_failure"
    RECOVERY_EVENT = "recovery_event"
    SECURITY_EVENT = "security_event"
    REPEATED_INTERVENTION = "repeated_intervention"
    WORKFLOW_FRICTION = "workflow_friction"
    SKILL_ASSESSMENT = "skill_assessment"
    PERFORMANCE_REGRESSION = "performance_regression"


@dataclass(frozen=True)
class IngestionRecord:
    source_type: EvidenceSourceType | str
    source: str
    subject: str
    observation: str
    project_id: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    work_order_id: str | None = None
    worker_run_id: str | None = None
    tool_name: str | None = None
    artifact_ref: str | None = None
    artifact_hash: str | None = None
    provenance: EvidenceProvenance = EvidenceProvenance.OBSERVED
    verification_state: VerificationState = VerificationState.UNVERIFIED
    verification_reason: str | None = None
    confidence: float = 0.7
    data_classification: str = "internal"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EvidenceIngestor:
    """Lossless, redacting, idempotent ingestion into the canonical Evidence store."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        self.connection = store.connection

    @staticmethod
    def _source_value(source_type: EvidenceSourceType | str) -> str:
        value = source_type.value if isinstance(source_type, EvidenceSourceType) else str(source_type)
        value = value.strip().lower()
        if not value:
            raise ValueError("source_type is required")
        return value

    def start_run(
        self,
        source_type: EvidenceSourceType | str,
        *,
        partition_key: str = "default",
        input_payload: Any = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        source_value = self._source_value(source_type)
        partition = str(partition_key or "default").strip() or "default"
        # Hash only a redacted representation so durable metadata is not a
        # dictionary oracle for credentials that should never enter this layer.
        safe_input = redact_text(_json(input_payload))
        run_id = f"eing_{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evidence_ingestion_runs(
                    id, source_type, partition_key, input_hash, status,
                    provider, model, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (run_id, source_value, partition, _hash(safe_input), provider, model, _now()),
            )
        return run_id

    def complete_run(
        self,
        run_id: str,
        *,
        cursor: Mapping[str, Any],
        output_payload: Any = None,
    ) -> None:
        now = _now()
        row = self.connection.execute(
            "SELECT source_type, partition_key, status FROM evidence_ingestion_runs WHERE id = ?",
            (str(run_id),),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        if str(row["status"]) != "running":
            raise ValueError("ingestion run is not running")
        safe_output = redact_text(_json(output_payload))
        with self.connection:
            self.connection.execute(
                """
                UPDATE evidence_ingestion_runs
                SET status = 'completed', output_hash = ?, completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (_hash(safe_output), now, str(run_id)),
            )
            self.connection.execute(
                """
                INSERT INTO evidence_ingestion_cursors(
                    source_type, partition_key, cursor_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_type, partition_key) DO UPDATE SET
                    cursor_json = excluded.cursor_json,
                    updated_at = excluded.updated_at
                """,
                (str(row["source_type"]), str(row["partition_key"]), _json(dict(cursor)), now),
            )

    def fail_run(self, run_id: str, *, error_code: str) -> None:
        code = str(error_code or "unknown_error").strip()[:160]
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE evidence_ingestion_runs
                SET status = 'failed', error_code = ?, completed_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (code, _now(), str(run_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("ingestion run is missing or not running")
        # Deliberately no cursor advancement on failure.

    def cursor(
        self,
        source_type: EvidenceSourceType | str,
        *,
        partition_key: str = "default",
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT cursor_json
            FROM evidence_ingestion_cursors
            WHERE source_type = ? AND partition_key = ?
            """,
            (self._source_value(source_type), str(partition_key or "default")),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def ingest(self, record: IngestionRecord, *, actor: str = "system") -> Evidence:
        source_type = self._source_value(record.source_type)
        safe_source = redact_text(record.source)
        safe_subject = redact_text(record.subject)
        safe_observation = redact_text(record.observation)
        safe_reason = None if record.verification_reason is None else redact_text(record.verification_reason)
        safe_metadata = {
            str(key): redact_text(value) if isinstance(value, str) else value
            for key, value in dict(record.metadata).items()
        }
        fingerprint = evidence_fingerprint(
            source_type=source_type,
            source=safe_source,
            subject=safe_subject,
            observation=safe_observation,
            project_id=record.project_id,
            work_order_id=record.work_order_id,
            metadata=safe_metadata,
        )
        existing = self.connection.execute(
            "SELECT evidence_id FROM evidence_fingerprints WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            item = self.store.get_evidence(str(existing[0]))
            if item is None:
                raise RuntimeError("evidence fingerprint points to missing evidence")
            return item

        evidence = Evidence(
            id=f"ev-ing-{fingerprint[:32]}",
            source_type=source_type,
            source=safe_source,
            subject=safe_subject,
            observation=safe_observation,
            provenance=record.provenance,
            project_id=record.project_id,
            goal_id=record.goal_id,
            plan_id=record.plan_id,
            work_order_id=record.work_order_id,
            worker_run_id=record.worker_run_id,
            tool_name=record.tool_name,
            artifact_ref=record.artifact_ref,
            artifact_hash=record.artifact_hash,
            verification_state=record.verification_state,
            verification_reason=safe_reason,
            confidence=record.confidence,
            data_classification=record.data_classification,
        )
        try:
            self.store.record_evidence(evidence)
        except sqlite3.IntegrityError:
            persisted = self.store.get_evidence(evidence.id)
            if persisted is None:
                raise
            evidence = persisted
        now = _now()
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO evidence_fingerprints(fingerprint, evidence_id, created_at) VALUES (?, ?, ?)",
                    (fingerprint, evidence.id, now),
                )
                self.connection.execute(
                    """
                    INSERT INTO evidence_lifecycle(
                        evidence_id, status, reason, superseded_by_id, updated_at, updated_by
                    ) VALUES (?, 'active', NULL, NULL, ?, ?)
                    ON CONFLICT(evidence_id) DO NOTHING
                    """,
                    (evidence.id, now, str(actor or "system")),
                )
        except sqlite3.IntegrityError:
            duplicate = self.connection.execute(
                "SELECT evidence_id FROM evidence_fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if duplicate is not None:
                existing_item = self.store.get_evidence(str(duplicate[0]))
                if existing_item is not None:
                    return existing_item
            raise
        return evidence

    def lifecycle(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM evidence_lifecycle WHERE evidence_id = ?",
            (str(evidence_id),),
        ).fetchone()
        return dict(row) if row else None

    def set_lifecycle(
        self,
        evidence_id: str,
        status: EvidenceStatus,
        *,
        actor: str,
        reason: str | None = None,
        superseded_by_id: str | None = None,
    ) -> None:
        if self.store.get_evidence(str(evidence_id)) is None:
            raise KeyError(evidence_id)
        if status is EvidenceStatus.SUPERSEDED and not superseded_by_id:
            raise ValueError("superseded evidence requires superseded_by_id")
        if superseded_by_id is not None and self.store.get_evidence(str(superseded_by_id)) is None:
            raise KeyError(superseded_by_id)
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evidence_lifecycle(
                    evidence_id, status, reason, superseded_by_id, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    superseded_by_id = excluded.superseded_by_id,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (
                    str(evidence_id),
                    status.value,
                    None if reason is None else redact_text(reason)[:1000],
                    superseded_by_id,
                    now,
                    str(actor or "system"),
                ),
            )

    def list_active(self, *, source_type: EvidenceSourceType | str | None = None) -> list[Evidence]:
        params: list[Any] = [EvidenceStatus.ACTIVE.value]
        sql = """
            SELECT e.payload_json
            FROM evidence AS e
            JOIN evidence_lifecycle AS lifecycle ON lifecycle.evidence_id = e.id
            WHERE lifecycle.status = ?
        """
        if source_type is not None:
            sql += " AND e.source_type = ?"
            params.append(self._source_value(source_type))
        sql += " ORDER BY e.created_at, e.id"
        return [Evidence.from_dict(json.loads(row[0])) for row in self.connection.execute(sql, tuple(params))]

    def record_receipt_context(
        self,
        receipt_id: str,
        *,
        work_order_id: str | None = None,
        attempt_id: str | None = None,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
        verification_method: str | None = None,
        verified_at: str | None = None,
    ) -> None:
        if self.store.get_receipt(str(receipt_id)) is None:
            raise KeyError(receipt_id)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO receipt_context(
                    receipt_id, work_order_id, attempt_id, approval_id,
                    idempotency_key, verification_method, verified_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(receipt_id) DO UPDATE SET
                    work_order_id = COALESCE(excluded.work_order_id, receipt_context.work_order_id),
                    attempt_id = COALESCE(excluded.attempt_id, receipt_context.attempt_id),
                    approval_id = COALESCE(excluded.approval_id, receipt_context.approval_id),
                    idempotency_key = COALESCE(excluded.idempotency_key, receipt_context.idempotency_key),
                    verification_method = COALESCE(excluded.verification_method, receipt_context.verification_method),
                    verified_at = COALESCE(excluded.verified_at, receipt_context.verified_at)
                """,
                (
                    str(receipt_id), work_order_id, attempt_id, approval_id,
                    idempotency_key, verification_method, verified_at, _now(),
                ),
            )
