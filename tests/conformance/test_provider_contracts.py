from __future__ import annotations

import pytest

from integrations.provider_contracts import ProviderConformanceError, ProviderKind, conformance_snapshot


class GoodReasoner:
    def chat(self, *args, **kwargs): return "ok"
    def json(self, *args, **kwargs): return {}
    def embed(self, *args, **kwargs): return [0.0]


class BadReasoner:
    def chat(self, *args, **kwargs): return "ok"


def test_reasoning_provider_contract_is_structural_and_not_authorization():
    snapshot = conformance_snapshot(GoodReasoner(), kind=ProviderKind.REASONING, provider_id="good")
    assert snapshot.capabilities == ("chat", "embed", "json")
    assert snapshot.metadata["authorization_authority"] is False


def test_missing_provider_methods_fail_conformance():
    with pytest.raises(ProviderConformanceError, match="missing required methods"):
        conformance_snapshot(BadReasoner(), kind=ProviderKind.REASONING, provider_id="bad")
