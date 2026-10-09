from evidence.claim_gate import ClaimGate, ClaimRequirement
from evidence.models import (
    Claim,
    ClaimState,
    Evidence,
    EvidenceProvenance,
    VerificationState,
)


def _evidence(
    evidence_id: str,
    provenance: EvidenceProvenance,
    *,
    source: str = "github",
    source_type: str = "tool_result",
    verified: bool = True,
):
    return Evidence(
        id=evidence_id,
        source_type=source_type,
        source=source,
        subject="deployment",
        observation="Observed result",
        provenance=provenance,
        verification_state=(
            VerificationState.VERIFIED if verified else VerificationState.UNVERIFIED
        ),
        confidence=1.0,
    )


def test_model_only_evidence_cannot_satisfy_default_gate_even_if_marked_verified():
    claim = Claim(id="c1", text="Deployment succeeded")
    decision = ClaimGate.evaluate(
        claim,
        [_evidence("e1", EvidenceProvenance.MODEL_ONLY)],
    )
    assert decision.passed is False
    assert decision.state is ClaimState.PROPOSED


def test_tool_verified_evidence_satisfies_default_gate():
    claim = Claim(id="c1", text="Deployment succeeded")
    decision = ClaimGate.evaluate(
        claim,
        [_evidence("e1", EvidenceProvenance.TOOL_VERIFIED)],
    )
    assert decision.passed is True
    assert decision.state is ClaimState.VERIFIED
    assert decision.qualifying_evidence_ids == ("e1",)


def test_observed_evidence_is_below_default_gate():
    decision = ClaimGate.evaluate(
        Claim(id="c1", text="Deployment succeeded"),
        [_evidence("e1", EvidenceProvenance.OBSERVED)],
    )
    assert decision.passed is False


def test_source_type_and_distinct_source_requirements_are_enforced():
    claim = Claim(id="c1", text="Deployment succeeded")
    requirement = ClaimRequirement(
        minimum_verified_evidence=2,
        minimum_provenance=EvidenceProvenance.TOOL_VERIFIED,
        allowed_source_types=("tool_result",),
        require_distinct_sources=True,
    )
    same_source = [
        _evidence("e1", EvidenceProvenance.TOOL_VERIFIED, source="github"),
        _evidence("e2", EvidenceProvenance.REPLAYABLE, source="github"),
    ]
    assert ClaimGate.evaluate(claim, same_source, requirement).passed is False

    distinct_sources = same_source + [
        _evidence("e3", EvidenceProvenance.EXTERNALLY_VERIFIED, source="ci"),
        _evidence(
            "ignored",
            EvidenceProvenance.REPLAYABLE,
            source="browser",
            source_type="model_output",
        ),
    ]
    decision = ClaimGate.evaluate(claim, distinct_sources, requirement)
    assert decision.passed is True
    assert set(decision.qualifying_evidence_ids) == {"e1", "e3"}
