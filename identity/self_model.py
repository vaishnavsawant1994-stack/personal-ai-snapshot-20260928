from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


class SelfAuthorityViolation(ValueError):
    """Raised when private Self data attempts to encode execution authority."""


# Private Self can shape behavior and relationship continuity, but it is never
# an authorization source. Keep this deliberately explicit and conservative.
_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "admin",
        "authorization",
        "bypass_approval",
        "capability_grants",
        "continuation_authority",
        "evolution_mode",
        "merge_authority",
        "permissions",
        "security_policy",
        "tool_permissions",
        "auto_deploy",
        "auto_merge",
    }
)


def _normalize_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _validate_no_authority(value: Any, *, path: str = "self") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in _FORBIDDEN_AUTHORITY_KEYS:
                raise SelfAuthorityViolation(
                    f"private Self cannot define authority at {path}.{key}; "
                    "use Vishnu permissions/approval policy instead"
                )
            _validate_no_authority(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_no_authority(child, path=f"{path}[{index}]")


def _stable_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class SelfProfile:
    """Private, portable relationship/personality state with no authority power."""

    schema_version: int = 1
    owner_relationship: dict[str, Any] = field(default_factory=dict)
    communication_style: dict[str, Any] = field(default_factory=dict)
    personality: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    private_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Self schema version")
        _validate_no_authority(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelfProfile":
        if not isinstance(data, dict):
            raise ValueError("Self profile must be an object")
        allowed = {
            "schema_version",
            "owner_relationship",
            "communication_style",
            "personality",
            "preferences",
            "private_context",
            "metadata",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"unknown Self fields: {', '.join(sorted(unknown))}")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            owner_relationship=dict(data.get("owner_relationship") or {}),
            communication_style=dict(data.get("communication_style") or {}),
            personality=dict(data.get("personality") or {}),
            preferences=dict(data.get("preferences") or {}),
            private_context=dict(data.get("private_context") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_relationship": dict(self.owner_relationship),
            "communication_style": dict(self.communication_style),
            "personality": dict(self.personality),
            "preferences": dict(self.preferences),
            "private_context": dict(self.private_context),
            "metadata": dict(self.metadata),
        }

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(_stable_json(self.to_dict()).encode("utf-8")).hexdigest()
