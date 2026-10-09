from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _strings(values: Sequence[Any], *, field_name: str, required: bool = False) -> tuple[str, ...]:
    items = tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    if required and not items:
        raise ValueError(f"{field_name} must not be empty")
    return items


class EvolutionMode(StrEnum):
    OFF = "off"
    CO_EVOLVE = "co_evolve"


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    RECOMMENDED = "recommended"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    RESTRICTED = "restricted"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RESTRICTED = "restricted"


class EvolutionDecision(StrEnum):
    RECOMMEND = "recommend"
    DEFER = "defer"
    REJECT = "reject"
    RESTRICT = "restrict"


@dataclass(frozen=True)
class EvolutionCandidate:
    id: str
    title: str
    rationale: str
    proposed_change: str
    expected_benefit: str
    risk_level: RiskLevel
    affected_scope: tuple[str, ...]
    test_plan: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: CandidateStatus = CandidateStatus.PROPOSED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        for label, value in (
            ("candidate id", self.id),
            ("title", self.title),
            ("rationale", self.rationale),
            ("proposed_change", self.proposed_change),
            ("expected_benefit", self.expected_benefit),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
        if not self.affected_scope:
            raise ValueError("affected_scope must not be empty")
        if not self.test_plan:
            raise ValueError("test_plan must not be empty")
        if not self.evidence_ids:
            raise ValueError("evidence_ids must not be empty")

    @property
    def candidate_hash(self) -> str:
        payload = {
            "title": self.title.strip(),
            "proposed_change": self.proposed_change.strip(),
            "expected_benefit": self.expected_benefit.strip(),
            "affected_scope": sorted(self.affected_scope),
            "test_plan": list(self.test_plan),
            "evidence_ids": sorted(self.evidence_ids),
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "rationale": self.rationale,
            "proposed_change": self.proposed_change,
            "expected_benefit": self.expected_benefit,
            "risk_level": self.risk_level.value,
            "affected_scope": list(self.affected_scope),
            "test_plan": list(self.test_plan),
            "evidence_ids": list(self.evidence_ids),
            "status": self.status.value,
            "candidate_hash": self.candidate_hash,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvolutionCandidate":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            rationale=str(data["rationale"]),
            proposed_change=str(data["proposed_change"]),
            expected_benefit=str(data["expected_benefit"]),
            risk_level=RiskLevel(str(data.get("risk_level", RiskLevel.MEDIUM.value))),
            affected_scope=_strings(data.get("affected_scope", ()), field_name="affected_scope", required=True),
            test_plan=_strings(data.get("test_plan", ()), field_name="test_plan", required=True),
            evidence_ids=_strings(data.get("evidence_ids", ()), field_name="evidence_ids", required=True),
            status=CandidateStatus(str(data.get("status", CandidateStatus.PROPOSED.value))),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
        )


@dataclass(frozen=True)
class CurationResult:
    decision: EvolutionDecision
    risk_level: RiskLevel
    reasons: tuple[str, ...]
    protected_matches: tuple[str, ...] = ()

    @property
    def allowed_for_owner_review(self) -> bool:
        return self.decision in {EvolutionDecision.RECOMMEND, EvolutionDecision.DEFER}
