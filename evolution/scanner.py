from __future__ import annotations

from dataclasses import dataclass

from evidence import Evidence
from evidence.ingestion import EvidenceIngestor, EvidenceSourceType, EvidenceStatus


DEFAULT_EVOLUTION_SOURCES = frozenset(
    {
        EvidenceSourceType.USER_FEEDBACK.value,
        EvidenceSourceType.USER_CORRECTION.value,
        EvidenceSourceType.WORK_EXPERIENCE.value,
        EvidenceSourceType.TOOL_FAILURE.value,
        EvidenceSourceType.VERIFICATION_FAILURE.value,
        EvidenceSourceType.RECOVERY_EVENT.value,
        EvidenceSourceType.SECURITY_EVENT.value,
        EvidenceSourceType.REPEATED_INTERVENTION.value,
        EvidenceSourceType.WORKFLOW_FRICTION.value,
        EvidenceSourceType.SKILL_ASSESSMENT.value,
        EvidenceSourceType.PERFORMANCE_REGRESSION.value,
    }
)


@dataclass(frozen=True)
class EvidenceScan:
    evidence: tuple[Evidence, ...]
    skipped_ids: tuple[str, ...]


class EvolutionScanner:
    """Read-only selector over E4's canonical, already-redacted Evidence."""

    def __init__(
        self,
        ingestor: EvidenceIngestor,
        *,
        minimum_confidence: float = 0.5,
        allowed_sources: frozenset[str] = DEFAULT_EVOLUTION_SOURCES,
    ) -> None:
        self.ingestor = ingestor
        self.minimum_confidence = float(minimum_confidence)
        self.allowed_sources = allowed_sources

    def scan(self) -> EvidenceScan:
        selected: list[Evidence] = []
        skipped: list[str] = []
        for item in self.ingestor.store.list_evidence():
            lifecycle = self.ingestor.lifecycle(item.id)
            status = str((lifecycle or {}).get("status") or EvidenceStatus.ACTIVE.value)
            if status not in {EvidenceStatus.ACTIVE.value, EvidenceStatus.LINKED.value}:
                skipped.append(item.id)
                continue
            if item.source_type not in self.allowed_sources or item.confidence < self.minimum_confidence:
                skipped.append(item.id)
                continue
            selected.append(item)
        return EvidenceScan(evidence=tuple(selected), skipped_ids=tuple(skipped))
