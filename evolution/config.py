from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvolutionMode(StrEnum):
    OFF = "off"
    CO_EVOLVE = "co_evolve"
    AUTO_EVOLVE = "auto_evolve"


@dataclass(frozen=True)
class EvolutionConfig:
    mode: EvolutionMode = EvolutionMode.CO_EVOLVE
    auto_evolve_enabled: bool = False

    def __post_init__(self) -> None:
        if self.mode is EvolutionMode.AUTO_EVOLVE and not self.auto_evolve_enabled:
            raise ValueError("AUTO_EVOLVE is reserved and disabled")
