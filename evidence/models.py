from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceProvenance(StrEnum):
    MODEL_ONLY = "model_only"
    CONTEXT = "context"
    OBSERVED = "observed"
    TOOL_VERIFIED = "tool_verified"
    EXTERNALLY_VERIFIED = "externally_verified"
    REPLAYABLE = "replayable"

    @property
    def rank(self) -> int:
        return {
            EvidenceProvenance.MODEL_ONLY: 0,
            EvidenceProvenance.CONTEXT: 1,
            EvidenceProvenance.OBSERVED: 2,
            EvidenceProvenance.TOOL_VERIFIED: 3,
            EvidenceProvenance.EXTERNALLY_VERIFIED: 4,
            EvidenceProvenance.REPLAYABLE: 5,
        }[self]


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DISPUTED = "disputed"


class ClaimState(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    REJECTED = "rejected"


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True)
class Evidence:
    id: str
    source_type: str
    source: str
    subject: str
    observation: str
    provenance: EvidenceProvenance
    project_id: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    work_order_id: str | None = None
    worker_run_id: str | None = None
    tool_name: str | None = None
    artifact_ref: str | None = None
    artifact_hash: str | None = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    verification_reason: str | None = None
    confidence: float = 0.0
    data_classification: str = "internal"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence id", self.id),
            ("source_type", self.source_type),
            ("source", self.source),
            ("subject", self.subject),
            ("observation", self.observation),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "work_order_id": self.work_order_id,
            "worker_run_id": self.worker_run_id,
            "tool_name": self.tool_name,
            "source_type": self.source_type,
            "source": self.source,
            "subject": self.subject,
            "observation": self.observation,
            "artifact_ref": self.artifact_ref,
            "artifact_hash": self.artifact_hash,
            "provenance": self.provenance.value,
            "verification_state": self.verification_state.value,
            "verification_reason": self.verification_reason,
            "confidence": self.confidence,
            "data_classification": self.data_classification,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Evidence":
        return cls(
            id=str(data["id"]),
            project_id=data.get("project_id"),
            goal_id=data.get("goal_id"),
            plan_id=data.get("plan_id"),
            work_order_id=data.get("work_order_id"),
            worker_run_id=data.get("worker_run_id"),
            tool_name=data.get("tool_name"),
            source_type=str(data["source_type"]),
            source=str(data["source"]),
            subject=str(data["subject"]),
            observation=str(data["observation"]),
            artifact_ref=data.get("artifact_ref"),
            artifact_hash=data.get("artifact_hash"),
            provenance=EvidenceProvenance(str(data["provenance"])),
            verification_state=VerificationState(str(data.get("verification_state", VerificationState.UNVERIFIED.value))),
            verification_reason=data.get("verification_reason"),
            confidence=float(data.get("confidence", 0.0)),
            data_classification=str(data.get("data_classification", "internal")),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class Receipt:
    id: str
    operation: str
    execution_id: str
    tool: str
    destination: str
    request_hash: str
    remote_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    verified: bool = False
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        for label, value in (
            ("receipt id", self.id),
            ("operation", self.operation),
            ("execution_id", self.execution_id),
            ("tool", self.tool),
            ("destination", self.destination),
            ("request_hash", self.request_hash),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "execution_id": self.execution_id,
            "tool": self.tool,
            "destination": self.destination,
            "request_hash": self.request_hash,
            "remote_id": self.remote_id,
            "details": dict(self.details),
            "verified": self.verified,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Receipt":
        return cls(
            id=str(data["id"]),
            operation=str(data["operation"]),
            execution_id=str(data["execution_id"]),
            tool=str(data["tool"]),
            destination=str(data["destination"]),
            request_hash=str(data["request_hash"]),
            remote_id=data.get("remote_id"),
            details=_mapping(data.get("details")),
            verified=bool(data.get("verified", False)),
            created_at=str(data.get("created_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    project_id: str | None = None
    work_order_id: str | None = None
    state: ClaimState = ClaimState.PROPOSED
    confidence: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.text.strip():
            raise ValueError("claim id and text are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "work_order_id": self.work_order_id,
            "text": self.text,
            "state": self.state.value,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Claim":
        return cls(
            id=str(data["id"]),
            project_id=data.get("project_id"),
            work_order_id=data.get("work_order_id"),
            text=str(data["text"]),
            state=ClaimState(str(data.get("state", ClaimState.PROPOSED.value))),
            confidence=float(data.get("confidence", 0.0)),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )
