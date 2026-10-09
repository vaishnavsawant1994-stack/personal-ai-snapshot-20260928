from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Iterable


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    QUALIFIED = "qualified"
    EXPERIMENTAL = "experimental"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


_ACTIVE_STATES = {
    CapabilityState.AVAILABLE,
    CapabilityState.QUALIFIED,
    CapabilityState.EXPERIMENTAL,
}


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

    @property
    def available(self) -> bool:
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
        }


class CapabilityRegistry:
    """Read-only capability projection over the existing ToolRegistry.

    It never authorizes or executes. ToolRegistry/PermissionEngine remain the final
    policy, risk, approval, destination and verification authorities.
    """

    def __init__(self, records: Iterable[CapabilityRecord] = (), *, source_available: bool = True) -> None:
        self.source_available = bool(source_available)
        self._records = tuple(records)
        self._by_tool = {record.tool_name: record for record in self._records}

    @classmethod
    def unavailable(cls) -> "CapabilityRegistry":
        return cls((), source_available=False)

    @classmethod
    def from_tool_registry(cls, registry) -> "CapabilityRegistry":
        if registry is None or not hasattr(registry, "all"):
            return cls.unavailable()
        try:
            tools = list(registry.all())
        except Exception:
            return cls.unavailable()
        records: list[CapabilityRecord] = []
        valid_states = {state.value: state for state in CapabilityState}
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name:
                continue
            prohibited = bool(getattr(tool, "prohibited", False))
            raw_state = str(
                getattr(tool, "qualification_state", None)
                or getattr(tool, "availability_state", None)
                or "available"
            ).strip().lower()
            state = CapabilityState.DISABLED if prohibited else valid_states.get(raw_state, CapabilityState.AVAILABLE)
            capability = str(getattr(tool, "capability", None) or name).strip()[:200]
            connector_id = getattr(tool, "connector_id", None)
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
                )
            )
        return cls(records, source_available=True)

    def all(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    def available(self) -> tuple[CapabilityRecord, ...]:
        return tuple(record for record in self._records if record.available)

    def available_tool_names(self) -> tuple[str, ...]:
        return tuple(record.tool_name for record in self.available())

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
            "states": counts,
            "authority": "metadata_only",
            "execution_authority": "existing_tool_registry",
        }
