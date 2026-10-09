from __future__ import annotations

from readiness.product_release import REQUIRED_GATES, WORK_ORCHESTRATION_BASELINE, evaluate

RC_SHA = "b" * 40


def _evidence(status: str = "HOLD"):
    gates = {
        name: {"status": status, "qualified_sha": RC_SHA, "evidence": [f"evidence:{name}"]}
        for name in REQUIRED_GATES
    }
    gates["work_orchestration"] = {
        "status": "PASS" if status == "PASS" else status,
        "qualified_sha": WORK_ORCHESTRATION_BASELINE,
        "evidence": ["PR #95 exact-SHA Work Orchestration release qualification"],
    }
    return {
        "schema": 1,
        "work_orchestration_baseline": WORK_ORCHESTRATION_BASELINE,
        "rc_sha": RC_SHA,
        "gates": gates,
    }


def test_product_release_gate_holds_when_external_evidence_is_missing():
    result = evaluate(_evidence())
    assert result["status"] == "HOLD"
    assert result["production_ready"] is False
    assert "physical_iphone" in result["missing"]
    assert "production_deployment" in result["missing"]


def test_product_release_gate_requires_pass_evidence_on_exact_rc_sha():
    evidence = _evidence("PASS")
    evidence["gates"]["physical_iphone"]["qualified_sha"] = "c" * 40
    result = evaluate(evidence)
    assert result["status"] == "FAIL"
    assert result["production_ready"] is False
    assert "physical_iphone" in result["failed"]


def test_product_release_gate_passes_only_when_every_gate_is_evidenced():
    result = evaluate(_evidence("PASS"), expected_rc_sha=RC_SHA)
    assert result["status"] == "PASS"
    assert result["production_ready"] is True
    assert result["missing"] == []
    assert result["failed"] == []


def test_product_release_gate_rejects_changed_orchestration_baseline():
    evidence = _evidence("PASS")
    evidence["work_orchestration_baseline"] = "d" * 40
    result = evaluate(evidence)
    assert result["status"] == "FAIL"
    assert "work orchestration baseline" in result["errors"][0]
