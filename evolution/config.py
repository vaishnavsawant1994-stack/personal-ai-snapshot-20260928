from __future__ import annotations

from dataclasses import dataclass

from .models import EvolutionMode


@dataclass(frozen=True)
class EvolutionConfig:
    mode: EvolutionMode = EvolutionMode.CO_EVOLVE
    minimum_evidence_confidence: float = 0.5
    maximum_candidates_per_cycle: int = 50

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.minimum_evidence_confidence) <= 1.0:
            raise ValueError("minimum_evidence_confidence must be between 0 and 1")
        if not 1 <= int(self.maximum_candidates_per_cycle) <= 500:
            raise ValueError("maximum_candidates_per_cycle must be between 1 and 500")
