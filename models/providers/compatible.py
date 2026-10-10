from __future__ import annotations

import json
from typing import Callable

from models.providers.base import ProviderAdapter, ProviderResult


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter over Vishnu's bounded/authenticated request primitive."""

    def __init__(self, provider, request_fn: Callable):
        self.provider = provider
        self.provider_id = provider.id
        self._request = request_fn

    @staticmethod
    def _usage(payload: dict) -> tuple[int, int, int, float]:
        usage = payload.get('usage') if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return 0, 0, 0, 0.0
        inp = usage.get('input_tokens', usage.get('prompt_tokens', 0))
        out = usage.get('output_tokens', usage.get('completion_tokens', 0))
        total = usage.get('total_tokens', 0)
        cost = usage.get('cost', 0)
        return int(inp or 0), int(out or 0), int(total or (int(inp or 0) + int(out or 0))), float(cost or 0)

    def invoke_chat(self, *, model: str, messages: list[dict], temperature: float = .3, timeout: float | None = None) -> ProviderResult:
        response = self._request(
            self.provider, 'POST', '/chat/completions',
            json={'model': model, 'messages': messages, 'temperature': temperature}, timeout=timeout,
        )
        try:
            payload = response.json()
            choice = payload['choices'][0]
            content = choice['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('empty content')
            inp, out, total, cost = self._usage(payload)
            return ProviderResult(
                content=content.strip(), payload=payload, input_tokens=inp,
                output_tokens=out, total_tokens=total, cost=cost,
                finish_reason=choice.get('finish_reason'),
            )
        except (AttributeError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            # Keep adapter independent of router exception classes to avoid a cycle.
            raise ValueError('invalid compatible provider response') from exc

    def list_models(self, *, timeout: float | None = None):
        response = self._request(self.provider, 'GET', '/models', timeout=timeout)
        payload = response.json()
        rows = payload.get('data', []) if isinstance(payload, dict) else []
        return tuple(str(row['id']) for row in rows if isinstance(row, dict) and row.get('id'))
