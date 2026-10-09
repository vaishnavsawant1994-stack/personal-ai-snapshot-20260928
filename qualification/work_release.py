from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Mapping

from .work_orchestration_final import FinalWorkQualificationReport


WORK_ORCHESTRATION_RELEASE_VERSION = 1

REQUIRED_WORK_RELEASE_GATES = (
    "canonical_work_consistency",
    "canonical_work_performance",
    "canonical_work_final",
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

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class WorkOrchestrationReleaseQualification:
    """Fail-closed release evidence for the canonical Work Orchestration subsystem.

    This is qualification metadata only. It cannot deploy, promote, approve,
    execute, recover, or declare the entire Vishnu product production-ready.
    """

    candidate_sha: str
    final_report: FinalWorkQualificationReport
    gates: Mapping[str, bool]
    generated_at: str
    version: int = WORK_ORCHESTRATION_RELEASE_VERSION

    @property
    def normalized_sha(self) -> str:
        return str(self.candidate_sha or "").strip().lower()

    @property
    def candidate_sha_valid(self) -> bool:
        return bool(_SHA40.fullmatch(self.normalized_sha))

    @property
    def exact_head_aligned(self) -> bool:
        return (
            self.candidate_sha_valid
            and self.normalized_sha == str(self.final_report.candidate_sha or "").strip().lower()
        )

    @property
    def missing_gates(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_WORK_RELEASE_GATES if name not in self.gates)

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_WORK_RELEASE_GATES if self.gates.get(name) is not True)

    @property
    def qualified(self) -> bool:
        return (
            self.version == WORK_ORCHESTRATION_RELEASE_VERSION
            and self.exact_head_aligned
            and self.final_report.qualified
            and not self.failed_gates
        )

    @property
    def status(self) -> str:
        return "qualified" if self.qualified else "hold"

    def to_dict(self) -> dict:
        return {
            "scope": "work_orchestration",
            "version": self.version,
            "candidate_sha": self.normalized_sha,
            "generated_at": self.generated_at,
            "status": self.status,
            "qualified": self.qualified,
            "exact_head_aligned": self.exact_head_aligned,
            "final_qualification": self.final_report.to_dict(),
            "gates": dict(self.gates),
            "missing_gates": list(self.missing_gates),
            "failed_gates": list(self.failed_gates),
            "authority": "qualification_only",
            "execution_authority": "existing_p10_p6_runtime",
            "deployment_authority": "none",
            "does_not_imply_product_production_ready": True,
            "product_production_ready": False,
        }


def build_release_qualification(
    candidate_sha: str,
    *,
    final_report: FinalWorkQualificationReport,
    gates: Mapping[str, bool],
) -> WorkOrchestrationReleaseQualification:
    return WorkOrchestrationReleaseQualification(
        candidate_sha=str(candidate_sha or "").strip(),
        final_report=final_report,
        gates=dict(gates),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
