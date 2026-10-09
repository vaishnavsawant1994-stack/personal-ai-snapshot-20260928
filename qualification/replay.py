from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ReplayCase:
    id: str
    tool_name: str
    capability: str
    description: str
    input_descriptor: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.tool_name.strip() or not self.capability.strip():
            raise ValueError("replay case id, tool_name, and capability are required")


@dataclass(frozen=True)
class ReplayResult:
    id: str
    case_id: str
    tool_name: str
    capability: str
    exact_head_sha: str
    passed: bool
    input_hash: str
    output_hash: str
    verifier: str
    evidence_refs: tuple[str, ...] = ()
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        for label, value in (
            ("replay id", self.id),
            ("case id", self.case_id),
            ("tool_name", self.tool_name),
            ("capability", self.capability),
            ("exact_head_sha", self.exact_head_sha),
            ("input_hash", self.input_hash),
            ("output_hash", self.output_hash),
            ("verifier", self.verifier),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "tool_name": self.tool_name,
            "capability": self.capability,
            "exact_head_sha": self.exact_head_sha,
            "passed": self.passed,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "verifier": self.verifier,
            "evidence_refs": list(self.evidence_refs),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReplayResult":
        return cls(
            id=str(data["id"]),
            case_id=str(data["case_id"]),
            tool_name=str(data["tool_name"]),
            capability=str(data["capability"]),
            exact_head_sha=str(data["exact_head_sha"]),
            passed=bool(data["passed"]),
            input_hash=str(data["input_hash"]),
            output_hash=str(data["output_hash"]),
            verifier=str(data["verifier"]),
            evidence_refs=tuple(str(x) for x in data.get("evidence_refs", [])),
            created_at=str(data.get("created_at") or _now()),
        )


class ReplayStore:
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
                CREATE TABLE IF NOT EXISTS capability_replays(
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    exact_head_sha TEXT NOT NULL,
                    passed INTEGER NOT NULL CHECK(passed IN (0,1)),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_capability_replays_tool_head ON capability_replays(tool_name,exact_head_sha,passed,created_at)"
            )

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def record(self, result: ReplayResult) -> ReplayResult:
        payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO capability_replays(id,case_id,tool_name,capability,exact_head_sha,passed,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET passed=excluded.passed,payload_json=excluded.payload_json
                """,
                (
                    result.id,
                    result.case_id,
                    result.tool_name,
                    result.capability,
                    result.exact_head_sha,
                    int(result.passed),
                    payload,
                    result.created_at,
                ),
            )
        return result

    def successful(self, tool_name: str, *, exact_head_sha: str | None = None) -> list[ReplayResult]:
        sql = "SELECT payload_json FROM capability_replays WHERE tool_name=? AND passed=1"
        params: list[Any] = [str(tool_name)]
        if exact_head_sha is not None:
            sql += " AND exact_head_sha=?"
            params.append(str(exact_head_sha))
        sql += " ORDER BY created_at,id"
        with self.lock:
            rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [ReplayResult.from_dict(json.loads(row[0])) for row in rows]

    def all_for_tool(self, tool_name: str) -> list[ReplayResult]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload_json FROM capability_replays WHERE tool_name=? ORDER BY created_at,id",
                (str(tool_name),),
            ).fetchall()
        return [ReplayResult.from_dict(json.loads(row[0])) for row in rows]


class ReplayRunner:
    """Qualification-only deterministic replay helper.

    Raw inputs and outputs are not persisted. Only hashes, pass/fail state and explicit
    evidence references are recorded, preventing qualification logs from becoming a
    duplicate secret store.
    """

    def __init__(self, store: ReplayStore) -> None:
        self.store = store

    def run(
        self,
        case: ReplayCase,
        *,
        exact_head_sha: str,
        invoke: Callable[[], Any],
        verify: Callable[[Any], bool],
        verifier: str = "deterministic",
        evidence_refs: tuple[str, ...] = (),
    ) -> ReplayResult:
        exact_head_sha = str(exact_head_sha or "").strip()
        if not exact_head_sha:
            raise ValueError("exact_head_sha is required for qualification replay")
        output = invoke()
        passed = bool(verify(output))
        result = ReplayResult(
            id=str(uuid.uuid4()),
            case_id=case.id,
            tool_name=case.tool_name,
            capability=case.capability,
            exact_head_sha=exact_head_sha,
            passed=passed,
            input_hash=_hash(dict(case.input_descriptor)),
            output_hash=_hash(output),
            verifier=str(verifier or "deterministic")[:200],
            evidence_refs=tuple(dict.fromkeys((*case.evidence_refs, *evidence_refs)))[:100],
        )
        return self.store.record(result)
