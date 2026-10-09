from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evidence import EvidenceStore
from evidence.ingestion import EvidenceIngestor, EvidenceSourceType, IngestionRecord
from evolution import (
    CandidateStatus,
    CodeBodyEvolutionService,
    CodeBodyRunStatus,
    EvolutionHandoffService,
    EvolutionService,
    EvolutionStore,
    OwnerBodyAdoptionService,
    ReviewVerification,
    VerificationCheck,
    VerificationReport,
)
from future_intelligence.work_orchestration import (
    DurableWorkStore,
    LocalGitRepositoryProvider,
    RepositoryStatus,
    RepositoryWorkspaceSession,
    WorkOrderStatus,
)
from identity import BodyRevisionStatus, IdentityStore


_BODY = {
    "body_version": 1,
    "identity": {"name": "Vishnu", "role": "personal_ai"},
    "contracts": {"work": 1, "evidence": 2, "evolution": 1, "continuity": 1, "extension": 1},
    "mission": ["assist the owner", "preserve governed continuity"],
    "principles": ["software-body changes remain reviewable"],
}


class _FakeRepository:
    repository = "vaishnavsawant1994-stack/vishnu"

    def __init__(self, root: Path):
        self.root = root
        self.sessions: dict[str, RepositoryWorkspaceSession] = {}
        self.revisions = {"base-1": "base-1", "impl-1": "impl-1"}

    def resolve_revision(self, revision: str) -> str:
        value = str(revision)
        if value not in self.revisions:
            raise ValueError("unknown revision")
        return self.revisions[value]

    def read_text_at(self, revision: str, path: str) -> str:
        self.resolve_revision(revision)
        if path != "config/vishnu-body.yaml":
            raise KeyError(path)
        return json.dumps(_BODY)

    def prepare(self, *, repository, work_order_id, attempt_id, base_revision, branch_ref):
        base = self.resolve_revision(base_revision)
        local = self.root / f"{work_order_id}-{attempt_id}"
        (local / "config").mkdir(parents=True)
        (local / "config" / "vishnu-body.yaml").write_text(json.dumps(_BODY), encoding="utf-8")
        session = RepositoryWorkspaceSession(
            repository=repository,
            work_order_id=work_order_id,
            attempt_id=attempt_id,
            base_revision=base,
            branch_ref=branch_ref,
            local_path=local,
        )
        self.sessions[attempt_id] = session
        return session

    def resume(self, *, repository, work_order_id, attempt_id, base_revision, branch_ref):
        session = self.sessions[attempt_id]
        assert session.repository == repository
        assert session.work_order_id == work_order_id
        assert session.base_revision == self.resolve_revision(base_revision)
        assert session.branch_ref == branch_ref
        return session

    def status(self, session):
        revision = "impl-1" if (session.local_path / "implemented").exists() else session.base_revision
        return RepositoryStatus(revision=revision, dirty=False, changes=())

    def commit_all(self, session, *, message):
        assert message
        (session.local_path / "implemented").write_text("yes", encoding="utf-8")
        return RepositoryStatus(revision="impl-1", dirty=False, changes=())

    def preserve(self, session):
        assert session.local_path.exists()


class _Verifier:
    def verify(self, session, *, revision):
        return VerificationReport(
            revision=revision,
            checks=(
                VerificationCheck(
                    name="focused-tests",
                    command=("pytest", "-q"),
                    passed=True,
                    returncode=0,
                    duration_ms=12,
                    output_hash="a" * 64,
                    output_excerpt="passed",
                ),
            ),
        )


class _ReviewVerifier:
    def verify(self, review_ref, *, revision):
        return ReviewVerification(
            review_ref=review_ref,
            revision=revision,
            verified=True,
            approved=True,
            state="open",
            reviewer="reviewer",
            reason="approved review found",
        )


def _runtime(tmp_path):
    evidence = EvidenceStore(tmp_path / "evidence.sqlite3")
    ingestor = EvidenceIngestor(evidence)
    evolution = EvolutionStore(connection=evidence.connection)
    work = DurableWorkStore(tmp_path / "work.sqlite3")
    identity = IdentityStore(tmp_path / "identity.sqlite3")
    item = ingestor.ingest(
        IngestionRecord(
            source_type=EvidenceSourceType.WORK_EXPERIENCE,
            source="test",
            subject="code-body reliability",
            observation="Repository work needs isolated verified implementation",
            confidence=0.95,
        )
    )
    candidate = EvolutionService(store=evolution, ingestor=ingestor).run_cycle().created_or_existing[0]
    handoffs = EvolutionHandoffService(evolution_store=evolution, work_store=work)
    handoff = handoffs.approve(
        candidate.id,
        owner_id="owner",
        reason="implement",
        base_body_revision="base-1",
    )
    repo = _FakeRepository(tmp_path / "workspaces")
    code = CodeBodyEvolutionService(
        handoffs=handoffs,
        work_store=work,
        evidence_store=evidence,
        identity_store=identity,
        repository_provider=repo,
        verification_provider=_Verifier(),
        review_verifier=_ReviewVerifier(),
    )
    adoption = OwnerBodyAdoptionService(
        evolution_store=evolution,
        code_body=code,
        identity_store=identity,
        repository_provider=repo,
    )
    return evidence, evolution, work, identity, candidate, handoff, code, adoption


