from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from models.registry import ModelDescriptor


@dataclass(frozen=True)
class RoutingPolicy:
    policy_id: str
    required_capabilities: tuple[str, ...] = ('chat',)
    preferred_capabilities: tuple[str, ...] = ()
    quality_weight: float = .35
    reasoning_weight: float = .25
    coding_weight: float = .0
    latency_weight: float = .20
    cost_weight: float = .20
    prefer_private: bool = False

    def score(self, model: ModelDescriptor, *, preferred_provider: str | None = None, preferred_model: str | None = None, session_provider: str | None = None) -> tuple[float, tuple[str, ...]]:
        if not model.supports(self.required_capabilities):
            return -1.0, ('missing_required_capability',)
        score = (
            model.quality_score * self.quality_weight
            + model.reasoning_score * self.reasoning_weight
            + model.coding_score * self.coding_weight
            + model.latency_score * self.latency_weight
            + model.cost_score * self.cost_weight
        )
        reasons = ['capabilities_match']
        if set(self.preferred_capabilities).issubset(set(model.capabilities)):
            score += .04
            reasons.append('preferred_capabilities')
        if preferred_provider and model.provider_id == preferred_provider:
            score += .08
            reasons.append('preferred_provider')
        if preferred_model and model.model_id == preferred_model:
            score += .12
            reasons.append('preferred_model')
        if session_provider and model.provider_id == session_provider:
            score += .05
            reasons.append('session_affinity')
        return round(score, 6), tuple(reasons)


DEFAULT_POLICIES = {
    'fast_chat': RoutingPolicy('fast_chat', latency_weight=.35, cost_weight=.30, quality_weight=.25, reasoning_weight=.10),
    'deep_reasoning': RoutingPolicy('deep_reasoning', quality_weight=.40, reasoning_weight=.40, latency_weight=.10, cost_weight=.10),
    'coding': RoutingPolicy('coding', required_capabilities=('chat',), preferred_capabilities=('json',), quality_weight=.30, reasoning_weight=.25, coding_weight=.35, latency_weight=.05, cost_weight=.05),
    'research': RoutingPolicy('research', quality_weight=.40, reasoning_weight=.35, latency_weight=.10, cost_weight=.15),
    'vision': RoutingPolicy('vision', required_capabilities=('vision',), quality_weight=.45, reasoning_weight=.25, latency_weight=.15, cost_weight=.15),
    'tool_execution': RoutingPolicy('tool_execution', required_capabilities=('chat', 'json'), quality_weight=.40, reasoning_weight=.30, latency_weight=.15, cost_weight=.15),
    'long_context': RoutingPolicy('long_context', quality_weight=.45, reasoning_weight=.30, latency_weight=.10, cost_weight=.15),
    'background': RoutingPolicy('background', quality_weight=.20, reasoning_weight=.15, latency_weight=.20, cost_weight=.45),
    'low_cost': RoutingPolicy('low_cost', quality_weight=.15, reasoning_weight=.10, latency_weight=.15, cost_weight=.60),
    'critical': RoutingPolicy('critical', quality_weight=.50, reasoning_weight=.40, latency_weight=.05, cost_weight=.05),
    'private_local': RoutingPolicy('private_local', quality_weight=.35, reasoning_weight=.25, latency_weight=.20, cost_weight=.20, prefer_private=True),
    'review': RoutingPolicy('review', quality_weight=.45, reasoning_weight=.40, latency_weight=.05, cost_weight=.10),
}


class PolicyRegistry:
    def __init__(self, policies: Iterable[RoutingPolicy] = ()):
        self._policies = dict(DEFAULT_POLICIES)
        self._policies.update({policy.policy_id: policy for policy in policies})

    def get(self, policy_id: str) -> RoutingPolicy:
        try:
            return self._policies[policy_id]
        except KeyError as exc:
            raise ValueError(f'unknown routing policy: {policy_id}') from exc

    def all(self) -> tuple[RoutingPolicy, ...]:
        return tuple(self._policies.values())
