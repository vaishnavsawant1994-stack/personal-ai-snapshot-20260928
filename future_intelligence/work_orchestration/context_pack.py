from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping


SENSITIVE_KEYS = {
    "token", "password", "secret", "authorization", "cookie", "api_key",
    "apikey", "credential", "private_key", "access_key", "refresh_token",
    "approval_token", "raw_context",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any, *, depth: int = 0, max_depth: int = 5, max_items: int = 30, max_text: int = 800) -> Any:
    if depth >= max_depth:
        return "[bounded]"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, nested in list(value.items())[:max_items]:
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS or any(normalized.endswith("_" + marker) for marker in SENSITIVE_KEYS):
                continue
            out[str(key)[:100]] = _safe(
                nested, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_text=max_text
            )
        return out
    if isinstance(value, (list, tuple, set)):
        return [
            _safe(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_text=max_text)
            for item in list(value)[:max_items]
        ]
    if isinstance(value, str):
        return value[:max_text]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:max_text]


@dataclass(frozen=True)
class ContextEntry:
    kind: str
    source_id: str
    text: str
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_id": self.source_id,
            "text": self.text,
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ContextPack:
    goal_id: str
    query: str
    project_id: str | None = None
    memory: tuple[ContextEntry, ...] = ()
    knowledge: tuple[ContextEntry, ...] = ()
    project: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[ContextEntry, ...] = ()
    recent_results: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    created_at: str = field(default_factory=_now)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.goal_id.strip():
            raise ValueError("goal_id is required")
        if not self.query.strip():
            raise ValueError("context query is required")
        if not self.fingerprint:
            payload = self._payload(include_fingerprint=False)
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "fingerprint", digest)

    def _payload(self, *, include_fingerprint: bool) -> dict[str, Any]:
        payload = {
            "goal_id": self.goal_id,
            "query": self.query,
            "project_id": self.project_id,
            "memory": [item.to_dict() for item in self.memory],
            "knowledge": [item.to_dict() for item in self.knowledge],
            "project": dict(self.project),
            "evidence": [item.to_dict() for item in self.evidence],
            "recent_results": [dict(item) for item in self.recent_results],
            "blockers": list(self.blockers),
            "available_tools": list(self.available_tools),
            "created_at": self.created_at,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload(include_fingerprint=True)

    def prompt_text(self, *, max_chars: int = 12000) -> str:
        safe = self.to_dict()
        safe.pop("fingerprint", None)
        return json.dumps(safe, sort_keys=True, default=str)[: max(1000, min(int(max_chars), 50000))]


class ContextPackBuilder:
    """Build a bounded, privacy-aware strategic context snapshot.

    Providers are optional and advisory. Failures never grant authority or block
    the existing runtime; they only reduce the available planning context.
    """

    def __init__(
        self,
        *,
        memory=None,
        knowledge=None,
        project_store=None,
        evidence_store=None,
        max_memory: int = 8,
        max_knowledge: int = 8,
        max_evidence: int = 12,
    ) -> None:
        self.memory = memory
        self.knowledge = knowledge
        self.project_store = project_store
        self.evidence_store = evidence_store
        self.max_memory = max(0, min(int(max_memory), 20))
        self.max_knowledge = max(0, min(int(max_knowledge), 20))
        self.max_evidence = max(0, min(int(max_evidence), 30))

    @staticmethod
    def _rows(provider, query: str, limit: int, *, project_id: str | None = None) -> list[dict[str, Any]]:
        if provider is None or limit <= 0:
            return []
        search = getattr(provider, "search", None)
        if search is None:
            store = getattr(provider, "store", None)
            search = getattr(store, "search", None) if store is not None else None
        if search is None:
            return []
        try:
            try:
                rows = search(query, limit=limit, project_id=project_id)
            except TypeError:
                rows = search(query, limit=limit)
        except Exception:
            return []
        return [dict(item) for item in list(rows or [])[:limit] if isinstance(item, Mapping)]

    @staticmethod
    def _memory_entries(rows: Iterable[Mapping[str, Any]]) -> tuple[ContextEntry, ...]:
        entries: list[ContextEntry] = []
        for index, row in enumerate(rows):
            clean = _safe(dict(row))
            text = str(clean.get("content") or clean.get("excerpt") or clean.get("subject") or "")[:800]
            if not text:
                continue
            entries.append(
                ContextEntry(
                    kind="memory",
                    source_id=str(clean.get("id") or f"memory-{index + 1}")[:200],
                    text=text,
                    score=float(clean["score"]) if isinstance(clean.get("score"), (int, float)) else None,
                    metadata={
                        key: clean[key]
                        for key in ("type", "subject", "source", "confidence", "verified", "sensitivity")
                        if key in clean
                    },
                )
            )
        return tuple(entries)

    @staticmethod
    def _knowledge_entries(rows: Iterable[Mapping[str, Any]]) -> tuple[ContextEntry, ...]:
        entries: list[ContextEntry] = []
        for index, row in enumerate(rows):
            clean = _safe(dict(row))
            text = str(clean.get("excerpt") or clean.get("content") or "")[:800]
            if not text:
                continue
            entries.append(
                ContextEntry(
                    kind="knowledge",
                    source_id=str(clean.get("chunk_id") or clean.get("document_id") or f"knowledge-{index + 1}")[:200],
                    text=text,
                    score=float(clean["score"]) if isinstance(clean.get("score"), (int, float)) else None,
                    metadata={
                        key: clean[key]
                        for key in ("document_id", "title", "source", "version", "citation", "access_class")
                        if key in clean
                    },
                )
            )
        return tuple(entries)

    def _project(self, project_id: str | None) -> Mapping[str, Any]:
        if not project_id or self.project_store is None:
            return {}
        getter = getattr(self.project_store, "get", None)
        if getter is None:
            return {}
        try:
            project = getter(project_id)
        except Exception:
            return {}
        if not isinstance(project, Mapping):
            return {}
        clean = _safe(dict(project), max_depth=4, max_items=40, max_text=600)
        return clean if isinstance(clean, Mapping) else {}

    def _evidence(self, project_id: str | None) -> tuple[ContextEntry, ...]:
        if self.evidence_store is None or self.max_evidence <= 0:
            return ()
        try:
            rows = self.evidence_store.list_evidence(project_id=project_id) if project_id else []
        except Exception:
            return ()
        entries: list[ContextEntry] = []
        for item in list(rows)[-self.max_evidence :]:
            data = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            clean = _safe(data)
            entries.append(
                ContextEntry(
                    kind="evidence",
                    source_id=str(clean.get("id") or "")[:200],
                    text=str(clean.get("observation") or "")[:800],
                    metadata={
                        key: clean[key]
                        for key in ("provenance", "verification_state", "source_type", "work_order_id")
                        if key in clean
                    },
                )
            )
        return tuple(entry for entry in entries if entry.source_id and entry.text)

    def build(
        self,
        *,
        goal_id: str,
        query: str,
        project_id: str | None = None,
        available_tools: Iterable[str] = (),
        recent_results: Iterable[Mapping[str, Any]] = (),
        blockers: Iterable[str] = (),
    ) -> ContextPack:
        memory_rows = self._rows(self.memory, query, self.max_memory, project_id=project_id)
        knowledge_rows = self._rows(self.knowledge, query, self.max_knowledge, project_id=project_id)
        return ContextPack(
            goal_id=str(goal_id),
            query=str(query)[:2000],
            project_id=project_id,
            memory=self._memory_entries(memory_rows),
            knowledge=self._knowledge_entries(knowledge_rows),
            project=self._project(project_id),
            evidence=self._evidence(project_id),
            recent_results=tuple(
                _safe(dict(item), max_depth=4, max_items=20, max_text=500)
                for item in list(recent_results)[:20]
                if isinstance(item, Mapping)
            ),
            blockers=tuple(str(item)[:500] for item in list(blockers)[:20]),
            available_tools=tuple(dict.fromkeys(str(item)[:200] for item in available_tools if str(item).strip()))[:100],
        )
