from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkQualificationScenario:
    id: str
    title: str
    requirement: str
    evidence_tests: tuple[str, ...]


FINAL_WORK_SCENARIOS: tuple[WorkQualificationScenario, ...] = (
    WorkQualificationScenario(
        "software_project",
        "Software Project",
        "Plan, execute, prove commit/push/deployment, review, and complete only after canonical proof.",
        ("tests/test_domain_claim_gate.py", "tests/test_authoritative_completion_judge.py"),
    ),
    WorkQualificationScenario(
        "research_project",
        "Research Project",
        "Conflicting evidence must be reviewable, replannable, and unable to complete until proof/review passes.",
        ("tests/test_authoritative_completion_judge.py", "tests/test_work_consistency_gate.py"),
    ),
    WorkQualificationScenario(
        "approval",
        "Approval Required",
        "Consequential execution stops at ApprovalManager and continues durably only after owner approval.",
        ("tests/test_project_autonomy_runtime.py", "tests/test_work_restart_recovery_e2e.py"),
    ),
    WorkQualificationScenario(
        "approval_rejected",
        "Approval Rejected",
        "Rejected owner approval cannot execute the requested external action.",
        ("tests/test_project_autonomy_runtime.py",),
    ),
    WorkQualificationScenario(
        "recovery",
        "Recovery",
        "Uncertain consequential effects become recovery-required and never blindly redispatch.",
        ("tests/test_work_restart_recovery_e2e.py",),
    ),
    WorkQualificationScenario(
        "review_failure",
        "Review Failure",
        "Unsupported claims and incomplete evidence block canonical completion until repaired/retested.",
        ("tests/test_domain_claim_gate.py", "tests/test_authoritative_completion_judge.py"),
    ),
    WorkQualificationScenario(
        "restart",
        "Restart Durability",
        "Restart preserves approvals, plans, deltas, evidence, claims, receipts and completion without duplicate effect.",
        ("tests/test_work_restart_recovery_e2e.py",),
    ),
    WorkQualificationScenario(
        "multi_project",
        "Multi-project Isolation",
        "Concurrent Projects keep context, evidence, approvals, recovery, memory, budgets and WorkOrders isolated.",
        ("tests/test_work_multiproject_qualification.py", "tests/test_work_multiproject_controls.py"),
    ),
    WorkQualificationScenario(
        "capability_outage",
        "Capability Outage",
        "Unavailable/disabled/degraded capabilities cannot be selected or executed as qualified capability.",
        ("tests/test_capability_qualification_enforcement.py",),
    ),
    WorkQualificationScenario(
        "emergency_stop",
        "Emergency Stop",
        "Emergency stop overrides Project autonomy modes and prevents further governed execution.",
        ("tests/test_project_autonomy_runtime.py", "tests/test_work_multiproject_controls.py"),
    ),
)


def required_test_files() -> tuple[str, ...]:
    seen: list[str] = []
    for scenario in FINAL_WORK_SCENARIOS:
        for path in scenario.evidence_tests:
            if path not in seen:
                seen.append(path)
    return tuple(seen)
