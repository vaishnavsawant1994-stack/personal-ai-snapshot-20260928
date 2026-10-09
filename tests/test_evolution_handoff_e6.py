from __future__ import annotations

import sqlite3

import pytest

from evidence import EvidenceIngestor, EvidenceStore
from evidence.sources import feedback_record
from evolution import (
    CandidateDraft,
    CandidateStatus,
    EvolutionConfig,
    EvolutionHandoffService,
    EvolutionService,
    EvolutionStore,
)
from future_intelligence.work_orchestration import DurableWorkStore, GoalSpec, WorkOrderStatus


def _shared_runtime():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    work = DurableWorkStore(connection=connection)
    evidence = EvidenceStore(connection=connection)
    evolution = EvolutionStore(connection=connection)
    ingestor = EvidenceIngestor(evidence)
    service = EvolutionService(
        config=EvolutionConfig(),
        evolution_store=evolution,
        evidence_ingestor=ingestor,
    )
    handoff = EvolutionHandoffService(evolution, work)
    return connection, work, evidence, evolution, ingestor, service, handoff


def _recommended(service, ingestor, *, scope=("ui/recovery.py",)):
    evidence = ingestor.ingest(
        feedback_record("Recovery explanation needs improvement"),
        actor="owner",
    )
    candidate, result = service.propose(
        CandidateDraft(
            title="Improve recovery explanation",
            rationale="Owner feedback demonstrates recurring confusion",
            proposed_change="Improve the recovery explanation and add tests",
            expected_benefit="Fewer repeated owner interventions",
            affected_scope=tuple(scope),
            test_plan=("run focused recovery UI tests", "run regression suite"),
            evidence_ids=(evidence.id,),
            metadata={"project_id": "project-1", "allowed_repositories": ["vaishnavsawant1994-stack/vishnu"]},
        )
    )
    assert result.status is CandidateStatus.RECOMMENDED
    return candidate


def test_owner_approval_atomically_materializes_immutable_canonical_work():
    connection, work, _evidence, evolution, ingestor, service, handoff_service = _shared_runtime()
    try:
        candidate = _recommended(service, ingestor)
        handoff = handoff_service.approve_and_handoff(
            candidate.id,
            actor_id="owner",
            reason="approved for implementation only",
            base_body_revision="body-rev-1",
        )

        assert handoff.candidate_id == candidate.id
        assert evolution.get_candidate(candidate.id).status is CandidateStatus.HANDED_OFF
        goal = work.get_goal(handoff.goal_id)
        plan = work.get_plan(handoff.plan_id)
        order = work.get_order(handoff.work_order_id)
        assert goal is not None and plan is not None and order is not None
        assert order.status is WorkOrderStatus.QUEUED
        assert order.allowed_capabilities == ()
        assert order.approval_policy["merge_requires_separate_owner_approval"] is True
        assert order.approval_policy["deploy_requires_separate_owner_approval"] is True
        assert order.approval_policy["body_activation_requires_separate_owner_approval"] is True
        assert order.resource_scope.allowed_paths == candidate.affected_scope
        assert connection.execute(
            "SELECT COUNT(*) FROM evolution_decisions WHERE candidate_id = ? AND decision = 'approved'",
            (candidate.id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM work_events WHERE work_order_id = ? AND event_type = 'evolution.handoff.created'",
            (order.id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_handoff_is_idempotent_and_database_immutable():
    connection, _work, _evidence, _evolution, ingestor, service, handoff_service = _shared_runtime()
    try:
        candidate = _recommended(service, ingestor)
        first = handoff_service.approve_and_handoff(
            candidate.id,
            actor_id="owner",
            reason="approved",
            base_body_revision="body-rev-1",
        )
        second = handoff_service.approve_and_handoff(
            candidate.id,
            actor_id="owner",
            reason="duplicate request",
            base_body_revision="body-rev-1",
        )
        assert first == second
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE evolution_handoffs SET base_body_revision = 'other' WHERE id = ?",
                (first.id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM evolution_handoffs WHERE id = ?", (first.id,))
        connection.rollback()
    finally:
        connection.close()


def test_handoff_requires_one_shared_transaction_connection():
    evolution = EvolutionStore()
    work = DurableWorkStore()
    try:
        with pytest.raises(ValueError, match="share one SQLite connection"):
            EvolutionHandoffService(evolution, work)
    finally:
        evolution.close()
        work.close()


def test_restricted_candidate_cannot_enter_ordinary_handoff():
    connection, work, _evidence, evolution, ingestor, service, _handoff_service = _shared_runtime()
    try:
        evidence = ingestor.ingest(feedback_record("Approval flow is slow"), actor="owner")
        candidate, result = service.propose(
            CandidateDraft(
                title="Change permissions",
                rationale="Reduce clicks",
                proposed_change="Bypass approval and grant itself permission",
                expected_benefit="Fewer approval prompts",
                affected_scope=("core/permissions.py",),
                test_plan=("test permissions",),
                evidence_ids=(evidence.id,),
            )
        )
        assert result.status is CandidateStatus.RESTRICTED
        # Even a direct handoff service call cannot bypass the candidate-state gate.
        handoff = EvolutionHandoffService(evolution, work)
        with pytest.raises(ValueError, match="only recommended"):
            handoff.approve_and_handoff(
                candidate.id,
                actor_id="owner",
                reason="try to force it",
                base_body_revision="body-rev-1",
            )
    finally:
        connection.close()


def test_transaction_rolls_back_owner_decision_when_work_materialization_fails():
    connection, work, _evidence, evolution, ingestor, service, handoff_service = _shared_runtime()
    try:
        candidate = _recommended(service, ingestor)
        conflicting_goal_id = f"evo-goal:{candidate.id}"
        work.upsert_goal(
            GoalSpec(
                id=conflicting_goal_id,
                title="Conflicting goal",
                objective="force unique-key failure",
                desired_outcome="prove rollback",
            )
        )

        with pytest.raises(sqlite3.IntegrityError):
            handoff_service.approve_and_handoff(
                candidate.id,
                actor_id="owner",
                reason="approved",
                base_body_revision="body-rev-1",
            )

        assert evolution.get_candidate(candidate.id).status is CandidateStatus.RECOMMENDED
        assert connection.execute(
            "SELECT COUNT(*) FROM evolution_decisions WHERE candidate_id = ?",
            (candidate.id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM evolution_handoffs WHERE candidate_id = ?",
            (candidate.id,),
        ).fetchone()[0] == 0
        assert work.get_order(f"evo-work:{candidate.id}") is None
    finally:
        connection.close()


def test_handoff_service_has_no_merge_deploy_or_body_activation_api():
    connection, _work, _evidence, _evolution, _ingestor, _service, handoff_service = _shared_runtime()
    try:
        assert not hasattr(handoff_service, "merge")
        assert not hasattr(handoff_service, "deploy")
        assert not hasattr(handoff_service, "activate_body")
    finally:
        connection.close()
