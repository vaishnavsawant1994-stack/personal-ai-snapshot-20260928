from __future__ import annotations

import pytest

from evidence import EvidenceIngestor, EvidenceStatus, EvidenceStore
from evidence.sources import feedback_record
from evolution import (
    CandidateDraft,
    CandidateStatus,
    EvolutionConfig,
    EvolutionMode,
    EvolutionService,
    EvolutionStore,
    RiskLevel,
)


def _service():
    evidence_store = EvidenceStore()
    ingestor = EvidenceIngestor(evidence_store)
    evolution_store = EvolutionStore()
    service = EvolutionService(
        config=EvolutionConfig(),
        evolution_store=evolution_store,
        evidence_ingestor=ingestor,
    )
    return evidence_store, ingestor, evolution_store, service


def _draft(evidence_id: str, *, scope=("ui/work_page.py",), proposal="Improve retry-state explanation"):
    return CandidateDraft(
        title="Improve recovery explanation",
        rationale="Owner feedback shows the recovery state is confusing",
        proposed_change=proposal,
        expected_benefit="Clearer recovery behavior with fewer repeated interventions",
        affected_scope=tuple(scope),
        test_plan=("add regression test for recovery explanation",),
        evidence_ids=(evidence_id,),
    )


def test_co_evolve_synthesizes_and_recommends_evidence_backed_candidate():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(
            feedback_record("Recovery status needs a clearer explanation"),
            actor="owner",
        )
        candidate, result = service.propose(_draft(evidence.id))

        assert candidate.status is CandidateStatus.RECOMMENDED
        assert result.status is CandidateStatus.RECOMMENDED
        assert candidate.risk_level is RiskLevel.LOW
        assert ingestor.lifecycle(evidence.id)["status"] == EvidenceStatus.LINKED.value
        assert evolution_store.get_candidate(candidate.id) == candidate
        assert service.status()["execution_authority"] is False
    finally:
        evidence_store.close()
        evolution_store.close()


def test_duplicate_candidate_is_deduplicated_by_content_hash():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(feedback_record("Retry text repeats too often"), actor="owner")
        first, _ = service.propose(_draft(evidence.id))
        second, _ = service.propose(_draft(evidence.id))
        assert first.id == second.id
        assert len(evolution_store.list_candidates()) == 1
    finally:
        evidence_store.close()
        evolution_store.close()


def test_protected_scope_is_restricted_before_any_execution_boundary():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(feedback_record("Approval flow feels slow"), actor="owner")
        candidate, result = service.propose(
            _draft(
                evidence.id,
                scope=("core/permissions.py",),
                proposal="Bypass approval for this action and grant itself permission automatically",
            )
        )
        assert candidate.status is CandidateStatus.RESTRICTED
        assert result.risk_level is RiskLevel.RESTRICTED
        assert any("protected" in reason for reason in result.reasons)
    finally:
        evidence_store.close()
        evolution_store.close()


def test_rejected_candidate_does_not_delete_supporting_evidence():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(feedback_record("Maybe simplify this UI"), actor="owner")
        candidate, _ = service.propose(_draft(evidence.id))
        rejected = service.reject(candidate.id, actor_id="owner", reason="not worth changing now")

        assert rejected.status is CandidateStatus.REJECTED
        assert evidence_store.get_evidence(evidence.id) is not None
        assert ingestor.lifecycle(evidence.id)["status"] == EvidenceStatus.ACTIVE.value
    finally:
        evidence_store.close()
        evolution_store.close()


def test_dismissed_evidence_cannot_be_used_for_new_candidate():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(feedback_record("Temporary observation"), actor="owner")
        ingestor.set_lifecycle(
            evidence.id,
            EvidenceStatus.DISMISSED,
            actor="owner",
            reason="not actually a product issue",
        )
        with pytest.raises(ValueError, match="not eligible"):
            service.propose(_draft(evidence.id))
    finally:
        evidence_store.close()
        evolution_store.close()


def test_auto_evolve_is_reserved_and_disabled():
    with pytest.raises(ValueError, match="reserved and disabled"):
        EvolutionConfig(mode=EvolutionMode.AUTO_EVOLVE)


def test_e5_has_no_approval_handoff_or_execution_api():
    evidence_store, _ingestor, evolution_store, service = _service()
    try:
        assert not hasattr(service, "approve")
        assert not hasattr(service, "handoff")
        assert not hasattr(service, "execute")
        assert service.status()["handoff_available"] is False
        assert evolution_store.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evolution_handoffs'"
        ).fetchone() is None
    finally:
        evidence_store.close()
        evolution_store.close()


def test_candidate_text_is_redacted_before_persistence():
    evidence_store, ingestor, evolution_store, service = _service()
    try:
        evidence = ingestor.ingest(feedback_record("There is a retry issue"), actor="owner")
        candidate, _ = service.propose(
            CandidateDraft(
                title="Fix retry with api_key=top-secret-value",
                rationale="Observed retry friction",
                proposed_change="Improve retry handling",
                expected_benefit="Fewer failures",
                affected_scope=("ui/retry.py",),
                test_plan=("test retry",),
                evidence_ids=(evidence.id,),
            )
        )
        assert "top-secret-value" not in candidate.title
        assert "[REDACTED]" in candidate.title
    finally:
        evidence_store.close()
        evolution_store.close()
