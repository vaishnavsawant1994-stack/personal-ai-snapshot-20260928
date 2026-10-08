from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.permissions import PermissionEngine
from devices.registry import DeviceRegistry
from knowledge.store import KnowledgeStore
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from models.router import ModelRouter
from server.owner_product import OwnerPermissionsBody, owner_product_router
from tools.registry import Risk, Tool, ToolRegistry


DEFAULTS = {
    'read': 'allow', 'create': 'allow', 'edit': 'allow', 'delete': 'ask',
    'external_communication': 'ask', 'execute_actions': 'ask',
    'financial_actions': 'ask', 'account_security_changes': 'ask',
}


def test_permission_rules_enforce_auto_ask_and_never_even_after_confirmation():
    engine = PermissionEngine('ask')
    engine.set_rules(DEFAULTS)
    assert engine.decide(Risk.READ_ONLY, operation='read').allowed
    assert engine.decide(Risk.REVERSIBLE, operation='create').allowed
    assert engine.decide(Risk.EXTERNAL_SIDE_EFFECT, operation='external_communication').requires_confirmation
    relaxed = {**DEFAULTS, 'financial_actions': 'allow', 'account_security_changes': 'allow'}
    engine.set_rules(relaxed)
    assert engine.decide(Risk.EXTERNAL_SIDE_EFFECT, operation='financial_actions').requires_confirmation
    assert engine.decide(Risk.REVERSIBLE, operation='account_security_changes').requires_confirmation
    denied = {**DEFAULTS, 'delete': 'never'}
    engine.set_rules(denied)
    decision = engine.decide(Risk.DESTRUCTIVE, operation='delete', confirmed=True)
    assert decision.allowed is False
    assert decision.requires_confirmation is False


def test_tool_registry_persists_owner_rules_and_enforces_category_mapping(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, autonomy_mode='ask')
    tools = ToolRegistry(settings)
    tools.update_owner_permissions('balanced', DEFAULTS)
    delete_tool = Tool('delete_file', 'Delete a file', lambda _: None, risk=Risk.DESTRUCTIVE)
    send_tool = Tool('send_email', 'Send an email', lambda _: None, risk=Risk.EXTERNAL_SIDE_EFFECT)
    create_tool = Tool('create_task', 'Create a task', lambda _: None, risk=Risk.REVERSIBLE)
    unknown_tool = Tool('w', '', lambda _: None, risk=Risk.REVERSIBLE)
    assert tools.authorize(delete_tool).requires_confirmation
    assert tools.authorize(send_tool).requires_confirmation
    assert tools.authorize(create_tool).allowed
    assert tools.authorize(unknown_tool).requires_confirmation

    restored = ToolRegistry(settings)
    assert restored.owner_permissions() == {'mode': 'balanced', 'rules': DEFAULTS}
    restored.set_owner_permission_rules({**DEFAULTS, 'delete': 'never'})
    assert not restored.authorize(delete_tool, confirmed=True).allowed


def test_default_model_provider_requires_real_configuration_and_persists(tmp_path):
    settings = SimpleNamespace(
        data_dir=tmp_path, autonomy_mode='ask', ai_provider='local', local_ai_explicit=True,
        local_ai_url='http://localhost:11434/v1', local_ai_model='llama3.2',
        openai_api_key='present-but-never-returned', openai_model='gpt-5-mini',
    )
    router = ModelRouter(settings)
    changed = router.set_default_provider('openai')
    assert changed['persisted'] is True
    assert router.status()['primary_provider'] == 'openai'
    assert router._candidates('chat', 'internal')[0].id == 'openai'
    assert all(provider.private for provider in router._candidates('chat', 'sensitive'))
    assert 'api_key' not in str(router.status())
    restarted = ModelRouter(settings)
    assert restarted.status()['primary_provider'] == 'openai'
    with pytest.raises(ValueError):
        restarted.set_default_provider('gemini')


def test_owner_permission_api_is_owner_authenticated_and_persistent(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, autonomy_mode='ask')
    tools = ToolRegistry(settings)
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, bearer = registry.enroll('Owner phone', 'ios-pwa')
    registry.set_permissions(device['id'], registry.OWNER_SCOPES)
    memory = MemoryStore(tmp_path / 'memory.sqlite3')
    runtime = {
        'device_registry': registry,
        'memory': memory,
        'second_brain': SecondBrain(memory),
        'knowledge': KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects'),
        'tools': tools,
    }
    router = owner_product_router(runtime)
    get_permissions = next(route.endpoint for route in router.routes if route.path.endswith('/owner/permissions') and 'GET' in route.methods)
    patch_permissions = next(route.endpoint for route in router.routes if route.path.endswith('/owner/permissions') and 'PATCH' in route.methods)
    with pytest.raises(HTTPException) as unauthenticated:
        get_permissions(None, None)
    assert unauthenticated.value.status_code == 401

    current = get_permissions(device['id'], bearer)
    assert current['rules'] == DEFAULTS
    changed = patch_permissions(OwnerPermissionsBody(mode='custom', rules={**DEFAULTS, 'delete': 'never'}), device['id'], bearer)
    assert changed['ok'] is True
    assert changed['rules']['delete'] == 'never'
    assert get_permissions(device['id'], bearer)['mode'] == 'custom'
    events = memory.audit_entries('owner-product')
    assert any(row['action'] == 'owner.permissions.updated' for row in events)
