from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .work_scenarios import FINAL_WORK_SCENARIOS


REQUIRED_RELEASE_GATES = (
    "final_scenario_suite",
    "full_pytest",
    "p3_iphone_pwa",
    "reliability_security",
    "p10_adversarial_durability",
    "p10_performance",
    "p10_soak",
    "package_ubuntu",
    "package_macos",
    "package_windows",
)


@dataclass(frozen=True)
class FinalWorkQualificationReport:
    candidate_sha: str
    scenarios: Mapping[str, bool]
    gates: Mapping[str, bool]
    generated_at: str

    @property
    def missing_scenarios(self) -> tuple[str, ...]:
        return tuple(s.id for s in FINAL_WORK_SCENARIOS if s.id not in self.scenarios)

    @property
    def failed_scenarios(self) -> tuple[str, ...]:
        return tuple(s.id for s in FINAL_WORK_SCENARIOS if self.scenarios.get(s.id) is not True)

    @property
    def missing_gates(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_RELEASE_GATES if name not in self.gates)

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_RELEASE_GATES if self.gates.get(name) is not True)

    @property
    def qualified(self) -> bool:
        return bool(self.candidate_sha.strip()) and not self.failed_scenarios and not self.failed_gates

    def to_dict(self) -> dict:
        return {
            "candidate_sha": self.candidate_sha,
            "generated_at": self.generated_at,
            "qualified": self.qualified,
            "scenarios": dict(self.scenarios),
            "gates": dict(self.gates),
            "missing_scenarios": list(self.missing_scenarios),
            "failed_scenarios": list(self.failed_scenarios),
            "missing_gates": list(self.missing_gates),
            "failed_gates": list(self.failed_gates),
            "authority": "qualification_only",
            "execution_authority": "existing_p10_p6_runtime",
        }


def build_report(
    candidate_sha: str,
    *,
    scenarios: Mapping[str, bool],
    gates: Mapping[str, bool],
) -> FinalWorkQualificationReport:
    """Build a fail-closed exact-head final qualification report.

    Missing, false, or unknown scenario/gate results can never produce QUALIFIED.
    This module does not execute tools or grant runtime authority.
    """
    return FinalWorkQualificationReport(
        candidate_sha=str(candidate_sha).strip(),
        scenarios=dict(scenarios),
        gates=dict(gates),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
