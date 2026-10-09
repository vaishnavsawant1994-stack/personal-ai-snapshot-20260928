from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable

from evidence import Evidence, EvidenceProvenance, EvidenceStore, VerificationState
from future_intelligence.work_orchestration.attempts import WorkAttemptStatus
from future_intelligence.work_orchestration.failure_policy import FailureClass, WorkFailure
from future_intelligence.work_orchestration.repository import (
    RepositoryWorkspaceProvider,
    RepositoryWorkspaceSession,
)
from future_intelligence.work_orchestration.workspace import WorkWorkspace, WorkspaceState
from identity import BodyManifest, BodyRevisionStatus, IdentityStore

from .handoff import EvolutionHandoffService
from .review import ReviewVerifier
from .verification import VerificationProvider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class CodeBodyRunStatus(StrEnum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    VERIFIED = "verified"
    REVIEW_READY = "review_ready"
    FAILED = "failed"
    ADOPTED = "adopted"


@dataclass(frozen=True)
class CodeBodyRun:
    id: str
    candidate_id: str
    handoff_id: str
    work_order_id: str
    attempt_id: str
    workspace_id: str
    repository: str
    base_revision: str
    branch_ref: str
    status: CodeBodyRunStatus
    working_revision: str | None = None
    verification_hash: str | None = None
    verification_evidence_id: str | None = None
    review_ref: str | None = None
    review_evidence_id: str | None = None
    reviewer: str | None = None
    body_revision_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CodeBodyRun":
        return cls(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            handoff_id=str(row["handoff_id"]),
            work_order_id=str(row["work_order_id"]),
            attempt_id=str(row["attempt_id"]),
            workspace_id=str(row["workspace_id"]),
            repository=str(row["repository"]),
            base_revision=str(row["base_revision"]),
            branch_ref=str(row["branch_ref"]),
            status=CodeBodyRunStatus(str(row["status"])),
            working_revision=row["working_revision"],
            verification_hash=row["verification_hash"],
            verification_evidence_id=row["verification_evidence_id"],
            review_ref=row["review_ref"],
            review_evidence_id=row["review_evidence_id"],
            reviewer=row["reviewer"],
            body_revision_id=row["body_revision_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "handoff_id": self.handoff_id,
            "work_order_id": self.work_order_id,
            "attempt_id": self.attempt_id,
            "workspace_id": self.workspace_id,
            "repository": self.repository,
            "base_revision": self.base_revision,
            "branch_ref": self.branch_ref,
            "status": self.status.value,
            "working_revision": self.working_revision,
            "verification_hash": self.verification_hash,
            "verification_evidence_id": self.verification_evidence_id,
            "review_ref": self.review_ref,
            "review_evidence_id": self.review_evidence_id,
            "reviewer": self.reviewer,
            "body_revision_id": self.body_revision_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class CodeBodyEvolutionService:
    """Governed implementation lifecycle after an owner-approved E6 handoff.

    This service prepares/records local implementation work, runs only a supplied
    verification provider, verifies an externally created code-review reference,
    and records a *candidate* Body revision. It has no push, merge, deploy, or
    Body-activation operation. E8 may additionally bind all mutating lifecycle
    methods to the currently active continuation-authority host.
    """

    def __init__(
        self,
        *,
        handoffs: EvolutionHandoffService,
        work_store,
        evidence_store: EvidenceStore,
        identity_store: IdentityStore,
        repository_provider: RepositoryWorkspaceProvider,
        verification_provider: VerificationProvider | None = None,
        review_verifier: ReviewVerifier | None = None,
        body_manifest_path: str = "config/vishnu-body.yaml",
        continuation_authority_guard: Callable[[], object] | None = None,
    ) -> None:
        self.handoffs = handoffs
        self.work_store = work_store
        self.evidence_store = evidence_store
        self.identity_store = identity_store
        self.repository_provider = repository_provider
        self.verification_provider = verification_provider
        self.review_verifier = review_verifier
        self.body_manifest_path = str(body_manifest_path)
        self._continuation_authority_guard = continuation_authority_guard
        self._migrate()

    def attach_continuation_authority(self, guard: Callable[[], object] | None) -> None:
        self._continuation_authority_guard = guard

    def _assert_continuation_authority(self) -> None:
        if self._continuation_authority_guard is not None:
            self._continuation_authority_guard()

    def _migrate(self) -> None:
        with self.work_store.connection:
            self.work_store.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_code_body_runs(
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    work_order_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE,
                    workspace_id TEXT NOT NULL UNIQUE,
                    repository TEXT NOT NULL,
                    base_revision TEXT NOT NULL,
                    branch_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    working_revision TEXT,
                    verification_hash TEXT,
                    verification_evidence_id TEXT,
                    review_ref TEXT,
                    review_evidence_id TEXT,
                    reviewer TEXT,
                    body_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_code_body_candidate
                    ON evolution_code_body_runs(candidate_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_evolution_code_body_status
                    ON evolution_code_body_runs(status, updated_at, id);
                """
            )

    def latest(self, candidate_id: str) -> CodeBodyRun | None:
        row = self.work_store.connection.execute(
            """
            SELECT * FROM evolution_code_body_runs
            WHERE candidate_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (str(candidate_id),),
        ).fetchone()
        return CodeBodyRun.from_row(row) if row else None

    def get(self, run_id: str) -> CodeBodyRun | None:
        row = self.work_store.connection.execute(
            "SELECT * FROM evolution_code_body_runs WHERE id = ?",
            (str(run_id),),
        ).fetchone()
        return CodeBodyRun.from_row(row) if row else None

    def prepare(
        self,
        candidate_id: str,
        *,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 900,
    ) -> CodeBodyRun:
        self._assert_continuation_authority()
        handoff = self.handoffs.get(candidate_id)
        if handoff is None:
            raise ValueError("candidate has no owner-approved handoff")
        existing = self.latest(candidate_id)
        if existing is not None and existing.status not in {CodeBodyRunStatus.FAILED}:
            return existing
        candidate = self.handoffs.evolution_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        order = self.work_store.get_order(handoff.work_order_id)
        if order is None:
            raise RuntimeError("handoff WorkOrder is unavailable")
        claim = self.work_store.claim_work_order(
            handoff.work_order_id,
            worker_id=str(worker_id),
            runtime_epoch=int(runtime_epoch),
            lease_seconds=int(lease_seconds),
            execution_id=f"evolution-code:{candidate_id}",
        )
        if claim is None:
            raise RuntimeError("evolution WorkOrder is not claimable")
        branch = f"vishnu/evolution/{candidate.id[:36]}-{candidate.candidate_hash[:8]}-a{claim.attempt.attempt_number}"
        try:
            session = self.repository_provider.prepare(
                repository=self.repository_provider.repository,
                work_order_id=handoff.work_order_id,
                attempt_id=claim.attempt.id,
                base_revision=handoff.base_body_revision,
                branch_ref=branch,
            )
        except Exception as exc:
            self.work_store.finish_attempt(
                claim.attempt.id,
                lease_token=claim.lease.lease_token,
                status=WorkAttemptStatus.FAILED,
                failure=WorkFailure(
                    failure_class=FailureClass.VALIDATION,
                    code="repository_workspace_prepare_failed",
                    message=type(exc).__name__,
                ),
                max_attempts=1,
            )
            raise
        workspace_id = f"ws-evo-{candidate.candidate_hash[:18]}-a{claim.attempt.attempt_number}"
        stamp = _now()
        workspace = WorkWorkspace(
            id=workspace_id,
            work_order_id=handoff.work_order_id,
            attempt_id=claim.attempt.id,
            repository=session.repository,
            base_revision=session.base_revision,
            branch_ref=session.branch_ref,
            state=WorkspaceState.ACTIVE,
            metadata={
                "evolution_candidate_id": candidate.id,
                "handoff_id": handoff.id,
                "portable": True,
            },
            created_at=stamp,
            updated_at=stamp,
        )
        self.work_store.register_workspace(workspace)
        run_id = f"cbr-{_digest(candidate.id, claim.attempt.id)[:24]}"
        with self.work_store.connection:
            self.work_store.connection.execute(
                """
                INSERT INTO evolution_code_body_runs(
                    id, candidate_id, handoff_id, work_order_id, attempt_id,
                    workspace_id, repository, base_revision, branch_ref, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candidate.id,
                    handoff.id,
                    handoff.work_order_id,
                    claim.attempt.id,
                    workspace_id,
                    session.repository,
                    session.base_revision,
                    session.branch_ref,
                    CodeBodyRunStatus.PREPARED.value,
                    stamp,
                    stamp,
                ),
            )
        self.work_store.append_work_event(
            handoff.work_order_id,
            "evolution.code_workspace.prepared",
            {"workspace_id": workspace_id, "branch_ref": session.branch_ref},
            attempt_id=claim.attempt.id,
        )
        run = self.get(run_id)
        if run is None:
            raise RuntimeError("code-body run was not persisted")
        return run

    def commit(self, candidate_id: str, *, message: str) -> CodeBodyRun:
        self._assert_continuation_authority()
        run = self._required_run(candidate_id, {CodeBodyRunStatus.PREPARED})
        lease = self._required_lease(run)
        session = self._session(run)
        status = self.repository_provider.commit_all(session, message=message)
        self._update_workspace(
            run.workspace_id,
            working_revision=status.revision,
            state=WorkspaceState.ACTIVE,
        )
        self._update_run(
            run.id,
            status=CodeBodyRunStatus.COMMITTED,
            working_revision=status.revision,
        )
        self.work_store.renew_lease(
            run.work_order_id,
            lease_token=lease.lease_token,
            worker_id=lease.worker_id,
            runtime_epoch=lease.runtime_epoch,
            lease_seconds=900,
        )
        self.work_store.append_work_event(
            run.work_order_id,
            "evolution.code_workspace.committed",
            {"workspace_id": run.workspace_id, "working_revision": status.revision},
            attempt_id=run.attempt_id,
        )
        return self._required_run(candidate_id, {CodeBodyRunStatus.COMMITTED})

    def verify(self, candidate_id: str) -> CodeBodyRun:
        self._assert_continuation_authority()
        run = self._required_run(candidate_id, {CodeBodyRunStatus.COMMITTED})
        if self.verification_provider is None:
            raise RuntimeError("code verification provider is not configured")
        lease = self._required_lease(run)
        session = self._session(run)
        repository_status = self.repository_provider.status(session)
        if repository_status.dirty:
            return self._verification_failed(
                run,
                lease.lease_token,
                code="dirty_workspace",
                failure_class=FailureClass.DIRTY_WORKSPACE,
                reason="workspace changed after implementation commit",
            )
        if repository_status.revision != run.working_revision:
            return self._verification_failed(
                run,
                lease.lease_token,
                code="working_revision_mismatch",
                failure_class=FailureClass.VALIDATION,
                reason="workspace revision differs from recorded implementation commit",
            )
        report = self.verification_provider.verify(session, revision=repository_status.revision)
        if report.revision != repository_status.revision:
            return self._verification_failed(
                run,
                lease.lease_token,
                code="verification_revision_mismatch",
                failure_class=FailureClass.VALIDATION,
                reason="verification provider reported a different revision",
            )
        evidence_id = f"ev-code-verify-{_digest(run.id, report.report_hash)[:24]}"
        summary = ", ".join(f"{check.name}:{'pass' if check.passed else 'fail'}" for check in report.checks)
        evidence = Evidence(
            id=evidence_id,
            source_type="repository_validation",
            source="evolution_code_verification",
            subject=f"software-body revision {repository_status.revision}",
            observation=f"Configured code verification checks: {summary}"[:3000],
            provenance=EvidenceProvenance.TOOL_VERIFIED if report.passed else EvidenceProvenance.OBSERVED,
            work_order_id=run.work_order_id,
            worker_run_id=run.attempt_id,
            artifact_ref=f"git:{repository_status.revision}",
            artifact_hash=report.report_hash,
            verification_state=VerificationState.VERIFIED if report.passed else VerificationState.REJECTED,
            verification_reason="all configured checks passed" if report.passed else "one or more configured checks failed",
            confidence=1.0,
        )
        try:
            self.evidence_store.record_evidence(evidence)
        except sqlite3.IntegrityError:
            pass
        if not report.passed:
            return self._verification_failed(
                run,
                lease.lease_token,
                code="verification_failed",
                failure_class=FailureClass.VALIDATION,
                reason="configured code verification failed",
                evidence_id=evidence_id,
                verification_hash=report.report_hash,
            )
        manifest = BodyManifest.load(session.local_path / self.body_manifest_path)
        body_revision_id = self.identity_store.record_body_revision(
            manifest,
            git_revision=repository_status.revision,
            status=BodyRevisionStatus.CANDIDATE,
        )
        self.work_store.finish_attempt(
            run.attempt_id,
            lease_token=lease.lease_token,
            status=WorkAttemptStatus.SUCCEEDED,
            metadata={
                "working_revision": repository_status.revision,
                "verification_hash": report.report_hash,
                "verification_evidence_id": evidence_id,
                "body_revision_id": body_revision_id,
            },
            max_attempts=1,
        )
        self._update_workspace(
            run.workspace_id,
            working_revision=repository_status.revision,
            state=WorkspaceState.REVIEW,
        )
        self._update_run(
            run.id,
            status=CodeBodyRunStatus.VERIFIED,
            verification_hash=report.report_hash,
            verification_evidence_id=evidence_id,
            body_revision_id=body_revision_id,
        )
        self.work_store.append_work_event(
            run.work_order_id,
            "evolution.code_workspace.verified",
            {
                "working_revision": repository_status.revision,
                "verification_evidence_id": evidence_id,
                "body_revision_id": body_revision_id,
            },
            attempt_id=run.attempt_id,
        )
        return self._required_run(candidate_id, {CodeBodyRunStatus.VERIFIED})

    def attach_review(self, candidate_id: str, *, review_ref: str) -> CodeBodyRun:
        self._assert_continuation_authority()
        run = self._required_run(candidate_id, {CodeBodyRunStatus.VERIFIED, CodeBodyRunStatus.REVIEW_READY})
        if run.status is CodeBodyRunStatus.REVIEW_READY:
            return run
        if self.review_verifier is None:
            raise RuntimeError("code review verifier is not configured")
        if not run.working_revision:
            raise RuntimeError("verified run has no working revision")
        review = self.review_verifier.verify(review_ref, revision=run.working_revision)
        if not review.verified:
            raise ValueError(review.reason or "review reference could not be verified")
        if not review.approved:
            raise ValueError(review.reason or "code review is not approved")
        review_evidence_id = f"ev-code-review-{_digest(run.id, review.review_ref, run.working_revision)[:24]}"
        item = Evidence(
            id=review_evidence_id,
            source_type="code_review",
            source="external_review_verifier",
            subject=f"software-body revision {run.working_revision}",
            observation=f"Approved code review verified for exact revision; reviewer={review.reviewer or 'unknown'}",
            provenance=EvidenceProvenance.EXTERNALLY_VERIFIED,
            work_order_id=run.work_order_id,
            worker_run_id=run.attempt_id,
            artifact_ref=review.review_ref,
            artifact_hash=_digest(review.review_ref, run.working_revision),
            verification_state=VerificationState.VERIFIED,
            verification_reason=review.reason or "approved review verified",
            confidence=1.0,
        )
        try:
            self.evidence_store.record_evidence(item)
        except sqlite3.IntegrityError:
            pass
        self._update_workspace(
            run.workspace_id,
            working_revision=run.working_revision,
            review_ref=review.review_ref,
            state=WorkspaceState.REVIEW,
        )
        self._update_run(
            run.id,
            status=CodeBodyRunStatus.REVIEW_READY,
            review_ref=review.review_ref,
            review_evidence_id=review_evidence_id,
            reviewer=review.reviewer,
        )
        evidence_ids = tuple(
            item
            for item in (run.verification_evidence_id, review_evidence_id)
            if item
        )
        self.work_store.complete_verified_work_order(
            run.work_order_id,
            attempt_id=run.attempt_id,
            evidence_ids=evidence_ids,
            review_ref=review.review_ref,
            actor="evolution_code_review",
        )
        self.work_store.append_work_event(
            run.work_order_id,
            "evolution.code_review.approved",
            {
                "review_ref": review.review_ref,
                "reviewer": review.reviewer,
                "review_evidence_id": review_evidence_id,
            },
            attempt_id=run.attempt_id,
        )
        return self._required_run(candidate_id, {CodeBodyRunStatus.REVIEW_READY})

    def _verification_failed(
        self,
        run: CodeBodyRun,
        lease_token: str,
        *,
        code: str,
        failure_class: FailureClass,
        reason: str,
        evidence_id: str | None = None,
        verification_hash: str | None = None,
    ) -> CodeBodyRun:
        self.work_store.finish_attempt(
            run.attempt_id,
            lease_token=lease_token,
            status=WorkAttemptStatus.FAILED,
            failure=WorkFailure(failure_class=failure_class, code=code, message=reason),
            metadata={"verification_evidence_id": evidence_id, "verification_hash": verification_hash},
            max_attempts=1,
        )
        self._update_workspace(run.workspace_id, state=WorkspaceState.PRESERVED)
        self._update_run(
            run.id,
            status=CodeBodyRunStatus.FAILED,
            verification_hash=verification_hash,
            verification_evidence_id=evidence_id,
        )
        failed = self.get(run.id)
        if failed is None:
            raise RuntimeError("failed run disappeared")
        return failed

    def _required_run(self, candidate_id: str, statuses: set[CodeBodyRunStatus]) -> CodeBodyRun:
        run = self.latest(candidate_id)
        if run is None:
            raise KeyError(candidate_id)
        if run.status not in statuses:
            allowed = ",".join(sorted(item.value for item in statuses))
            raise ValueError(f"code-body run must be one of: {allowed}")
        return run

    def _required_lease(self, run: CodeBodyRun):
        lease = self.work_store.get_lease(run.work_order_id)
        if lease is None or lease.attempt_id != run.attempt_id:
            raise RuntimeError("code-body Work lease is unavailable or no longer owned by this attempt")
        return lease

    def _session(self, run: CodeBodyRun) -> RepositoryWorkspaceSession:
        return self.repository_provider.resume(
            repository=run.repository,
            work_order_id=run.work_order_id,
            attempt_id=run.attempt_id,
            base_revision=run.base_revision,
            branch_ref=run.branch_ref,
        )

    def _update_run(self, run_id: str, *, status: CodeBodyRunStatus, **values: Any) -> None:
        allowed = {
            "working_revision",
            "verification_hash",
            "verification_evidence_id",
            "review_ref",
            "review_evidence_id",
            "reviewer",
            "body_revision_id",
        }
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, _now()]
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f"unsupported code-body field: {key}")
            assignments.append(f"{key} = ?")
            params.append(value)
        params.append(str(run_id))
        with self.work_store.connection:
            self.work_store.connection.execute(
                f"UPDATE evolution_code_body_runs SET {', '.join(assignments)} WHERE id = ?",
                tuple(params),
            )

    def _update_workspace(
        self,
        workspace_id: str,
        *,
        state: WorkspaceState,
        working_revision: str | None = None,
        review_ref: str | None = None,
    ) -> None:
        updates = ["state = ?", "updated_at = ?"]
        params: list[Any] = [state.value, _now()]
        if working_revision is not None:
            updates.append("working_revision = ?")
            params.append(working_revision)
        if review_ref is not None:
            updates.append("review_ref = ?")
            params.append(review_ref)
        params.append(str(workspace_id))
        with self.work_store.connection:
            cursor = self.work_store.connection.execute(
                f"UPDATE work_workspaces SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            if cursor.rowcount != 1:
                raise KeyError(workspace_id)
