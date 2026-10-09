from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .migrations import migrate_evidence_schema
from .models import Claim, ClaimState, Evidence, Receipt, VerificationState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


class EvidenceStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if connection is not None and db_path is not None:
            raise ValueError("provide db_path or connection, not both")
        self._owns_connection = connection is None
        self.connection = connection or sqlite3.connect(str(db_path or ":memory:"))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        migrate_evidence_schema(self.connection)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def record_evidence(self, evidence: Evidence) -> Evidence:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evidence(
                    id, project_id, goal_id, plan_id, work_order_id,
                    source_type, verification_state, provenance, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.project_id,
                    evidence.goal_id,
                    evidence.plan_id,
                    evidence.work_order_id,
                    evidence.source_type,
                    evidence.verification_state.value,
                    evidence.provenance.value,
                    _json(evidence.to_dict()),
                    evidence.created_at,
                ),
            )
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        return Evidence.from_dict(json.loads(row[0])) if row else None

    def list_evidence(
        self,
        *,
        project_id: str | None = None,
        work_order_id: str | None = None,
        verification_state: VerificationState | None = None,
    ) -> list[Evidence]:
        clauses: list[str] = []
        params: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if work_order_id is not None:
            clauses.append("work_order_id = ?")
            params.append(work_order_id)
        if verification_state is not None:
            clauses.append("verification_state = ?")
            params.append(verification_state.value)
        sql = "SELECT payload_json FROM evidence"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, id"
        return [
            Evidence.from_dict(json.loads(row[0]))
            for row in self.connection.execute(sql, tuple(params)).fetchall()
        ]

    def record_receipt(self, receipt: Receipt) -> Receipt:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO receipts(
                    id, execution_id, operation, tool, destination,
                    verified, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.id,
                    receipt.execution_id,
                    receipt.operation,
                    receipt.tool,
                    receipt.destination,
                    int(receipt.verified),
                    _json(receipt.to_dict()),
                    receipt.created_at,
                ),
            )
        return receipt

    def get_receipt(self, receipt_id: str) -> Receipt | None:
        row = self.connection.execute(
            "SELECT payload_json FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return Receipt.from_dict(json.loads(row[0])) if row else None

    def list_receipts(
        self,
        *,
        execution_id: str | None = None,
        tool: str | None = None,
        verified: bool | None = None,
    ) -> list[Receipt]:
        clauses: list[str] = []
        params: list[object] = []
        if execution_id is not None:
            clauses.append("execution_id = ?")
            params.append(execution_id)
        if tool is not None:
            clauses.append("tool = ?")
            params.append(tool)
        if verified is not None:
            clauses.append("verified = ?")
            params.append(int(verified))
        sql = "SELECT payload_json FROM receipts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, id"
        return [
            Receipt.from_dict(json.loads(row[0]))
            for row in self.connection.execute(sql, tuple(params)).fetchall()
        ]

    def create_claim(self, claim: Claim) -> Claim:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO claims(
                    id, project_id, work_order_id, state,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.id,
                    claim.project_id,
                    claim.work_order_id,
                    claim.state.value,
                    _json(claim.to_dict()),
                    claim.created_at,
                    claim.updated_at,
                ),
            )
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self.connection.execute(
            "SELECT payload_json FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        return Claim.from_dict(json.loads(row[0])) if row else None

    def update_claim_state(
        self,
        claim_id: str,
        state: ClaimState,
        *,
        confidence: float | None = None,
    ) -> Claim:
        claim = self.get_claim(claim_id)
        if claim is None:
            raise KeyError(claim_id)
        updated = Claim(
            id=claim.id,
            project_id=claim.project_id,
            work_order_id=claim.work_order_id,
            text=claim.text,
            state=state,
            confidence=claim.confidence if confidence is None else confidence,
            created_at=claim.created_at,
            updated_at=_now(),
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE claims
                SET state = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (state.value, _json(updated.to_dict()), updated.updated_at, claim_id),
            )
        return updated

    def link_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        *,
        relationship: str = "supports",
    ) -> None:
        if not relationship.strip():
            raise ValueError("relationship is required")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO claim_evidence(claim_id, evidence_id, relationship)
                VALUES (?, ?, ?)
                """,
                (claim_id, evidence_id, relationship),
            )

    def evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        rows = self.connection.execute(
            """
            SELECT e.payload_json
            FROM evidence AS e
            JOIN claim_evidence AS ce ON ce.evidence_id = e.id
            WHERE ce.claim_id = ?
            ORDER BY e.created_at, e.id
            """,
            (claim_id,),
        ).fetchall()
        return [Evidence.from_dict(json.loads(row[0])) for row in rows]
