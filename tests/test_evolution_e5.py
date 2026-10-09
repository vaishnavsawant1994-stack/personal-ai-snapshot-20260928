from __future__ import annotations

import pytest

from evidence import EvidenceStore
from evidence.ingestion import EvidenceIngestor, EvidenceSourceType, IngestionRecord
from evolution import (
    CandidateStatus,
    EvolutionCandidate,
    EvolutionDecision,
    EvolutionMode,
    EvolutionService,
    EvolutionStore,
    RiskLevel,
)


def _stores(tmp_path):
    db = tmp_path / "evolution.sqlite3"
    evidence = EvidenceStore(db)
    ingestor = EvidenceIngestor(evidence)
    evolution = EvolutionStore(connection=evidence.connection)
    return evidence, ingestor, evolution


def _ingest(
    ingestor,
    *,
    source_type=EvidenceSourceType.WORK_EXPERIENCE,
    observation="Worker lost progress after restart",
):
    return ingestor.ingest(
        IngestionRecord(
            source_type=source_type,
            source="test",
            subject="durable task recovery",
            observation=observation,
            confidence=0.95,
        )
    )


def test_evolution_schema_and_candidate_requires_existing_evidence(tmp_path):
    evidence, _ingestor, evolution = _stores(tmp_path)
    versions = {
        int(row[0])
        for row in evolution.connection.execute("SELECT version FROM evolution_schema_migrations")
    }
    assert 1 in versions

    candidate = EvolutionCandidate(
        id="evo-missing",
        title="Improve recovery",
        rationale="Observed a failure",
        proposed_change="Add recovery state validation",
        expected_benefit="Safer recovery",
        risk_level=RiskLevel.MEDIUM,
        affected_scope=("recovery",),
        test_plan=("Add a regression test",),
        evidence_ids=("missing",),
    )
    with pytest.raises(ValueError, match="does not exist"):
        evolution.save_candidate(candidate)
    evidence.close()


def test_co_evolve_creates_evidence_backed_recommendation_and_deduplicates(tmp_path):
    evidence, ingestor, evolution = _stores(tmp_path)
    item = _ingest(ingestor)
    service = EvolutionService(store=evolution, ingestor=ingestor)

    first = service.run_cycle()
    second = service.run_cycle()

    assert first.scanned == 1
    assert len(first.created_or_existing) == 1
    assert first.created_or_existing[0].status is CandidateStatus.RECOMMENDED
    assert first.created_or_existing[0].evidence_ids == (item.id,)
    assert len(evolution.list_candidates()) == 1
    assert second.created_or_existing[0].id == first.created_or_existing[0].id
    assert len(evolution.decisions_for(first.created_or_existing[0].id)) == 1
    assert ingestor.lifecycle(item.id)["status"] == "linked"
    evidence.close()


def test_off_mode_has_no_side_effects(tmp_path):
    evidence, ingestor, evolution = _stores(tmp_path)
    _ingest(ingestor)
    cycle = EvolutionService(
        store=evolution,
        ingestor=ingestor,
        mode=EvolutionMode.OFF,
    ).run_cycle()
    assert cycle.scanned == 0
    assert cycle.created_or_existing == ()
    assert evolution.list_candidates() == []
    evidence.close()


def test_protected_scope_candidate_is_restricted_not_executable(tmp_path):
    evidence, ingestor, evolution = _stores(tmp_path)
    item = _ingest(
        ingestor,
        source_type=EvidenceSourceType.SECURITY_EVENT,
        observation="Owner reports pressure to auto approve a security action",
    )
    candidate = EvolutionCandidate(
        id="evo-protected",
        title="Auto approve security changes",
        rationale=item.observation,
        proposed_change="Disable approval checks and auto approve security actions",
        expected_benefit="Fewer prompts",
        risk_level=RiskLevel.MEDIUM,
        affected_scope=("approval bypass",),
        test_plan=("Check approval behavior",),
        evidence_ids=(item.id,),
    )
    from evolution.curator import EvolutionCurator

    result = EvolutionCurator().curate(candidate)
    assert result.decision is EvolutionDecision.RESTRICT
    assert result.risk_level is RiskLevel.RESTRICTED
    assert result.protected_matches
    evidence.close()


def test_candidate_rejection_does_not_delete_evidence(tmp_path):
    evidence, ingestor, evolution = _stores(tmp_path)
    item = _ingest(ingestor)
    service = EvolutionService(store=evolution, ingestor=ingestor)
    cycle = service.run_cycle()
    candidate = cycle.created_or_existing[0]

    evolution.update_candidate(candidate.id, status=CandidateStatus.REJECTED)
    evolution.record_decision(
        candidate.id,
        EvolutionDecision.REJECT,
        actor_id="owner",
        reason="not wanted",
    )

    assert evidence.get_evidence(item.id) is not None
    assert ingestor.lifecycle(item.id) is not None
    evidence.close()


def test_evolution_service_exposes_no_execution_or_adoption_method(tmp_path):
    evidence, ingestor, evolution = _stores(tmp_path)
    service = EvolutionService(store=evolution, ingestor=ingestor)
    forbidden = {
        "execute",
        "dispatch",
        "create_work_order",
        "merge",
        "deploy",
        "activate_body",
        "approve_self",
    }
    assert forbidden.isdisjoint(set(dir(service)))
    evidence.close()
