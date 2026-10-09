from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .body import BodyManifest
from .self_model import SelfProfile


@dataclass(frozen=True)
class IdentityContextEnvelope:
    """Provider-neutral identity context supplied to a reasoning runtime."""

    body: BodyManifest
    self_profile: SelfProfile | None
    active_body_revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": self.body.to_dict(),
            "self": self.self_profile.to_dict() if self.self_profile else None,
            "active_body_revision": self.active_body_revision,
        }


def compose_identity_context(
    body: BodyManifest,
    self_profile: SelfProfile | None,
    *,
    active_body_revision: str | None = None,
) -> IdentityContextEnvelope:
    return IdentityContextEnvelope(
        body=body,
        self_profile=self_profile,
        active_body_revision=active_body_revision,
    )
