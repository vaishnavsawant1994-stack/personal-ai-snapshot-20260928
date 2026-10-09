from __future__ import annotations

from dataclasses import dataclass

from evidence.ingestion import EvidenceIngestor, EvidenceStatus

from .curator import EvolutionCurator
from .models import CandidateStatus, EvolutionCandidate, EvolutionMode
from .scanner import EvolutionScanner
from .store import EvolutionStore
from .synthesizer import CandidateSynthesizer


@dataclass(frozen=True)
class EvolutionCycle:
    mode: EvolutionMode
    scanned: int
    created_or_existing: tuple[EvolutionCandidate, ...]
    skipped_ids: tuple[str, ...]


class EvolutionService:
    """E5 recommendation engine with intentionally no execution/adoption surface."""

    def __init__(
        self,
        *,
        store: EvolutionStore,
        ingestor: EvidenceIngestor,
        mode: EvolutionMode = EvolutionMode.CO_EVOLVE,
        scanner: EvolutionScanner | None = None,
        synthesizer: CandidateSynthesizer | None = None,
        curator: EvolutionCurator | None = None,
    ) -> None:
        self.store = store
        self.ingestor = ingestor
        self.mode = EvolutionMode(mode)
        self.scanner = scanner or EvolutionScanner(ingestor)
        self.synthesizer = synthesizer or CandidateSynthesizer()
        self.curator = curator or EvolutionCurator()

    def run_cycle(self) -> EvolutionCycle:
        if self.mode is EvolutionMode.OFF:
            return EvolutionCycle(mode=self.mode, scanned=0, created_or_existing=(), skipped_ids=())

        scan = self.scanner.scan()
        persisted: list[EvolutionCandidate] = []
        for proposal in self.synthesizer.synthesize(scan.evidence):
            existing = self.store.get_candidate(proposal.id)
            if existing is not None and existing.status is not CandidateStatus.PROPOSED:
                persisted.append(existing)
                continue

            result = self.curator.curate(proposal)
            proposal = self.store.save_candidate(proposal)
            updated = self.store.update_candidate(
                proposal.id,
                status=self.curator.status_for(result),
                risk_level=result.risk_level,
            )
            self.store.record_decision(
                updated.id,
                result.decision,
                actor_id="evolution_curator",
                reason="; ".join(result.reasons),
                payload={"protected_matches": list(result.protected_matches), "read_only": True},
            )
            for evidence_id in updated.evidence_ids:
                lifecycle = self.ingestor.lifecycle(evidence_id)
                if lifecycle is None or lifecycle.get("status") == EvidenceStatus.ACTIVE.value:
                    self.ingestor.set_lifecycle(
                        evidence_id,
                        EvidenceStatus.LINKED,
                        actor="evolution_service",
                        reason=f"linked to candidate {updated.id}",
                    )
            persisted.append(updated)

        return EvolutionCycle(
            mode=self.mode,
            scanned=len(scan.evidence),
            created_or_existing=tuple(persisted),
            skipped_ids=scan.skipped_ids,
        )
