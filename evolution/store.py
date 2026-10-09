from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from evidence.store import EvidenceStore

from .migrations import migrate_evolution_schema
from .models import CandidateStatus, EvolutionCandidate, EvolutionDecision, RiskLevel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class EvolutionStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if db_path is not None and connection is not None:
            raise ValueError("provide db_path or connection, not both")
        self._owns_connection = connection is None
        self.connection = connection or sqlite3.connect(str(db_path or ":memory:"))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        EvidenceStore(connection=self.connection)
        migrate_evolution_schema(self.connection)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "EvolutionStore":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def save_candidate(self, candidate: EvolutionCandidate) -> EvolutionCandidate:
        for evidence_id in candidate.evidence_ids:
            row = self.connection.execute("SELECT 1 FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            if row is None:
                raise ValueError(f"candidate evidence does not exist: {evidence_id}")
        existing = self.connection.execute(
            "SELECT payload_json FROM evolution_candidates WHERE candidate_hash = ?",
            (candidate.candidate_hash,),
        ).fetchone()
        if existing is not None:
            return EvolutionCandidate.from_dict(json.loads(existing[0]))

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evolution_candidates(
                    id, status, risk_level, candidate_hash, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.status.value,
                    candidate.risk_level.value,
                    candidate.candidate_hash,
                    _json(candidate.to_dict()),
                    candidate.created_at,
                    candidate.updated_at,
                ),
            )
            for evidence_id in candidate.evidence_ids:
                self.connection.execute(
                    "INSERT INTO evolution_candidate_evidence(candidate_id, evidence_id) VALUES (?, ?)",
                    (candidate.id, evidence_id),
                )
        return candidate

    def get_candidate(self, candidate_id: str) -> EvolutionCandidate | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evolution_candidates WHERE id = ?",
            (str(candidate_id),),
        ).fetchone()
        return EvolutionCandidate.from_dict(json.loads(row[0])) if row else None

    def list_candidates(
        self,
        *,
        status: CandidateStatus | None = None,
        risk_level: RiskLevel | None = None,
    ) -> list[EvolutionCandidate]:
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if risk_level is not None:
            clauses.append("risk_level = ?")
            params.append(risk_level.value)
        sql = "SELECT payload_json FROM evolution_candidates"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, id"
        return [EvolutionCandidate.from_dict(json.loads(row[0])) for row in self.connection.execute(sql, tuple(params))]

    def update_candidate(
        self,
        candidate_id: str,
        *,
        status: CandidateStatus,
        risk_level: RiskLevel | None = None,
    ) -> EvolutionCandidate:
        current = self.get_candidate(candidate_id)
        if current is None:
            raise KeyError(candidate_id)
        updated = replace(
            current,
            status=status,
            risk_level=current.risk_level if risk_level is None else risk_level,
            updated_at=_now(),
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE evolution_candidates
                SET status = ?, risk_level = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (updated.status.value, updated.risk_level.value, _json(updated.to_dict()), updated.updated_at, updated.id),
            )
        return updated

    def record_decision(
        self,
        candidate_id: str,
        decision: EvolutionDecision,
        *,
        actor_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        if self.get_candidate(candidate_id) is None:
            raise KeyError(candidate_id)
        actor = str(actor_id or "").strip()
        explanation = str(reason or "").strip()
        if not actor or not explanation:
            raise ValueError("actor_id and reason are required")
        decision_id = f"evd-{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evolution_decisions(
                    id, candidate_id, decision, actor_id, reason, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (decision_id, candidate_id, decision.value, actor, explanation, _json(dict(payload or {})), _now()),
            )
        return decision_id

    def decisions_for(self, candidate_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, candidate_id, decision, actor_id, reason, payload_json, created_at
            FROM evolution_decisions
            WHERE candidate_id = ?
            ORDER BY created_at, id
            """,
            (str(candidate_id),),
        ).fetchall()
        return [dict(row) for row in rows]
