from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable

from evidence import Evidence

from .models import EvolutionCandidate, RiskLevel


_SCOPE_BY_SOURCE = {
    "user_feedback": "product/behavior",
    "user_correction": "product/behavior",
    "work_experience": "future_intelligence/work_orchestration",
    "tool_failure": "agent/tool_execution",
    "verification_failure": "evidence/verification",
    "recovery_event": "recovery/execution",
    "security_event": "security",
    "repeated_intervention": "agent/autonomy",
    "workflow_friction": "automation/workflows",
    "skill_assessment": "skills",
    "performance_regression": "performance",
}

_CHANGE_BY_SOURCE = {
    "user_feedback": "Improve the affected behavior using the observed owner feedback.",
    "user_correction": "Correct the affected behavior and add a regression test for the correction.",
    "work_experience": "Reduce the observed work-execution friction while preserving existing authority boundaries.",
    "tool_failure": "Harden the affected tool execution path and its failure handling.",
    "verification_failure": "Strengthen verification so unsupported completion claims remain blocked.",
    "recovery_event": "Improve recovery and reconciliation for the observed failure mode without blind retry.",
    "security_event": "Harden the affected security path without reducing owner controls or approval requirements.",
    "repeated_intervention": "Reduce repeated owner intervention through safer planning or clearer state handling.",
    "workflow_friction": "Improve workflow orchestration for the observed friction while preserving approval policy.",
    "skill_assessment": "Improve the assessed skill behavior and add conformance coverage.",
    "performance_regression": "Restore the affected performance characteristic with a repeatable benchmark.",
}


class CandidateSynthesizer:
    """Deterministic E5 synthesis with no execution capability."""

    @staticmethod
    def _group_key(item: Evidence) -> tuple[str, str, str]:
        return (
            item.source_type,
            item.project_id or "",
            item.work_order_id or item.subject[:120],
        )

    def synthesize(self, evidence: Iterable[Evidence]) -> tuple[EvolutionCandidate, ...]:
        groups: dict[tuple[str, str, str], list[Evidence]] = defaultdict(list)
        for item in evidence:
            groups[self._group_key(item)].append(item)

        candidates: list[EvolutionCandidate] = []
        for key in sorted(groups):
            items = sorted(groups[key], key=lambda item: (item.created_at, item.id))
            source_type = key[0]
            evidence_ids = tuple(item.id for item in items)
            observations = tuple(dict.fromkeys(item.observation.strip() for item in items if item.observation.strip()))
            subject = items[0].subject.strip()
            scope = _SCOPE_BY_SOURCE.get(source_type, "agent/runtime")
            proposed = _CHANGE_BY_SOURCE.get(
                source_type,
                "Investigate the observed behavior and implement a bounded, testable improvement.",
            )
            title = f"Improve {subject}"[:180]
            rationale = " | ".join(observations)[:3000]
            benefit = f"Reduce recurrence of the observed {source_type.replace('_', ' ')} while preserving governed execution."
            tests = (
                f"Add a regression test reproducing the evidence-backed {source_type.replace('_', ' ')}.",
                "Run the affected focused qualification suite.",
                "Run security and authority regression coverage before adoption.",
            )
            digest = hashlib.sha256(
                ("|".join(sorted(evidence_ids)) + "|" + proposed + "|" + scope).encode("utf-8")
            ).hexdigest()
            candidates.append(
                EvolutionCandidate(
                    id=f"evo-{digest[:24]}",
                    title=title,
                    rationale=rationale,
                    proposed_change=proposed,
                    expected_benefit=benefit,
                    risk_level=RiskLevel.HIGH if source_type == "security_event" else RiskLevel.MEDIUM,
                    affected_scope=(scope,),
                    test_plan=tests,
                    evidence_ids=evidence_ids,
                    metadata={"source_type": source_type, "read_only": True},
                )
            )
        return tuple(candidates)
