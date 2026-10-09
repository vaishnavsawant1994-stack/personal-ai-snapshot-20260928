from __future__ import annotations

from pathlib import Path

from evidence.migrations import EVIDENCE_SCHEMA_VERSION
from future_intelligence.work_orchestration.migrations import WORK_SCHEMA_VERSION
from qualification.work_final import (
    FINAL_WORK_QUALIFICATION,
    WORK_FINAL_QUALIFICATION_VERSION,
    final_qualification_manifest,
)
from qualification.work_orchestration_final import REQUIRED_RELEASE_GATES, build_report
from qualification.work_scenarios import FINAL_WORK_SCENARIOS, required_test_files


ROOT = Path(__file__).resolve().parents[1]


def test_final_qualification_contract_freezes_authorities_and_invariants():
    contract = FINAL_WORK_QUALIFICATION
    assert contract.version == WORK_FINAL_QUALIFICATION_VERSION == 1
    authorities = dict(contract.authorities)
    assert authorities == {
        "execution": "existing_p10_p6_runtime",
        "approval": "approval_manager",
        "recovery": "recovery_authority",
        "evidence": "evidence_store",
        "claims": "domain_claim_gate",
        "review": "deterministic_reviewer",
        "completion": "deterministic_completion_judge",
        "memory": "governed_memory",
        "events": "core_events",
    }
    assert len(contract.invariants) >= 10
    assert len(set(contract.invariants)) == len(contract.invariants)


def test_final_gate_patterns_cover_required_tranches():
    patterns = set(FINAL_WORK_QUALIFICATION.test_patterns)
    assert "tests/test_work_*.py" in patterns
    assert "tests/test_domain_claim_gate.py" in patterns
    assert "tests/test_evidence_*.py" in patterns
    assert "tests/test_authoritative_completion_judge.py" in patterns
    assert "tests/test_completion_runtime_integration.py" in patterns
    assert "tests/test_project_autonomy_*.py" in patterns


def test_final_scenario_catalog_covers_all_required_operating_failures():
    ids = {scenario.id for scenario in FINAL_WORK_SCENARIOS}
    assert ids == {
        "software_project",
        "research_project",
        "approval",
        "approval_rejected",
        "recovery",
        "review_failure",
        "restart",
        "multi_project",
        "capability_outage",
        "emergency_stop",
    }
    for test_path in required_test_files():
        assert (ROOT / test_path).is_file(), test_path


def test_final_exact_head_report_is_fail_closed():
    scenarios = {scenario.id: True for scenario in FINAL_WORK_SCENARIOS}
    gates = {gate: True for gate in REQUIRED_RELEASE_GATES}
    qualified = build_report("a" * 40, scenarios=scenarios, gates=gates)
    assert qualified.qualified is True
    assert qualified.to_dict()["authority"] == "qualification_only"
    assert qualified.to_dict()["execution_authority"] == "existing_p10_p6_runtime"

    missing_gate = dict(gates)
    missing_gate.pop(REQUIRED_RELEASE_GATES[0])
    assert build_report("a" * 40, scenarios=scenarios, gates=missing_gate).qualified is False

    failed_scenario = dict(scenarios)
    failed_scenario[FINAL_WORK_SCENARIOS[0].id] = False
    assert build_report("a" * 40, scenarios=failed_scenario, gates=gates).qualified is False
    assert build_report("", scenarios=scenarios, gates=gates).qualified is False


def test_final_contract_tracks_current_additive_store_versions():
    # #93 introduced the qualified read-path indexes as additive schema v2.
    assert WORK_SCHEMA_VERSION >= 2
    assert EVIDENCE_SCHEMA_VERSION >= 2


def test_final_qualification_manifest_is_serializable_and_non_authoritative():
    manifest = final_qualification_manifest()
    assert manifest["version"] == 1
    assert manifest["authorities"]
    assert manifest["invariants"]
    assert manifest["test_patterns"]
    assert not hasattr(FINAL_WORK_QUALIFICATION, "execute")
    assert not hasattr(FINAL_WORK_QUALIFICATION, "approve")
    assert not hasattr(FINAL_WORK_QUALIFICATION, "recover")
    assert not hasattr(FINAL_WORK_QUALIFICATION, "complete")


def test_ci_runs_named_final_gate_before_full_repository_suite():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    marker = "Canonical Work final qualification gate"
    assert marker in workflow
    marker_index = workflow.index(marker)
    full_suite_index = workflow.rindex("- run: pytest -q")
    assert marker_index < full_suite_index
    for pattern in FINAL_WORK_QUALIFICATION.test_patterns:
        assert pattern in workflow
