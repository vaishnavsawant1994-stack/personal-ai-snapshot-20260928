from __future__ import annotations

from dataclasses import asdict, dataclass, field
import threading
from typing import Iterable


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    private: bool = False
    enabled: bool = True
    configured: bool = False
    capabilities: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ModelDescriptor:
    provider_id: str
    model_id: str
    display_name: str = ''
    capabilities: tuple[str, ...] = ('chat',)
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_score: float = 0.5
    coding_score: float = 0.5
    quality_score: float = 0.5
    latency_score: float = 0.5
    cost_score: float = 0.5
    enabled: bool = True
    deprecated: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return self.provider_id, self.model_id

    def supports(self, required: Iterable[str]) -> bool:
        available = set(self.capabilities)
        return set(required).issubset(available)

    def public(self) -> dict:
        return asdict(self)


class ModelRegistry:
    """Thread-safe capability registry. It stores metadata, never credentials."""

    def __init__(self):
        self._lock = threading.RLock()
        self._providers: dict[str, ProviderDescriptor] = {}
        self._models: dict[tuple[str, str], ModelDescriptor] = {}

    def register_provider(self, descriptor: ProviderDescriptor) -> None:
        if not descriptor.provider_id:
            raise ValueError('provider_id is required')
        with self._lock:
            self._providers[descriptor.provider_id] = descriptor

    def register_model(self, descriptor: ModelDescriptor) -> None:
        if not descriptor.provider_id or not descriptor.model_id:
            raise ValueError('provider_id and model_id are required')
        with self._lock:
            if descriptor.provider_id not in self._providers:
                raise ValueError('provider must be registered before its models')
            self._models[descriptor.key] = descriptor

    def provider(self, provider_id: str) -> ProviderDescriptor | None:
        with self._lock:
            return self._providers.get(provider_id)

    def model(self, provider_id: str, model_id: str) -> ModelDescriptor | None:
        with self._lock:
            return self._models.get((provider_id, model_id))

    def providers(self, *, enabled_only: bool = False) -> tuple[ProviderDescriptor, ...]:
        with self._lock:
            rows = tuple(self._providers.values())
        return tuple(row for row in rows if row.enabled) if enabled_only else rows

    def models(self, *, provider_id: str | None = None, enabled_only: bool = True) -> tuple[ModelDescriptor, ...]:
        with self._lock:
            rows = tuple(self._models.values())
        if provider_id is not None:
            rows = tuple(row for row in rows if row.provider_id == provider_id)
        if enabled_only:
            rows = tuple(row for row in rows if row.enabled and not row.deprecated)
        return rows

    def candidates(self, required_capabilities: Iterable[str] = (), *, allowed_providers: Iterable[str] = (), blocked_providers: Iterable[str] = ()) -> tuple[ModelDescriptor, ...]:
        allowed, blocked = set(allowed_providers), set(blocked_providers)
        result = []
        with self._lock:
            providers = dict(self._providers)
            models = tuple(self._models.values())
        for model in models:
            provider = providers.get(model.provider_id)
            if not provider or not provider.enabled or not provider.configured:
                continue
            if not model.enabled or model.deprecated or not model.supports(required_capabilities):
                continue
            if allowed and model.provider_id not in allowed:
                continue
            if model.provider_id in blocked:
                continue
            result.append(model)
        return tuple(result)

    @classmethod
    def from_router(cls, router) -> 'ModelRegistry':
        registry = cls()
        for provider in router.providers.values():
            descriptor = ProviderDescriptor(
                provider_id=provider.id,
                display_name=provider.id.replace('_', ' ').title(),
                private=bool(provider.private),
                enabled=provider.id not in set(getattr(router, 'disabled', ()) or ()),
                configured=bool(provider.configured and (provider.private or provider.api_key)),
                capabilities=tuple(provider.capabilities),
            )
            registry.register_provider(descriptor)
            if provider.model:
                registry.register_model(ModelDescriptor(
                    provider_id=provider.id,
                    model_id=provider.model,
                    display_name=provider.model,
                    capabilities=tuple(provider.capabilities),
                    latency_score=max(0.0, min(1.0, 1.0 - ((provider.latency_rank - 1) * .2))),
                    cost_score=max(0.0, min(1.0, 1.0 - ((provider.cost_rank - 1) * .2))),
                ))
        return registry
