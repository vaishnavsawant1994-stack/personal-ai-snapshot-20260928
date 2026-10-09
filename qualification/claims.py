from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
import sqlite3
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping

from .replay import ReplayResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityClaimState(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CapabilityClaim:
    id: str
    tool_name: str
    capability: str
    exact_head_sha: str
    qualification_suite: str
    required_replay_count: int = 1
    evidence_refs: tuple[str, ...] = ()
    state: CapabilityClaimState = CapabilityClaimState.PROPOSED
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        for label, value in (
            ("claim id", self.id),
            ("tool_name", self.tool_name),
            ("capability", self.capability),
            ("exact_head_sha", self.exact_head_sha),
            ("qualification_suite", self.qualification_suite),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
        if self.required_replay_count < 1:
            raise ValueError("required_replay_count must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "capability": self.capability,
            "exact_head_sha": self.exact_head_sha,
            "qualification_suite": self.qualification_suite,
            "required_replay_count": self.required_replay_count,
            "evidence_refs": list(self.evidence_refs),
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityClaim":
        return cls(
            id=str(data["id"]),
            tool_name=str(data["tool_name"]),
            capability=str(data["capability"]),
            exact_head_sha=str(data["exact_head_sha"]),
            qualification_suite=str(data["qualification_suite"]),
            required_replay_count=int(data.get("required_replay_count", 1)),
            evidence_refs=tuple(str(x) for x in data.get("evidence_refs", [])),
            state=CapabilityClaimState(str(data.get("state", CapabilityClaimState.PROPOSED.value))),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
        )


@dataclass(frozen=True)
class CapabilityClaimDecision:
    passed: bool
    state: CapabilityClaimState
    reasons: tuple[str, ...]
    replay_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "state": self.state.value,
            "reasons": list(self.reasons),
            "replay_ids": list(self.replay_ids),
            "evidence_refs": list(self.evidence_refs),
        }


class CapabilityClaimGate:
    """Deterministic gate for the strong `qualified` capability state."""

    @staticmethod
    def evaluate(claim: CapabilityClaim, replays: Iterable[ReplayResult]) -> CapabilityClaimDecision:
        if claim.state is CapabilityClaimState.REJECTED:
            return CapabilityClaimDecision(False, CapabilityClaimState.REJECTED, ("claim is rejected",))

        matching = [
            item
            for item in replays
            if item.passed
            and item.tool_name == claim.tool_name
            and item.capability == claim.capability
            and item.exact_head_sha == claim.exact_head_sha
        ]
        by_case: dict[str, ReplayResult] = {}
        for item in matching:
            by_case.setdefault(item.case_id, item)
        matching = list(by_case.values())
        replay_ids = tuple(item.id for item in matching)
        evidence = tuple(
            dict.fromkeys(
                (*claim.evidence_refs, *(ref for item in matching for ref in item.evidence_refs))
            )
        )
        reasons: list[str] = []
        if len(matching) < claim.required_replay_count:
            reasons.append(
                f"only {len(matching)} of {claim.required_replay_count} required exact-head replay case(s) passed"
            )
        if not evidence:
            reasons.append("no explicit qualification evidence reference is attached")
        if reasons:
            state = CapabilityClaimState.SUPPORTED if matching else CapabilityClaimState.PROPOSED
            return CapabilityClaimDecision(False, state, tuple(reasons), replay_ids, evidence)
        return CapabilityClaimDecision(
            True,
            CapabilityClaimState.QUALIFIED,
            ("exact-head replay and explicit qualification evidence satisfy the capability claim",),
            replay_ids,
            evidence,
        )


class CapabilityClaimStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
        lock: RLock | None = None,
    ) -> None:
        if db_path is not None and connection is not None:
            raise ValueError("provide db_path or connection, not both")
        self._owns_connection = connection is None
        self.connection = connection or sqlite3.connect(str(db_path or ":memory:"), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = lock or RLock()
        with self.lock, self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_claims(
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    exact_head_sha TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_claims_tool_head ON capability_claims(tool_name,exact_head_sha,state,updated_at)"
            )

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def create(
        self,
        *,
        tool_name: str,
        capability: str,
        exact_head_sha: str,
        qualification_suite: str,
        required_replay_count: int = 1,
        evidence_refs: tuple[str, ...] = (),
    ) -> CapabilityClaim:
        claim = CapabilityClaim(
            id=str(uuid.uuid4()),
            tool_name=str(tool_name),
            capability=str(capability),
            exact_head_sha=str(exact_head_sha),
            qualification_suite=str(qualification_suite),
            required_replay_count=int(required_replay_count),
            evidence_refs=tuple(dict.fromkeys(str(x) for x in evidence_refs if str(x).strip())),
        )
        return self.save(claim)

    def save(self, claim: CapabilityClaim) -> CapabilityClaim:
        payload = json.dumps(claim.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO capability_claims(id,tool_name,capability,exact_head_sha,state,payload_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload_json=excluded.payload_json,updated_at=excluded.updated_at
                """,
                (
                    claim.id,
                    claim.tool_name,
                    claim.capability,
                    claim.exact_head_sha,
                    claim.state.value,
                    payload,
                    claim.created_at,
                    claim.updated_at,
                ),
            )
        return claim

    def get(self, claim_id: str) -> CapabilityClaim | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM capability_claims WHERE id=?", (str(claim_id),)
            ).fetchone()
        return CapabilityClaim.from_dict(json.loads(row[0])) if row else None

    def update_state(self, claim_id: str, state: CapabilityClaimState) -> CapabilityClaim:
        claim = self.get(claim_id)
        if claim is None:
            raise KeyError(claim_id)
        updated = replace(claim, state=state, updated_at=_now())
        return self.save(updated)
