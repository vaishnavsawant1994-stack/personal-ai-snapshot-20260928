from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ProviderResult:
    content: str = ''
    payload: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    finish_reason: str | None = None


class ProviderAdapter(ABC):
    """Transport boundary for an AI provider.

    Adapters normalize transport/protocol differences only. They do not own
    Vishnu routing policy, memory, permissions, approvals or execution state.
    """

    provider_id: str

    @abstractmethod
    def invoke_chat(self, *, model: str, messages: list[dict], temperature: float = .3, timeout: float | None = None) -> ProviderResult:
        raise NotImplementedError

    def list_models(self, *, timeout: float | None = None) -> Iterable[str]:
        return ()

    def health_check(self, *, timeout: float | None = None) -> bool:
        try:
            tuple(self.list_models(timeout=timeout))
            return True
        except Exception:
            return False
