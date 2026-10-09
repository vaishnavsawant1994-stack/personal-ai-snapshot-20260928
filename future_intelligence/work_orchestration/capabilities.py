from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Iterable, Mapping


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    QUALIFIED = "qualified"
    EXPERIMENTAL = "experimental"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


_ACTIVE_STATES = {
    CapabilityState.AVAILABLE,
    CapabilityState.QUALIFIED,
    CapabilityState.EXPERIMENTAL,
    CapabilityState.DEGRADED,
}
_PLANNING_MODES = {"strict", "assisted", "experimental"}


def normalize_capability(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", ".", str(value or "").strip().lower()).strip(".")
    return text[:200]


def capability_tokens(*values: Any) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        normalized = normalize_capability(value)
        if not normalized:
            continue
        found.append(normalized)
        found.extend(part for part in normalized.split(".") if part)
    return tuple(dict.fromkeys(found))


@dataclass(frozen=True)
class CapabilityRecord:
    id: str
    tool_name: str
    description: str = ""
    capability: str = ""
    connector_id: str | None = None
    state: CapabilityState = CapabilityState.AVAILABLE
    risk: int = 0
    verification_required: bool = False
    requires_reauth: bool = False
    allowed_destinations: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    exact_head_sha: str | None = None
    qualification_suite: str | None = None
    qualification_evidence: tuple[str, ...] = ()
    qualified_at: str | None = None
    requirements: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    failure_reason: str = ""

    @property
    def available(self) -> bool:
        """Compatibility visibility, not planner/execution authority."""
        return self.state in _ACTIVE_STATES

    def matches(self, requirement: str) -> bool:
        wanted = normalize_capability(requirement)
        if not wanted:
            return False
        aliases = set(capability_tokens(self.tool_name, self.capability, self.connector_id, *self.tags))
        return wanted in aliases

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "description": self.description,
            "capability": self.capability,
            "connector_id": self.connector_id,
            "state": self.state.value,
            "risk": self.risk,
            "verification_required": self.verification_required,
            "requires_reauth": self.requires_reauth,
            "allowed_destinations": list(self.allowed_destinations),
            "tags": list(self.tags),
            "exact_head_sha": self.exact_head_sha,
            "qualified_commit": self.exact_head_sha,
            "qualified_at": self.qualified_at,
            "qualification_suite": self.qualification_suite,
            "qualification_evidence": list(self.qualification_evidence),
            "requirements": list(self.requirements),
            "provider": self.connector_id,
            "fallbacks": list(self.fallbacks),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class CapabilityPlannerSelection:
    mode: str
    selected_tools: tuple[str, ...]
    degraded_tools: tuple[str, ...]
    excluded_tools: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "selected_tools": list(self.selected_tools),
            "degraded_tools": list(self.degraded_tools),
            "excluded_tools": list(self.excluded_tools),
            "warnings": list(self.warnings),
            "authority": "planning_filter_only",
        }