def test_e7_full_lifecycle_stops_at_separate_adoption_then_exact_activation(tmp_path):
    evidence, evolution, work, identity, candidate, handoff, code, adoption = _runtime(tmp_path)
    prepared = code.prepare(candidate.id, worker_id="code-worker", runtime_epoch=1)
    assert prepared.status is CodeBodyRunStatus.PREPARED
    assert work.get_order(handoff.work_order_id).status is WorkOrderStatus.RUNNING

    committed = code.commit(candidate.id, message="feat: implement approved evolution")
    assert committed.status is CodeBodyRunStatus.COMMITTED
    assert committed.working_revision == "impl-1"

    verified = code.verify(candidate.id)
    assert verified.status is CodeBodyRunStatus.VERIFIED
    assert verified.body_revision_id
    assert identity.get_body_revision(verified.body_revision_id)["status"] == BodyRevisionStatus.CANDIDATE.value
    assert identity.active_body_revision() is None
    assert work.get_order(handoff.work_order_id).status is WorkOrderStatus.VERIFYING

    reviewed = code.attach_review(candidate.id, review_ref="https://github.com/vaishnavsawant1994-stack/vishnu/pull/777")
    assert reviewed.status is CodeBodyRunStatus.REVIEW_READY
    assert work.get_order(handoff.work_order_id).status is WorkOrderStatus.COMPLETED
    assert identity.active_body_revision() is None

    approved = adoption.approve(candidate.id, owner_id="owner", reason="adopt reviewed implementation")
    assert approved.status == "approved"
    assert evolution.get_candidate(candidate.id).status is CandidateStatus.ADOPTION_APPROVED
    assert identity.active_body_revision() is None

    with pytest.raises(ValueError, match="running revision"):
        adoption.confirm_activation(candidate.id, running_revision="base-1")
    assert identity.active_body_revision() is None

    active = adoption.confirm_activation(candidate.id, running_revision="impl-1")
    assert active.status == "activated"
    assert identity.active_body_revision()["revision_id"] == reviewed.body_revision_id
    assert evolution.get_candidate(candidate.id).status is CandidateStatus.ADOPTED
    assert code.latest(candidate.id).status is CodeBodyRunStatus.ADOPTED
    evidence.close(); work.close(); identity.close()


def test_e7_requires_verification_provider_and_exposes_no_merge_push_deploy(tmp_path):
    evidence, evolution, work, identity, candidate, _handoff, code, _adoption = _runtime(tmp_path)
    code.verification_provider = None
    code.prepare(candidate.id, worker_id="code-worker", runtime_epoch=2)
    code.commit(candidate.id, message="feat: local only")
    with pytest.raises(RuntimeError, match="verification provider"):
        code.verify(candidate.id)
    forbidden = {"push", "merge", "deploy", "activate_body", "activate_body_revision"}
    assert forbidden.isdisjoint(set(dir(code)))
    assert forbidden.isdisjoint(set(dir(code.repository_provider)))
    evidence.close(); work.close(); identity.close()


def test_local_git_provider_uses_isolated_worktree_and_no_remote_mutation_surface(tmp_path):
    repo = tmp_path / "repo"
    workspace_root = tmp_path / "worktrees"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Vishnu Test"], check=True)
    (repo / "config").mkdir()
    (repo / "config" / "vishnu-body.yaml").write_text(json.dumps(_BODY), encoding="utf-8")
    (repo / "value.txt").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    provider = LocalGitRepositoryProvider(
        repository="vaishnavsawant1994-stack/vishnu",
        repository_root=repo,
        workspace_root=workspace_root,
    )
    assert provider.resolve_revision(base) == base
    assert json.loads(provider.read_text_at(base, "config/vishnu-body.yaml"))["identity"]["name"] == "Vishnu"
    session = provider.prepare(
        repository="vaishnavsawant1994-stack/vishnu",
        work_order_id="work-1",
        attempt_id="attempt-1",
        base_revision=base,
        branch_ref="vishnu/evolution/test",
    )
    assert session.local_path != repo
    (session.local_path / "value.txt").write_text("changed", encoding="utf-8")
    committed = provider.commit_all(session, message="test isolated change")
    assert committed.revision != base
    assert committed.dirty is False
    assert (repo / "value.txt").read_text(encoding="utf-8") == "base"
    resumed = provider.resume(
        repository=session.repository,
        work_order_id=session.work_order_id,
        attempt_id=session.attempt_id,
        base_revision=base,
        branch_ref=session.branch_ref,
    )
    assert resumed.local_path == session.local_path
    assert {"push", "merge", "deploy"}.isdisjoint(set(dir(provider)))
