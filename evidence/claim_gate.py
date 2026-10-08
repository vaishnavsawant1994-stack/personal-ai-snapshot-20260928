from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Claim, ClaimState, Evidence, EvidenceProvenance, VerificationState


@dataclass(frozen=True)
class ClaimRequirement:
    minimum_verified_evidence: int = 1
    minimum_provenance: EvidenceProvenance = EvidenceProvenance.TOOL_VERIFIED
    allowed_source_types: tuple[str, ...] = ()
    require_distinct_sources: bool = False

    def __post_init__(self) -> None:
        if self.minimum_verified_evidence < 1:
            raise ValueError("minimum_verified_evidence must be at least 1")


@dataclass(frozen=True)
class ClaimGateDecision:
    passed: bool
    state: ClaimState
    reasons: tuple[str, ...]
    qualifying_evidence_ids: tuple[str, ...] = ()


class ClaimGate:
    @staticmethod
    def evaluate(
        claim: Claim,
        evidence: Iterable[Evidence],
        requirement: ClaimRequirement | None = None,
    ) -> ClaimGateDecision:
        requirement = requirement or ClaimRequirement()
        if claim.state is ClaimState.REJECTED:
            return ClaimGateDecision(False, ClaimState.REJECTED, ("claim is rejected",))
        if claim.state is ClaimState.DISPUTED:
            return ClaimGateDecision(False, ClaimState.DISPUTED, ("claim is disputed",))

        candidates: list[Evidence] = []
        reasons: list[str] = []
        for item in evidence:
            if item.verification_state is not VerificationState.VERIFIED:
                continue
            if item.provenance.rank < requirement.minimum_provenance.rank:
                continue
            if requirement.allowed_source_types and item.source_type not in requirement.allowed_source_types:
                continue
            candidates.append(item)

        if requirement.require_distinct_sources:
            unique: dict[str, Evidence] = {}
            for item in candidates:
                unique.setdefault(item.source, item)
            candidates = list(unique.values())

        count = len(candidates)
        needed = requirement.minimum_verified_evidence
        if count >= needed:
            return ClaimGateDecision(
                True,
                ClaimState.VERIFIED,
                (f"{count} qualifying evidence item(s) satisfy the claim requirement",),
                tuple(item.id for item in candidates),
            )

        if count:
            reasons.append(f"only {count} of {needed} required evidence item(s) qualify")
            state = ClaimState.SUPPORTED
        else:
            reasons.append("no verified evidence meets the minimum provenance and source requirements")
            state = ClaimState.PROPOSED
        return ClaimGateDecision(False, state, tuple(reasons), tuple(item.id for item in candidates))
