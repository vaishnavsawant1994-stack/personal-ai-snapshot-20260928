from __future__ import annotations

from dataclasses import asdict, dataclass


WORK_FINAL_QUALIFICATION_VERSION = 1


@dataclass(frozen=True)
class FinalQualificationContract:
    """Frozen qualification contract for canonical Work Orchestration.

    This module is intentionally declarative. It creates no execution, approval,
    recovery, evidence, review, memory, event, or completion authority. CI uses
    it to keep the final qualification surface explicit and auditable.
    """

    version: int
    authorities: tuple[tuple[str, str], ...]
    invariants: tuple[str, ...]
    test_patterns: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


FINAL_WORK_QUALIFICATION = FinalQualificationContract(
    version=WORK_FINAL_QUALIFICATION_VERSION,
    authorities=(
        ("execution", "existing_p10_p6_runtime"),
        ("approval", "approval_manager"),
        ("recovery", "recovery_authority"),
        ("evidence", "evidence_store"),
        ("claims", "domain_claim_gate"),
        ("review", "deterministic_reviewer"),
        ("completion", "deterministic_completion_judge"),
        ("memory", "governed_memory"),
        ("events", "core_events"),
    ),
    invariants=(
        "model output never grants tool authority",
        "consequential claims require deterministic evidence-backed proof",
        "raw execution completion never bypasses the Completion Judge",
        "uncertain external effects enter recovery and are never blindly replayed",
        "Project scope, approvals, budgets, memory, knowledge and evidence remain isolated",
        "Active Project autonomy remains bounded by policy, approval, recovery and completion gates",
        "verified Work may only propose governed Memory candidates; it cannot self-approve durable Memory",
        "canonical Work events remain projections and never become a second decision authority",
        "global product projections remain consistent with canonical Work completion and attention state",
        "qualified read paths remain bounded at realistic multi-Project scale",
    ),
    test_patterns=(
        "tests/test_work_*.py",
        "tests/test_domain_claim_gate.py",
        "tests/test_evidence_*.py",
        "tests/test_authoritative_completion_judge.py",
        "tests/test_completion_runtime_integration.py",
        "tests/test_project_autonomy_*.py",
    ),
)


def final_qualification_manifest() -> dict:
    return FINAL_WORK_QUALIFICATION.to_dict()
