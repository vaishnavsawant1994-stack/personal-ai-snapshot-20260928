from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class BodyRevisionStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


def _stable_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class BodyManifest:
    """Versioned declaration of Vishnu's governed software-body contracts.

    The manifest describes the body. It is not itself the whole body: source,
    tests, schemas, migrations, policy and capability implementations remain
    part of the governed software body and are identified by a Git revision.
    """

    body_version: int
    identity: dict[str, str]
    contracts: dict[str, int]
    mission: tuple[str, ...]
    principles: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BodyManifest":
        if not isinstance(data, dict):
            raise ValueError("body manifest must be an object")
        body_version = data.get("body_version")
        if not isinstance(body_version, int) or body_version < 1:
            raise ValueError("body_version must be a positive integer")

        identity = data.get("identity")
        if not isinstance(identity, dict):
            raise ValueError("identity must be an object")
        name = str(identity.get("name") or "").strip()
        role = str(identity.get("role") or "").strip()
        if not name or not role:
            raise ValueError("identity.name and identity.role are required")
        normalized_identity = {str(k): str(v) for k, v in identity.items()}

        contracts = data.get("contracts")
        if not isinstance(contracts, dict) or not contracts:
            raise ValueError("contracts must be a non-empty object")
        normalized_contracts: dict[str, int] = {}
        for key, value in contracts.items():
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"contract version for {key!r} must be a positive integer")
            normalized_contracts[str(key)] = value

        mission = cls._string_tuple(data.get("mission"), field="mission", required=True)
        principles = cls._string_tuple(data.get("principles", ()), field="principles", required=False)
        return cls(
            body_version=body_version,
            identity=normalized_identity,
            contracts=normalized_contracts,
            mission=mission,
            principles=principles,
        )

    @staticmethod
    def _string_tuple(value: Any, *, field: str, required: bool) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{field} must be a list")
        items = tuple(str(item).strip() for item in value if str(item).strip())
        if required and not items:
            raise ValueError(f"{field} must not be empty")
        return items

    @classmethod
    def load(cls, path: str | Path) -> "BodyManifest":
        """Load the manifest from JSON-compatible YAML.

        JSON is a YAML 1.2 subset, so the repository keeps the .yaml contract
        without adding a YAML runtime dependency to Vishnu's core.
        """

        raw = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("body manifest must use JSON-compatible YAML") from exc
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_version": self.body_version,
            "identity": dict(self.identity),
            "contracts": dict(self.contracts),
            "mission": list(self.mission),
            "principles": list(self.principles),
        }

    @property
    def manifest_hash(self) -> str:
        return hashlib.sha256(_stable_json(self.to_dict()).encode("utf-8")).hexdigest()

    @property
    def revision_id(self) -> str:
        return f"body-v{self.body_version}-{self.manifest_hash[:16]}"
