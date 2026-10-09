from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .migrations import migrate_evolution_schema
from .models import CandidateStatus, EvolutionCandidate, RiskLevel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
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
        migrate_evolution_schema(self.connection)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "EvolutionStore":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def save_candidate(self, candidate: EvolutionCandidate) -> EvolutionCandidate:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evolution_candidates(
                    id, status, title, risk_level, candidate_hash,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.status.value,
                    candidate.title,
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

    def find_by_hash(self, candidate_hash: str) -> EvolutionCandidate | None:
        row = self.connection.execute(
            "SELECT payload_json FROM evolution_candidates WHERE candidate_hash = ?",
            (str(candidate_hash),),
        ).fetchone()
        return EvolutionCandidate.from_dict(json.loads(row[0])) if row else None

    def list_candidates(self, *, status: CandidateStatus | None = None) -> list[EvolutionCandidate]:
        if status is None:
            rows = self.connection.execute(
                "SELECT payload_json FROM evolution_candidates ORDER BY created_at, id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT payload_json FROM evolution_candidates
                WHERE status = ? ORDER BY created_at, id
                """,
                (status.value,),
            ).fetchall()
        return [EvolutionCandidate.from_dict(json.loads(row[0])) for row in rows]

    def update_candidate(
        self,
        candidate_id: str,
        *,
        status: CandidateStatus,
        risk_level: RiskLevel | None = None,
    ) -> EvolutionCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        updated = EvolutionCandidate(
            id=candidate.id,
            status=status,
            title=candidate.title,
            rationale=candidate.rationale,
            proposed_change=candidate.proposed_change,
            expected_benefit=candidate.expected_benefit,
            risk_level=risk_level or candidate.risk_level,
            affected_scope=candidate.affected_scope,
            test_plan=candidate.test_plan,
            evidence_ids=candidate.evidence_ids,
            candidate_hash=candidate.candidate_hash,
            metadata=candidate.metadata,
            created_at=candidate.created_at,
            updated_at=_now(),
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE evolution_candidates
                SET status = ?, risk_level = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.status.value,
                    updated.risk_level.value,
                    _json(updated.to_dict()),
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated

    def record_review(
        self,
        candidate_id: str,
        *,
        reviewer_type: str,
        status: CandidateStatus,
        risk_level: RiskLevel,
        reasons: tuple[str, ...],
    ) -> str:
        if self.get_candidate(candidate_id) is None:
            raise KeyError(candidate_id)
        review_id = f"erev_{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evolution_reviews(
                    id, candidate_id, reviewer_type, status, risk_level,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    candidate_id,
                    str(reviewer_type),
                    status.value,
                    risk_level.value,
                    _json({"reasons": list(reasons)}),
                    _now(),
                ),
            )
        return review_id

    def record_decision(
        self,
        candidate_id: str,
        *,
        decision: CandidateStatus,
        actor_id: str,
        reason: str,
    ) -> str:
        if self.get_candidate(candidate_id) is None:
            raise KeyError(candidate_id)
        decision_id = f"edec_{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO evolution_decisions(
                    id, candidate_id, decision, actor_id, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    candidate_id,
                    decision.value,
                    str(actor_id),
                    str(reason),
                    _now(),
                ),
            )
        return decision_id

    def status_counts(self) -> dict[str, int]:
        return {
            str(row["status"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS count FROM evolution_candidates GROUP BY status"
            )
        }
