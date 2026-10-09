from __future__ import annotations

from evidence import EvidenceIngestor, EvidenceStatus

from .models import CandidateStatus, CurationResult, EvolutionCandidate, RiskLevel
from .protected_scope import evaluate_protected_scope
from .store import EvolutionStore


class EvolutionCurator:
    """Deterministic policy gate after synthesis and before any owner decision."""

    def __init__(self, evolution_store: EvolutionStore, evidence_ingestor: EvidenceIngestor) -> None:
        self.evolution_store = evolution_store
        self.evidence_ingestor = evidence_ingestor

    def review(self, candidate: EvolutionCandidate) -> CurationResult:
        reasons: list[str] = []
        if not candidate.test_plan:
            reasons.append("candidate has no test plan")
        if not candidate.affected_scope:
            reasons.append("candidate has no affected scope")
        if not candidate.evidence_ids:
            reasons.append("candidate has no supporting evidence")

        eligible_evidence = 0
        for evidence_id in candidate.evidence_ids:
            evidence = self.evidence_ingestor.store.get_evidence(evidence_id)
            lifecycle = self.evidence_ingestor.lifecycle(evidence_id)
            if evidence is None:
                reasons.append(f"missing evidence: {evidence_id}")
                continue
            if lifecycle is not None and lifecycle["status"] in {
                EvidenceStatus.DISMISSED.value,
                EvidenceStatus.SUPERSEDED.value,
            }:
                reasons.append(f"ineligible evidence: {evidence_id}")
                continue
            eligible_evidence += 1

        protected = evaluate_protected_scope(candidate.affected_scope, candidate.proposed_change)
        if protected.restricted:
            reasons.extend(protected.reasons)
            status = CandidateStatus.RESTRICTED
            risk = RiskLevel.RESTRICTED
        elif eligible_evidence == 0 or reasons:
            status = CandidateStatus.DEFERRED
            risk = RiskLevel.HIGH if len(candidate.affected_scope) > 4 else RiskLevel.MEDIUM
        else:
            status = CandidateStatus.RECOMMENDED
            if len(candidate.affected_scope) > 6:
                risk = RiskLevel.HIGH
            elif len(candidate.affected_scope) > 2:
                risk = RiskLevel.MEDIUM
            else:
                risk = RiskLevel.LOW
            reasons.append("candidate passed deterministic evidence, scope, and testability gates")

        updated = self.evolution_store.update_candidate(
            candidate.id,
            status=status,
            risk_level=risk,
        )
        self.evolution_store.record_review(
            updated.id,
            reviewer_type="deterministic_curator",
            status=status,
            risk_level=risk,
            reasons=tuple(reasons),
        )
        return CurationResult(
            candidate_id=updated.id,
            status=status,
            risk_level=risk,
            reasons=tuple(reasons),
        )
