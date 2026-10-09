from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from future_intelligence.work_orchestration.models import WorkOrderStatus
from identity import BodyRevisionStatus, IdentityStore

from .code_body import CodeBodyEvolutionService, CodeBodyRunStatus
from .models import CandidateStatus, EvolutionDecision
from .store import EvolutionStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AdoptionRecord:
    id: str
    candidate_id: str
    code_body_run_id: str
    body_revision_id: str
    working_revision: str
    owner_decision_id: str
    status: str
    approved_at: str
    activated_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AdoptionRecord":
        return cls(**{key: row[key] for key in cls.__dataclass_fields__})


class OwnerBodyAdoptionService:
    """Separate authority boundary for accepting a reviewed software-body change.

    `approve()` records owner adoption authority but does not merge, deploy, or
    activate anything. `confirm_activation()` may activate only the exact already
    approved revision after an external release/runtime controller proves that
    exact revision is now running.
    """

    def __init__(
        self,
        *,
        evolution_store: EvolutionStore,
        code_body: CodeBodyEvolutionService,
        identity_store: IdentityStore,
        repository_provider,
    ) -> None:
        self.evolution_store = evolution_store
        self.code_body = code_body
        self.identity_store = identity_store
        self.repository_provider = repository_provider
        self.work_store = code_body.work_store
        self._migrate()

    def _migrate(self) -> None:
        with self.work_store.connection:
            self.work_store.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_adoptions(
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    code_body_run_id TEXT NOT NULL UNIQUE,
                    body_revision_id TEXT NOT NULL UNIQUE,
                    working_revision TEXT NOT NULL,
                    owner_decision_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    activated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_adoptions_status
                    ON evolution_adoptions(status, approved_at, id);
                """
            )

    def get(self, candidate_id: str) -> AdoptionRecord | None:
        row = self.work_store.connection.execute(
            "SELECT * FROM evolution_adoptions WHERE candidate_id = ?",
            (str(candidate_id),),
        ).fetchone()
        return AdoptionRecord.from_row(row) if row else None

    def approve(self, candidate_id: str, *, owner_id: str, reason: str) -> AdoptionRecord:
        if str(owner_id) != "owner":
            raise PermissionError("only the canonical owner may approve Body adoption")
        existing = self.get(candidate_id)
        if existing is not None:
            return existing
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("adoption reason is required")
        candidate = self.evolution_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate.status is not CandidateStatus.HANDED_OFF:
            raise ValueError("candidate must be handed off before adoption approval")
        run = self.code_body.latest(candidate_id)
        if run is None or run.status is not CodeBodyRunStatus.REVIEW_READY:
            raise ValueError("verified implementation and approved code review are required")
        if not run.body_revision_id or not run.working_revision or not run.review_ref:
            raise ValueError("review-ready code run is incomplete")
        order = self.work_store.get_order(run.work_order_id)
        if order is None or order.status is not WorkOrderStatus.COMPLETED:
            raise ValueError("implementation Work must be verified-completed before adoption")
        body = self.identity_store.get_body_revision(run.body_revision_id)
        if body is None:
            raise ValueError("candidate Body revision is not registered")
        if str(body["git_revision"]) != run.working_revision:
            raise ValueError("Body revision does not match reviewed implementation revision")
        if str(body["status"]) == BodyRevisionStatus.REJECTED.value:
            raise ValueError("rejected Body revision cannot be adopted")

        decision_id = f"owner-adopt-{_digest(candidate.id, run.working_revision)[:24]}"
        self.evolution_store.record_decision(
            candidate.id,
            EvolutionDecision.ADOPT,
            actor_id="owner",
            reason=explanation,
            payload={
                "owner_adoption": True,
                "body_revision_id": run.body_revision_id,
                "working_revision": run.working_revision,
                "review_ref": run.review_ref,
                "activation": "requires_exact_running_revision_confirmation",
            },
            decision_id=decision_id,
        )
        stamp = _now()
        record = AdoptionRecord(
            id=f"adopt-{_digest(candidate.id, run.body_revision_id)[:24]}",
            candidate_id=candidate.id,
            code_body_run_id=run.id,
            body_revision_id=run.body_revision_id,
            working_revision=run.working_revision,
            owner_decision_id=decision_id,
            status="approved",
            approved_at=stamp,
        )
        with self.work_store.connection:
            self.work_store.connection.execute(
                """
                INSERT INTO evolution_adoptions(
                    id, candidate_id, code_body_run_id, body_revision_id,
                    working_revision, owner_decision_id, status, approved_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, NULL)
                """,
                (
                    record.id,
                    record.candidate_id,
                    record.code_body_run_id,
                    record.body_revision_id,
                    record.working_revision,
                    record.owner_decision_id,
                    record.approved_at,
                ),
            )
        self.evolution_store.update_candidate(candidate.id, status=CandidateStatus.ADOPTION_APPROVED)
        self.work_store.append_work_event(
            run.work_order_id,
            "evolution.body_adoption.approved",
            {
                "body_revision_id": run.body_revision_id,
                "working_revision": run.working_revision,
                "owner_decision_id": decision_id,
                "activation_required": True,
            },
            attempt_id=run.attempt_id,
        )
        return self.get(candidate.id) or record

    def confirm_activation(
        self,
        candidate_id: str,
        *,
        running_revision: str,
        actor: str = "release_controller",
    ) -> AdoptionRecord:
        record = self.get(candidate_id)
        if record is None:
            raise ValueError("owner adoption approval is required before activation")
        if record.status == "activated":
            return record
        resolved = self.repository_provider.resolve_revision(running_revision)
        if resolved != record.working_revision:
            raise ValueError("running revision is not the owner-approved reviewed revision")
        body = self.identity_store.get_body_revision(record.body_revision_id)
        if body is None or str(body["git_revision"]) != resolved:
            raise ValueError("registered Body revision does not match running revision")
        self.identity_store.activate_body_revision(record.body_revision_id, actor=str(actor or "release_controller"))
        stamp = _now()
        with self.work_store.connection:
            self.work_store.connection.execute(
                """
                UPDATE evolution_adoptions
                SET status = 'activated', activated_at = ?
                WHERE id = ? AND status = 'approved'
                """,
                (stamp, record.id),
            )
            self.work_store.connection.execute(
                """
                UPDATE evolution_code_body_runs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (CodeBodyRunStatus.ADOPTED.value, stamp, record.code_body_run_id),
            )
        self.evolution_store.update_candidate(candidate_id, status=CandidateStatus.ADOPTED)
        run = self.code_body.get(record.code_body_run_id)
        if run is not None:
            self.work_store.append_work_event(
                run.work_order_id,
                "evolution.body_revision.activated",
                {
                    "body_revision_id": record.body_revision_id,
                    "running_revision": resolved,
                    "owner_decision_id": record.owner_decision_id,
                    "actor": str(actor or "release_controller"),
                },
                attempt_id=run.attempt_id,
            )
        return self.get(candidate_id) or record
