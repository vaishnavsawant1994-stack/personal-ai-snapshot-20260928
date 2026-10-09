from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable


class ProviderKind(StrEnum):
    REASONING = "reasoning"
    TOOL = "tool"
    REPOSITORY = "repository"
    REVIEW = "review"
    DEPLOYMENT = "deployment"
    STORAGE = "storage"
    NOTIFICATION = "notification"


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    kind: ProviderKind
    capabilities: tuple[str, ...] = ()
    authenticated: bool | None = None
    healthy: bool | None = None
    idempotency: str = "unknown"
    verification: str = "unknown"
    risk: str = "external"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.provider_id).strip():
            raise ValueError("provider_id is required")
        if self.idempotency not in {"none", "supported", "required", "unknown"}:
            raise ValueError("invalid idempotency declaration")
        if self.verification not in {"none", "self_reported", "independent", "required", "unknown"}:
            raise ValueError("invalid verification declaration")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind.value,
            "capabilities": list(self.capabilities),
            "authenticated": self.authenticated,
            "healthy": self.healthy,
            "idempotency": self.idempotency,
            "verification": self.verification,
            "risk": self.risk,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class CapabilityProvider(Protocol):
    def provider_capabilities(self) -> ProviderCapabilities: ...


@runtime_checkable
class ReasoningProvider(Protocol):
    def chat(self, *args, **kwargs): ...
    def json(self, *args, **kwargs): ...
    def embed(self, *args, **kwargs): ...


@runtime_checkable
class RepositoryProvider(Protocol):
    def prepare(self, *args, **kwargs): ...
    def commit(self, *args, **kwargs): ...


@runtime_checkable
class ReviewProvider(Protocol):
    def verify(self, *args, **kwargs): ...


@runtime_checkable
class NotificationProvider(Protocol):
    def send(self, *args, **kwargs): ...


class ProviderConformanceError(ValueError):
    pass


def require_methods(provider: Any, *methods: str, provider_id: str | None = None) -> None:
    missing = [name for name in methods if not callable(getattr(provider, name, None))]
    if missing:
        label = provider_id or type(provider).__name__
        raise ProviderConformanceError(f"provider {label} is missing required methods: {', '.join(missing)}")


def conformance_snapshot(provider: Any, *, kind: ProviderKind, provider_id: str | None = None) -> ProviderCapabilities:
    """Return a normalized capability declaration without granting authority.

    Providers may supply a richer `provider_capabilities()` method. Otherwise we
    derive a conservative structural snapshot. Authorization always remains in
    Vishnu's permissions/approval/runtime layers, never in this declaration.
    """
    explicit = getattr(provider, "provider_capabilities", None)
    if callable(explicit):
        value = explicit()
        if not isinstance(value, ProviderCapabilities):
            raise ProviderConformanceError("provider_capabilities must return ProviderCapabilities")
        if value.kind is not kind:
            raise ProviderConformanceError("provider capability kind mismatch")
        return value

    requirements = {
        ProviderKind.REASONING: ("chat", "json", "embed"),
        ProviderKind.TOOL: ("all", "authorize", "verify_result"),
        ProviderKind.REPOSITORY: ("prepare", "commit"),
        ProviderKind.REVIEW: ("verify",),
        ProviderKind.DEPLOYMENT: (),
        ProviderKind.STORAGE: (),
        ProviderKind.NOTIFICATION: (),
    }
    required = requirements[kind]
    if required:
        require_methods(provider, *required, provider_id=provider_id)
    capabilities = tuple(sorted(name for name in required if callable(getattr(provider, name, None))))
    return ProviderCapabilities(
        provider_id=str(provider_id or type(provider).__name__),
        kind=kind,
        capabilities=capabilities,
        authenticated=None,
        healthy=None,
        idempotency="unknown",
        verification="unknown",
        risk="external",
        metadata={"derived": True, "authorization_authority": False},
    )


def runtime_provider_inventory(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        ("models", ProviderKind.REASONING),
        ("tools", ProviderKind.TOOL),
        ("repository_provider", ProviderKind.REPOSITORY),
        ("notifications", ProviderKind.NOTIFICATION),
    )
    items = []
    for key, kind in candidates:
        provider = runtime.get(key)
        if provider is None:
            continue
        try:
            snapshot = conformance_snapshot(provider, kind=kind, provider_id=key)
            items.append({"key": key, "conformant": True, **snapshot.to_dict()})
        except Exception as exc:
            items.append({"key": key, "kind": kind.value, "conformant": False, "error_type": type(exc).__name__})
    return items
