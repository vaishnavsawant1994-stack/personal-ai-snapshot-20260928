from __future__ import annotations

from pathlib import Path

from qualification.work_orchestration_final import REQUIRED_RELEASE_GATES, build_report
from qualification.work_scenarios import FINAL_WORK_SCENARIOS
from qualification.work_release import (
    REQUIRED_WORK_RELEASE_GATES,
    WORK_ORCHESTRATION_RELEASE_VERSION,
    build_release_qualification,
)


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _final_report(*, sha: str = SHA, qualified: bool = True):
    scenarios = {scenario.id: True for scenario in FINAL_WORK_SCENARIOS}
    gates = {gate: True for gate in REQUIRED_RELEASE_GATES}
    if not qualified:
        scenarios[FINAL_WORK_SCENARIOS[0].id] = False
    return build_report(sha, scenarios=scenarios, gates=gates)


def _release_gates():
    return {gate: True for gate in REQUIRED_WORK_RELEASE_GATES}


def test_release_qualifies_only_with_exact_head_final_report_and_all_gates():
    result = build_release_qualification(
        SHA,
        final_report=_final_report(),
        gates=_release_gates(),
    )
    assert result.qualified is True
    assert result.status == "qualified"
    data = result.to_dict()
    assert data["scope"] == "work_orchestration"
    assert data["version"] == WORK_ORCHESTRATION_RELEASE_VERSION == 1
    assert data["exact_head_aligned"] is True
    assert data["deployment_authority"] == "none"


def test_release_fails_closed_on_invalid_or_mismatched_sha():
    gates = _release_gates()
    assert build_release_qualification("", final_report=_final_report(), gates=gates).qualified is False
    assert build_release_qualification("abc", final_report=_final_report(), gates=gates).qualified is False
    assert build_release_qualification("g" * 40, final_report=_final_report(), gates=gates).qualified is False
    mismatch = build_release_qualification(
        "b" * 40,
        final_report=_final_report(sha=SHA),
        gates=gates,
    )
    assert mismatch.qualified is False
    assert mismatch.exact_head_aligned is False


def test_release_fails_closed_on_missing_or_failed_gate():
    missing = _release_gates()
    missing.pop(REQUIRED_WORK_RELEASE_GATES[0])
    result = build_release_qualification(SHA, final_report=_final_report(), gates=missing)
    assert result.qualified is False
    assert REQUIRED_WORK_RELEASE_GATES[0] in result.missing_gates

    failed = _release_gates()
    failed[REQUIRED_WORK_RELEASE_GATES[-1]] = False
    result = build_release_qualification(SHA, final_report=_final_report(), gates=failed)
    assert result.qualified is False
    assert REQUIRED_WORK_RELEASE_GATES[-1] in result.failed_gates


def test_release_requires_final_qualification_to_pass():
    result = build_release_qualification(
        SHA,
        final_report=_final_report(qualified=False),
        gates=_release_gates(),
    )
    assert result.qualified is False
    assert result.status == "hold"


def test_release_never_claims_entire_product_is_production_ready_or_grants_actions():
    result = build_release_qualification(SHA, final_report=_final_report(), gates=_release_gates())
    data = result.to_dict()
    assert data["does_not_imply_product_production_ready"] is True
    assert data["product_production_ready"] is False
    assert data["authority"] == "qualification_only"
    assert not hasattr(result, "execute")
    assert not hasattr(result, "deploy")
    assert not hasattr(result, "promote")
    assert not hasattr(result, "approve")


def test_ci_runs_named_release_gate_before_full_repository_suite():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    marker = "Canonical Work release qualification gate"
    assert marker in workflow
    marker_index = workflow.index(marker)
    full_suite_index = workflow.rindex("- run: pytest -q")
    assert marker_index < full_suite_index
    assert "tests/test_work_release_qualification.py" in workflow
