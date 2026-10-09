from __future__ import annotations

from uuid import uuid4

from evidence import EvidenceIngestor, EvidenceStatus
from evidence.redaction import redact_text

from .models import CandidateDraft, CandidateStatus, EvolutionCandidate, RiskLevel
from .store import EvolutionStore


class EvolutionSynthesizer:
    """Build candidates from active Evidence without executing any action."""

    def __init__(self, evolution_store: EvolutionStore, evidence_ingestor: EvidenceIngestor) -> None:
        self.evolution_store = evolution_store
        self.evidence_ingestor = evidence_ingestor

    def synthesize(self, draft: CandidateDraft) -> EvolutionCandidate:
        for evidence_id in draft.evidence_ids:
            evidence = self.evidence_ingestor.store.get_evidence(evidence_id)
            if evidence is None:
                raise KeyError(f"evidence not found: {evidence_id}")
            lifecycle = self.evidence_ingestor.lifecycle(evidence_id)
            if lifecycle is not None and lifecycle["status"] in {
                EvidenceStatus.DISMISSED.value,
                EvidenceStatus.SUPERSEDED.value,
            }:
                raise ValueError(f"evidence is not eligible for synthesis: {evidence_id}")

        title = redact_text(draft.title).strip()
        rationale = redact_text(draft.rationale).strip()
        proposed_change = redact_text(draft.proposed_change).strip()
        expected_benefit = redact_text(draft.expected_benefit).strip()
        affected_scope = tuple(redact_text(item).strip() for item in draft.affected_scope if str(item).strip())
        test_plan = tuple(redact_text(item).strip() for item in draft.test_plan if str(item).strip())
        evidence_ids = tuple(dict.fromkeys(str(item) for item in draft.evidence_ids))
        metadata = {
            str(key): redact_text(value) if isinstance(value, str) else value
            for key, value in dict(draft.metadata).items()
        }
        candidate_hash = EvolutionCandidate.content_hash(
            title=title,
            rationale=rationale,
            proposed_change=proposed_change,
            expected_benefit=expected_benefit,
            affected_scope=affected_scope,
            test_plan=test_plan,
            evidence_ids=evidence_ids,
            metadata=metadata,
        )
        existing = self.evolution_store.find_by_hash(candidate_hash)
        if existing is not None:
            return existing

        candidate = EvolutionCandidate(
            id=f"ecand_{uuid4().hex}",
            status=CandidateStatus.PROPOSED,
            title=title,
            rationale=rationale,
            proposed_change=proposed_change,
            expected_benefit=expected_benefit,
            risk_level=RiskLevel.MEDIUM,
            affected_scope=affected_scope,
            test_plan=test_plan,
            evidence_ids=evidence_ids,
            candidate_hash=candidate_hash,
            metadata=metadata,
        )
        self.evolution_store.save_candidate(candidate)
        for evidence_id in evidence_ids:
            self.evidence_ingestor.set_lifecycle(
                evidence_id,
                EvidenceStatus.LINKED,
                actor="evolution.synthesizer",
                reason=f"linked to evolution candidate {candidate.id}",
            )
        return candidate
