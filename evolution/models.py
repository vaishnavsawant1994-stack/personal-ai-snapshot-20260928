from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    RECOMMENDED = "recommended"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    RESTRICTED = "restricted"
    APPROVED = "approved"
    HANDED_OFF = "handed_off"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class CandidateDraft:
    title: str
    rationale: str
    proposed_change: str
    expected_benefit: str
    affected_scope: tuple[str, ...]
    test_plan: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("title", self.title),
            ("rationale", self.rationale),
            ("proposed_change", self.proposed_change),
            ("expected_benefit", self.expected_benefit),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
        if not self.affected_scope:
            raise ValueError("affected_scope is required")
        if not self.test_plan:
            raise ValueError("test_plan is required")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")


@dataclass(frozen=True)
class EvolutionCandidate:
    id: str
    status: CandidateStatus
    title: str
    rationale: str
    proposed_change: str
    expected_benefit: str
    risk_level: RiskLevel
    affected_scope: tuple[str, ...]
    test_plan: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    candidate_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @staticmethod
    def content_hash(
        *,
        title: str,
        rationale: str,
        proposed_change: str,
        expected_benefit: str,
        affected_scope: tuple[str, ...],
        test_plan: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        return _stable_hash(
            {
                "title": title.strip(),
                "rationale": rationale.strip(),
                "proposed_change": proposed_change.strip(),
                "expected_benefit": expected_benefit.strip(),
                "affected_scope": sorted(set(affected_scope)),
                "test_plan": list(test_plan),
                "evidence_ids": sorted(set(evidence_ids)),
                "metadata": dict(metadata or {}),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "title": self.title,
            "rationale": self.rationale,
            "proposed_change": self.proposed_change,
            "expected_benefit": self.expected_benefit,
            "risk_level": self.risk_level.value,
            "affected_scope": list(self.affected_scope),
            "test_plan": list(self.test_plan),
            "evidence_ids": list(self.evidence_ids),
            "candidate_hash": self.candidate_hash,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvolutionCandidate":
        return cls(
            id=str(data["id"]),
            status=CandidateStatus(str(data["status"])),
            title=str(data["title"]),
            rationale=str(data["rationale"]),
            proposed_change=str(data["proposed_change"]),
            expected_benefit=str(data["expected_benefit"]),
            risk_level=RiskLevel(str(data["risk_level"])),
            affected_scope=tuple(str(x) for x in data.get("affected_scope", [])),
            test_plan=tuple(str(x) for x in data.get("test_plan", [])),
            evidence_ids=tuple(str(x) for x in data.get("evidence_ids", [])),
            candidate_hash=str(data["candidate_hash"]),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )


@dataclass(frozen=True)
class CurationResult:
    candidate_id: str
    status: CandidateStatus
    risk_level: RiskLevel
    reasons: tuple[str, ...]
