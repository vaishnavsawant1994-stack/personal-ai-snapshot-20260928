from __future__ import annotations

from .models import CandidateStatus, CurationResult, EvolutionCandidate, EvolutionDecision, RiskLevel
from .protected_scope import protected_scope_matches


class EvolutionCurator:
    """Deterministic policy gate after synthesis; never executes a candidate."""

    def curate(self, candidate: EvolutionCandidate) -> CurationResult:
        text_surfaces = (
            candidate.title,
            candidate.rationale,
            candidate.proposed_change,
            candidate.expected_benefit,
            *candidate.affected_scope,
            *candidate.test_plan,
        )
        matches = protected_scope_matches(text_surfaces)
        if matches:
            return CurationResult(
                decision=EvolutionDecision.RESTRICT,
                risk_level=RiskLevel.RESTRICTED,
                reasons=(
                    "candidate intersects a protected authority/security scope",
                    "E5 is recommendation-only and cannot hand off protected changes",
                ),
                protected_matches=tuple(match.key for match in matches),
            )

        if not candidate.evidence_ids:
            return CurationResult(
                decision=EvolutionDecision.REJECT,
                risk_level=RiskLevel.HIGH,
                reasons=("candidate has no supporting Evidence",),
            )

        if candidate.risk_level is RiskLevel.HIGH:
            return CurationResult(
                decision=EvolutionDecision.DEFER,
                risk_level=RiskLevel.HIGH,
                reasons=("high-risk candidate requires explicit owner review before any later handoff stage",),
            )

        return CurationResult(
            decision=EvolutionDecision.RECOMMEND,
            risk_level=candidate.risk_level,
            reasons=("candidate is evidence-backed, bounded, and testable",),
        )

    @staticmethod
    def status_for(result: CurationResult) -> CandidateStatus:
        return {
            EvolutionDecision.RECOMMEND: CandidateStatus.RECOMMENDED,
            EvolutionDecision.DEFER: CandidateStatus.DEFERRED,
            EvolutionDecision.REJECT: CandidateStatus.REJECTED,
            EvolutionDecision.RESTRICT: CandidateStatus.RESTRICTED,
        }[result.decision]
