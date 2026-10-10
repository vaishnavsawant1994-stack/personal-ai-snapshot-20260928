from types import SimpleNamespace

import pytest

from models.budget import BudgetEngine, BudgetExceeded, BudgetLimits
from models.contracts import ModelRequest
from models.policies import PolicyRegistry
from models.quota import QuotaEngine, QuotaExceeded, QuotaLimits
from models.registry import ModelDescriptor, ModelRegistry, ProviderDescriptor


def test_registry_filters_by_capability_and_never_stores_credentials():
    registry = ModelRegistry()
    registry.register_provider(ProviderDescriptor('p1', 'Provider One', configured=True, capabilities=('chat','json')))
    registry.register_provider(ProviderDescriptor('p2', 'Provider Two', configured=True, capabilities=('chat',)))
    registry.register_model(ModelDescriptor('p1','m1',capabilities=('chat','json')))
    registry.register_model(ModelDescriptor('p2','m2',capabilities=('chat',)))
    rows = registry.candidates(('chat','json'))
    assert [(row.provider_id,row.model_id) for row in rows] == [('p1','m1')]
    assert 'api_key' not in registry.provider('p1').public()


def test_policy_scoring_respects_affinity_and_preference():
    policy = PolicyRegistry().get('coding')
    base = ModelDescriptor('p','m',capabilities=('chat','json'),quality_score=.8,reasoning_score=.8,coding_score=.9,latency_score=.4,cost_score=.4)
    score1,_ = policy.score(base)
    score2,reasons = policy.score(base,preferred_provider='p',session_provider='p')
    assert score2 > score1
    assert 'preferred_provider' in reasons
    assert 'session_affinity' in reasons


def test_quota_reservation_is_concurrency_safe():
    quota = QuotaEngine()
    quota.configure('p', QuotaLimits(concurrent_requests=1, requests_per_minute=2))
    first = quota.reserve('p',tokens=10)
    with pytest.raises(QuotaExceeded):
        quota.reserve('p',tokens=1)
    quota.commit(first.reservation_id,actual_tokens=7)
    second = quota.reserve('p',tokens=1)
    quota.release(second.reservation_id)
    assert quota.snapshot('p')['usage']['concurrent_requests'] == 0


def test_hierarchical_budget_blocks_child_from_escaping_parent():
    budget = BudgetEngine()
    budget.configure('global', BudgetLimits(max_cost=1.0,max_parallel_model_calls=1))
    budget.configure('task:a', BudgetLimits(max_cost=5.0))
    first = budget.reserve(('global','task:a'),cost=.8,model_call=True)
    with pytest.raises(BudgetExceeded):
        budget.reserve(('global','task:a'),cost=.3,model_call=True)
    budget.commit(first.reservation_id,actual_cost=.8)
    with pytest.raises(BudgetExceeded):
        budget.reserve(('global','task:a'),cost=.3,model_call=True)


def test_model_request_supports_provider_constraints_without_secrets():
    request = ModelRequest(
        prompt='x',routing_policy='research',allowed_providers=('p1','p2'),blocked_providers=('p3',),
        required_capabilities=('chat',),preferred_capabilities=('json',),
    )
    assert request.allowed_providers == ('p1','p2')
    assert request.blocked_providers == ('p3',)
