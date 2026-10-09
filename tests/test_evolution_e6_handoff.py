from __future__ import annotations

import json

import pytest

from evidence import EvidenceStore
from evidence.ingestion import EvidenceIngestor, EvidenceSourceType, IngestionRecord
from evolution import (
    CandidateStatus,
    EvolutionCandidate,
    EvolutionHandoffService,
    EvolutionService,
    EvolutionStore,
    RiskLevel,
)
from future_intelligence.work_orchestration.durable_store import DurableWorkStore
from future_intelligence.work_orchestration.models import WorkOrderStatus


def _runtime(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.sqlite3")
    ingestor = EvidenceIngestor(evidence_store)
    evolution_store = EvolutionStore(connection=evidence_store.connection)
    work_store = DurableWorkStore(tmp_path / "work.sqlite3")
    return evidence_store, ingestor, evolution_store, work_store


def _recommended(ingestor, evolution_store):
    item = ingestor.ingest(
        IngestionRecord(
            source_type=EvidenceSourceType.WORK_EXPERIENCE,
            source="test",
            subject="repository task recovery",
            observation="Repository task needed a safer restart path",
            confidence=0.95,
        )
    )
    cycle = EvolutionService(store=evolution_store, ingestor=ingestor).run_cycle()
    return item, cycle.created_or_existing[0]


def test_owner_approval_creates_immutable_handoff_and_queued_work(tmp_path):
    evidence, ingestor, evolution, work = _runtime(tmp_path)
    item, candidate = _recommended(ingestor, evolution)
    service = EvolutionHandoffService(evolution_store=evolution, work_store=work)

    handoff = service.approve(
        candidate.id,
        owner_id="owner",
        reason="Implement the evidence-backed improvement",
        base_body_revision="abc123",
    )
    repeated = service.approve(
        candidate.id,
        owner_id="owner",
        reason="Implement the evidence-backed improvement",
        base_body_revision="abc123",
    )

    assert repeated == handoff
    assert service.get(candidate.id) == handoff
    assert evolution.get_candidate(candidate.id).status is CandidateStatus.HANDED_OFF
    order = work.get_order(handoff.work_order_id)
    assert order is not None
    assert order.status is WorkOrderStatus.QUEUED
    assert order.allowed_capabilities == ()
    assert order.resource_scope.metadata["evolution_candidate_id"] == candidate.id
    assert order.approval_policy["merge"] == "separate_owner_adoption_required"
    assert evidence.get_evidence(item.id) is not None
    owner_decisions = [row for row in evolution.decisions_for(candidate.id) if row["decision"] == "approve"]
    assert len(owner_decisions) == 1
    evidence.close(); work.close()


def test_non_owner_cannot_create_handoff(tmp_path):
    evidence, ingestor, evolution, work = _runtime(tmp_path)
    _item, candidate = _recommended(ingestor, evolution)
    service = EvolutionHandoffService(evolution_store=evolution, work_store=work)
    with pytest.raises(PermissionError, match="canonical owner"):
        service.approve(
            candidate.id,
            owner_id="other",
            reason="not authoritative",
            base_body_revision="abc123",
        )
    assert service.get(candidate.id) is None
    assert work.status()["orders"] == 0
    evidence.close(); work.close()


def test_restricted_candidate_cannot_be_handed_off(tmp_path):
    evidence, ingestor, evolution, work = _runtime(tmp_path)
    item = ingestor.ingest(
        IngestionRecord(
            source_type=EvidenceSourceType.SECURITY_EVENT,
            source="test",
            subject="approval policy",
            observation="Attempted auto approve behavior should remain blocked",
            confidence=1.0,
        )
    )
    candidate = EvolutionCandidate(
        id="evo-restricted",
        title="Auto approve owner actions",
        rationale=item.observation,
        proposed_change="Disable approval checks",
        expected_benefit="Fewer prompts",
        risk_level=RiskLevel.RESTRICTED,
        affected_scope=("approval bypass",),
        test_plan=("Verify approval behavior",),
        evidence_ids=(item.id,),
        status=CandidateStatus.RESTRICTED,
    )
    evolution.save_candidate(candidate)
    service = EvolutionHandoffService(evolution_store=evolution, work_store=work)
    with pytest.raises(ValueError, match="not eligible"):
        service.approve(
            candidate.id,
            owner_id="owner",
            reason="should fail",
            base_body_revision="abc123",
        )
    assert work.status()["orders"] == 0
    evidence.close(); work.close()


def test_work_collision_rolls_back_generated_goal_plan_and_handoff(tmp_path):
    evidence, ingestor, evolution, work = _runtime(tmp_path)
    _item, candidate = _recommended(ingestor, evolution)
    service = EvolutionHandoffService(evolution_store=evolution, work_store=work)
    suffix = candidate.candidate_hash[:20]
    work.connection.execute(
        """
        INSERT INTO work_orders(
            id, plan_id, project_id, project_task_id, worker_type,
            status, payload_json, created_at, updated_at
        ) VALUES (?, 'foreign-plan', NULL, NULL, 'test', 'queued', ?, 'now', 'now')
        """,
        (
            f"work-evo-{suffix}",
            json.dumps({
                "id": f"work-evo-{suffix}",
                "plan_id": "foreign-plan",
                "title": "foreign",
                "objective": "foreign",
                "worker_type": "test",
                "status": "queued",
                "resource_scope": {"metadata": {"evolution_candidate_id": "other"}},
            }),
        ),
    )
    work.connection.commit()

    with pytest.raises(ValueError, match="collides"):
        service.approve(
            candidate.id,
            owner_id="owner",
            reason="approved but collision must fail closed",
            base_body_revision="abc123",
        )

    assert service.get(candidate.id) is None
    assert work.get_goal(f"goal-evo-{suffix}") is None
    assert work.get_plan(f"plan-evo-{suffix}") is None
    assert evolution.get_candidate(candidate.id).status is CandidateStatus.RECOMMENDED
    evidence.close(); work.close()


def test_owner_rejection_preserves_evidence_and_creates_no_work(tmp_path):
    evidence, ingestor, evolution, work = _runtime(tmp_path)
    item, candidate = _recommended(ingestor, evolution)
    service = EvolutionHandoffService(evolution_store=evolution, work_store=work)
    service.reject(candidate.id, owner_id="owner", reason="not wanted")
    assert evolution.get_candidate(candidate.id).status is CandidateStatus.REJECTED
    assert evidence.get_evidence(item.id) is not None
    assert work.status()["orders"] == 0
    evidence.close(); work.close()
