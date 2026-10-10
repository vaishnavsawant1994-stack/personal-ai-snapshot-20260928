from models.hybrid import HybridPolicy, HybridRequest, PrivacyMode
from models.router import Provider


def provider(provider_id: str, *, private: bool):
    return Provider(
        id=provider_id,
        base_url=f"https://{provider_id}.example.test/v1",
        api_key="key" if not private else "",
        model="model",
        private=private,
        capabilities=("chat",),
        cost_rank=1,
        latency_rank=1,
    )


def test_private_local_sensitivity_rejects_external_provider_even_when_owner_allows_external():
    local = provider("self_hosted", private=True)
    external = provider("openai", private=False)
    request = HybridRequest(
        capability="chat",
        sensitivity="private_local",
        privacy=PrivacyMode.EXTERNAL_ALLOWED,
        allowed_providers=("self_hosted", "openai"),
    )
    assert HybridPolicy.filter_candidates(request, (external, local)) == [local]


def test_internal_context_can_still_use_external_when_owner_policy_allows_it():
    local = provider("self_hosted", private=True)
    external = provider("openai", private=False)
    request = HybridRequest(
        capability="chat",
        sensitivity="internal",
        privacy=PrivacyMode.EXTERNAL_ALLOWED,
        allowed_providers=("self_hosted", "openai"),
    )
    assert HybridPolicy.filter_candidates(request, (external, local)) == [external, local]
