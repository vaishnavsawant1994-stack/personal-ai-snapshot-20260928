from future_intelligence.workers import DEFAULT_WORKERS, WorkerRegistry


def test_default_worker_roles_have_intelligence_policies():
    profiles = {profile.id: profile for profile in DEFAULT_WORKERS}
    assert profiles['research'].routing_policy == 'research'
    assert profiles['coding'].routing_policy == 'coding'
    assert profiles['reviewer'].routing_policy == 'review'
    assert profiles['project'].parallelizable is False
    assert all('chat' in profile.required_model_capabilities for profile in profiles.values())


def test_worker_registry_status_exposes_non_authoritative_intelligence_profiles():
    status = WorkerRegistry.default().status()
    assert status['authority'] == 'proposal_only'
    assert status['execution_authority'] == 'existing_p10_p6_tool_registry'
    assert status['intelligence_profiles']['coding']['routing_policy'] == 'coding'