class CapabilityRegistry:
    """Read-only capability projection over the existing ToolRegistry.

    It never authorizes or executes. ToolRegistry/PermissionEngine remain the final
    policy, risk, approval, destination and verification authorities. Qualification
    metadata may strengthen or disable the planning view but never grants authority.
    """

    def __init__(self, records: Iterable[CapabilityRecord] = (), *, source_available: bool = True) -> None:
        self.source_available = bool(source_available)
        self._records = tuple(records)
        self._by_tool = {record.tool_name: record for record in self._records}

    @classmethod
    def unavailable(cls) -> "CapabilityRegistry":
        return cls((), source_available=False)

    @classmethod
    def from_tool_registry(
        cls,
        registry,
        *,
        qualification_manifest: Mapping[str, Any] | None = None,
    ) -> "CapabilityRegistry":
        if registry is None or not hasattr(registry, "all"):
            return cls.unavailable()
        try:
            tools = list(registry.all())
        except Exception:
            return cls.unavailable()
        records: list[CapabilityRecord] = []
        valid_states = {state.value: state for state in CapabilityState}
        manifest = dict(qualification_manifest or {})
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name:
                continue
            capability = str(getattr(tool, "capability", None) or name).strip()[:200]
            connector_id = getattr(tool, "connector_id", None)
            prohibited = bool(getattr(tool, "prohibited", False))
            raw_state = str(
                getattr(tool, "qualification_state", None)
                or getattr(tool, "availability_state", None)
                or "available"
            ).strip().lower()
            state = valid_states.get(raw_state, CapabilityState.AVAILABLE)
            exact_head_sha = None
            qualified_at = None
            qualification_suite = None
            qualification_evidence: tuple[str, ...] = ()
            requirements: tuple[str, ...] = ()
            fallbacks: tuple[str, ...] = ()
            failure_reason = ""
            overlay = manifest.get(name)
            if isinstance(overlay, Mapping):
                manifest_capability = normalize_capability(overlay.get("capability"))
                current_capability = normalize_capability(capability)
                if not manifest_capability or manifest_capability == current_capability:
                    manifest_state = str(overlay.get("state") or "").strip().lower()
                    if manifest_state in valid_states:
                        state = valid_states[manifest_state]
                    exact_head_sha = str(overlay.get("qualified_commit") or overlay.get("exact_head_sha") or "").strip() or None
                    qualified_at = str(overlay.get("qualified_at") or "").strip() or None
                    qualification_suite = str(overlay.get("qualification_suite") or "").strip() or None
                    qualification_evidence = tuple(
                        str(item)[:500]
                        for item in overlay.get("evidence_refs", overlay.get("qualification_evidence", []))
                        if str(item).strip()
                    )[:100]
                    requirements = tuple(str(item)[:500] for item in overlay.get("requirements", []) if str(item).strip())[:100]
                    fallbacks = tuple(str(item)[:200] for item in overlay.get("fallbacks", []) if str(item).strip())[:50]
                    failure_reason = str(overlay.get("failure_reason") or overlay.get("reason") or "")[:1000]
            if prohibited:
                state = CapabilityState.DISABLED
                exact_head_sha = None
                qualified_at = None
                qualification_suite = None
                qualification_evidence = ()
                requirements = ()
                fallbacks = ()
                failure_reason = "tool is prohibited by the canonical ToolRegistry"
            records.append(
                CapabilityRecord(
                    id=f"tool:{name}",
                    tool_name=name,
                    description=str(getattr(tool, "description", "") or "")[:1000],
                    capability=capability,
                    connector_id=str(connector_id)[:200] if connector_id else None,
                    state=state,
                    risk=int(getattr(tool, "risk", 0) or 0),
                    verification_required=bool(getattr(tool, "verification_required", False)),
                    requires_reauth=bool(getattr(tool, "requires_reauth", False)),
                    allowed_destinations=tuple(str(item)[:500] for item in (getattr(tool, "allowed_destinations", None) or ())),
                    tags=capability_tokens(name, capability, connector_id),
                    exact_head_sha=exact_head_sha,
                    qualification_suite=qualification_suite,
                    qualification_evidence=qualification_evidence,
                    qualified_at=qualified_at,
                    requirements=requirements,
                    fallbacks=fallbacks,
                    failure_reason=failure_reason,
                )
            )
        return cls(records, source_available=True)

    def all(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    def available(self) -> tuple[CapabilityRecord, ...]:
        return tuple(record for record in self._records if record.available)

    def available_tool_names(self) -> tuple[str, ...]:
        """Legacy visibility helper; callers needing planner policy use planner_selection."""
        return tuple(record.tool_name for record in self.available())

    def planner_selection(self, *, mode: str = "assisted") -> CapabilityPlannerSelection:
        normalized = str(mode or "assisted").strip().lower()
        if normalized not in _PLANNING_MODES:
            raise ValueError("capability planning mode must be strict, assisted, or experimental")
        selected: list[str] = []
        degraded: list[str] = []
        excluded: list[str] = []
        warnings: list[str] = []
        for record in self._records:
            if record.state is CapabilityState.QUALIFIED:
                selected.append(record.tool_name)
                continue
            if record.state is CapabilityState.AVAILABLE:
                if normalized in {"assisted", "experimental"}:
                    selected.append(record.tool_name)
                else:
                    excluded.append(record.tool_name)
                continue
            if record.state is CapabilityState.EXPERIMENTAL:
                if normalized == "experimental":
                    selected.append(record.tool_name)
                    warnings.append(f"{record.tool_name} is experimental and requires explicit experimental planning policy")
                else:
                    excluded.append(record.tool_name)
                continue
            if record.state is CapabilityState.DEGRADED:
                degraded.append(record.tool_name)
                excluded.append(record.tool_name)
                fallback = ", ".join(record.fallbacks) if record.fallbacks else "a qualified fallback"
                warnings.append(f"{record.tool_name} is degraded and excluded from primary selection; use {fallback}")
                continue
            excluded.append(record.tool_name)
        return CapabilityPlannerSelection(
            mode=normalized,
            selected_tools=tuple(dict.fromkeys(selected)),
            degraded_tools=tuple(dict.fromkeys(degraded)),
            excluded_tools=tuple(dict.fromkeys(excluded)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def planner_tool_names(self, *, mode: str = "assisted") -> tuple[str, ...]:
        return self.planner_selection(mode=mode).selected_tools

    def qualified(self) -> tuple[CapabilityRecord, ...]:
        return tuple(record for record in self._records if record.state is CapabilityState.QUALIFIED)

    def get_tool(self, tool_name: str) -> CapabilityRecord | None:
        return self._by_tool.get(str(tool_name))

    def match(self, requirement: str, *, available_only: bool = True) -> tuple[CapabilityRecord, ...]:
        pool = self.available() if available_only else self._records
        return tuple(record for record in pool if record.matches(requirement))

    def status(self) -> dict[str, Any]:
        counts = {state.value: 0 for state in CapabilityState}
        for record in self._records:
            counts[record.state.value] += 1
        return {
            "source_available": self.source_available,
            "total": len(self._records),
            "available": len(self.available()),
            "qualified": len(self.qualified()),
            "states": counts,
            "authority": "metadata_only",
            "execution_authority": "existing_tool_registry",
        }
