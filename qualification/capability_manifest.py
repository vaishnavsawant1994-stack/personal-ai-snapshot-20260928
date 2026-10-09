from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .claims import (
    CapabilityClaim,
    CapabilityClaimGate,
    CapabilityClaimState,
    CapabilityClaimStore,
)
from .replay import ReplayResult, ReplayStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QualificationState(StrEnum):
    AVAILABLE = "available"
    QUALIFIED = "qualified"
    EXPERIMENTAL = "experimental"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True)
class CapabilityManifestEntry:
    tool_name: str
    capability: str
    state: QualificationState
    exact_head_sha: str | None = None
    qualification_suite: str | None = None
    replay_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    qualified_at: str | None = None
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.tool_name.strip() or not self.capability.strip():
            raise ValueError("tool_name and capability are required")
        if self.state is QualificationState.QUALIFIED:
            if not self.exact_head_sha or not self.qualification_suite or not self.replay_ids or not self.evidence_refs:
                raise ValueError("qualified capability requires exact-head suite, replay ids, and evidence refs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "capability": self.capability,
            "state": self.state.value,
            "exact_head_sha": self.exact_head_sha,
            "qualification_suite": self.qualification_suite,
            "replay_ids": list(self.replay_ids),
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "qualified_at": self.qualified_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapabilityManifestEntry":
        return cls(
            tool_name=str(data["tool_name"]),
            capability=str(data["capability"]),
            state=QualificationState(str(data["state"])),
            exact_head_sha=data.get("exact_head_sha"),
            qualification_suite=data.get("qualification_suite"),
            replay_ids=tuple(str(x) for x in data.get("replay_ids", [])),
            evidence_refs=tuple(str(x) for x in data.get("evidence_refs", [])),
            reason=str(data.get("reason") or ""),
            qualified_at=data.get("qualified_at"),
            updated_at=str(data.get("updated_at") or _now()),
        )


class CapabilityQualificationStore:
    """Durable qualification manifest over capability metadata.

    This store never authorizes execution. It only records evidence-backed confidence
    about a capability. ToolRegistry and its policy/permission/approval gates remain
    authoritative even when a capability is marked QUALIFIED.
    """

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
                CREATE TABLE IF NOT EXISTS capability_qualification_manifest(
                    tool_name TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_manifest_state ON capability_qualification_manifest(state,updated_at)"
            )
        self.replays = ReplayStore(connection=self.connection, lock=self.lock)
        self.claims = CapabilityClaimStore(connection=self.connection, lock=self.lock)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def _save(self, entry: CapabilityManifestEntry) -> CapabilityManifestEntry:
        payload = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO capability_qualification_manifest(tool_name,capability,state,payload_json,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(tool_name) DO UPDATE SET capability=excluded.capability,state=excluded.state,payload_json=excluded.payload_json,updated_at=excluded.updated_at
                """,
                (entry.tool_name, entry.capability, entry.state.value, payload, entry.updated_at),
            )
        return entry

    def set_nonqualified_state(
        self,
        tool_name: str,
        capability: str,
        state: QualificationState | str,
        *,
        reason: str = "",
    ) -> CapabilityManifestEntry:
        state = state if isinstance(state, QualificationState) else QualificationState(str(state))
        if state is QualificationState.QUALIFIED:
            raise ValueError("QUALIFIED can only be set through promote_claim")
        return self._save(
            CapabilityManifestEntry(
                tool_name=str(tool_name),
                capability=str(capability),
                state=state,
                reason=str(reason)[:1000],
            )
        )

    def record_replay(self, result: ReplayResult) -> ReplayResult:
        return self.replays.record(result)

    def create_claim(
        self,
        *,
        tool_name: str,
        capability: str,
        exact_head_sha: str,
        qualification_suite: str,
        required_replay_count: int = 1,
        evidence_refs: tuple[str, ...] = (),
    ) -> CapabilityClaim:
        return self.claims.create(
            tool_name=tool_name,
            capability=capability,
            exact_head_sha=exact_head_sha,
            qualification_suite=qualification_suite,
            required_replay_count=required_replay_count,
            evidence_refs=evidence_refs,
        )

    def promote_claim(self, claim_id: str) -> CapabilityManifestEntry:
        claim = self.claims.get(claim_id)
        if claim is None:
            raise KeyError(claim_id)
        replays = self.replays.successful(claim.tool_name, exact_head_sha=claim.exact_head_sha)
        decision = CapabilityClaimGate.evaluate(claim, replays)
        self.claims.update_state(claim.id, decision.state)
        if not decision.passed:
            raise RuntimeError("capability qualification claim is not satisfied: " + "; ".join(decision.reasons))
        stamp = _now()
        entry = CapabilityManifestEntry(
            tool_name=claim.tool_name,
            capability=claim.capability,
            state=QualificationState.QUALIFIED,
            exact_head_sha=claim.exact_head_sha,
            qualification_suite=claim.qualification_suite,
            replay_ids=decision.replay_ids,
            evidence_refs=decision.evidence_refs,
            reason="exact-head qualification claim passed deterministic replay gate",
            qualified_at=stamp,
            updated_at=stamp,
        )
        return self._save(entry)

    def get(self, tool_name: str) -> CapabilityManifestEntry | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM capability_qualification_manifest WHERE tool_name=?",
                (str(tool_name),),
            ).fetchone()
        return CapabilityManifestEntry.from_dict(json.loads(row[0])) if row else None

    def all(self) -> tuple[CapabilityManifestEntry, ...]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload_json FROM capability_qualification_manifest ORDER BY tool_name"
            ).fetchall()
        return tuple(CapabilityManifestEntry.from_dict(json.loads(row[0])) for row in rows)

    def manifest_map(self) -> dict[str, dict[str, Any]]:
        return {entry.tool_name: entry.to_dict() for entry in self.all()}

    def status(self) -> dict[str, Any]:
        counts = {state.value: 0 for state in QualificationState}
        entries = self.all()
        for entry in entries:
            counts[entry.state.value] += 1
        return {
            "entries": len(entries),
            "states": counts,
            "authority": "qualification_metadata_only",
            "qualified_requires": "exact_head_replay_and_evidence",
        }
