from __future__ import annotations

from evidence import EvidenceIngestor, EvidenceStatus

from .config import EvolutionConfig, EvolutionMode
from .curator import EvolutionCurator
from .models import CandidateDraft, CandidateStatus, CurationResult, EvolutionCandidate
from .store import EvolutionStore
from .synthesizer import EvolutionSynthesizer


class EvolutionService:
    """Read-only/co-evolve candidate service with no execution authority."""

    def __init__(
        self,
        *,
        config: EvolutionConfig,
        evolution_store: EvolutionStore,
        evidence_ingestor: EvidenceIngestor,
    ) -> None:
        self.config = config
        self.store = evolution_store
        self.evidence_ingestor = evidence_ingestor
        self.synthesizer = EvolutionSynthesizer(evolution_store, evidence_ingestor)
        self.curator = EvolutionCurator(evolution_store, evidence_ingestor)

    def propose(self, draft: CandidateDraft) -> tuple[EvolutionCandidate, CurationResult]:
        if self.config.mode is EvolutionMode.OFF:
            raise PermissionError("evolution is disabled")
        candidate = self.synthesizer.synthesize(draft)
        result = self.curator.review(candidate)
        return self.store.get_candidate(candidate.id) or candidate, result

    def reject(self, candidate_id: str, *, actor_id: str, reason: str) -> EvolutionCandidate:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate.status in {CandidateStatus.HANDED_OFF, CandidateStatus.ADOPTED}:
            raise ValueError("candidate is beyond the read-only E5 decision boundary")
        self.store.record_decision(
            candidate.id,
            decision=CandidateStatus.REJECTED,
            actor_id=actor_id,
            reason=reason,
        )
        updated = self.store.update_candidate(candidate.id, status=CandidateStatus.REJECTED)
        # Rejection never deletes supporting Evidence and makes it available to
        # future, materially different candidates.
        for evidence_id in candidate.evidence_ids:
            if self.evidence_ingestor.store.get_evidence(evidence_id) is not None:
                self.evidence_ingestor.set_lifecycle(
                    evidence_id,
                    EvidenceStatus.ACTIVE,
                    actor=actor_id,
                    reason=f"candidate {candidate.id} rejected; evidence retained",
                )
        return updated

    def defer(self, candidate_id: str, *, actor_id: str, reason: str) -> EvolutionCandidate:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        self.store.record_decision(
            candidate.id,
            decision=CandidateStatus.DEFERRED,
            actor_id=actor_id,
            reason=reason,
        )
        return self.store.update_candidate(candidate.id, status=CandidateStatus.DEFERRED)

    def status(self) -> dict[str, object]:
        return {
            "mode": self.config.mode.value,
            "auto_evolve_enabled": self.config.auto_evolve_enabled,
            "counts": self.store.status_counts(),
            "execution_authority": False,
            "handoff_available": False,
            "body_adoption_authority": False,
        }
