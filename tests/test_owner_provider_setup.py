import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from devices.registry import DeviceRegistry
from security.vault import SecretVault
from knowledge.store import KnowledgeStore
from memory.second_brain import SecondBrain
from memory.store import MemoryStore
from models.router import ModelRouter
from server.owner_product import OwnerProviderConnectBody, OwnerProviderTestBody, owner_product_router


class ProviderResponse:
    status_code = 200
    headers = {'Content-Length': '2'}
    content = b'{}'

    def json(self):
        return {'data': [{'id': 'model-live-1'}, {'id': 'model-live-2'}]}


def make_router(tmp_path):
    settings = SimpleNamespace(
        data_dir=tmp_path, ai_provider='local', local_ai_explicit=True,
        local_ai_url='http://localhost:11434/v1', local_ai_model='llama3.2',
        openai_api_key='', openai_model='gpt-5-mini',
    )
    vault = SecretVault(tmp_path / 'vault.json', 'test-vault-password')
    return settings, vault, ModelRouter(settings, vault=vault)


def test_owner_provider_test_lists_live_models_without_storing_credential(tmp_path, monkeypatch):
    settings, vault, router = make_router(tmp_path)
    monkeypatch.setattr(router, '_request', lambda *args, **kwargs: ProviderResponse())
    result = router.test_owner_provider('openai', 'sk-test-key-1234567890')
    assert result == {'provider': 'openai', 'models': ['model-live-1', 'model-live-2'], 'credential_stored': False}
    assert vault.get('ai-provider:openai:api-key') is None
    assert 'sk-test-key' not in str(router.status())


def test_owner_provider_connection_is_encrypted_persisted_and_disconnectable(tmp_path, monkeypatch):
    settings, vault, router = make_router(tmp_path)
    monkeypatch.setattr(router, '_request', lambda *args, **kwargs: ProviderResponse())
    result = router.connect_owner_provider('openai', 'sk-test-key-1234567890', 'model-live-2')
    assert result['credential_stored'] is True
    assert vault.get('ai-provider:openai:api-key') == 'sk-test-key-1234567890'
    assert 'sk-test-key' not in (tmp_path / 'vault.json').read_text()
    assert router.providers['openai'].model == 'model-live-2'
    assert 'api_key' not in str(router.status())
    assert router.owner_provider_models('openai')['models'] == ['model-live-1', 'model-live-2']
    assert router.set_owner_provider_model('openai', 'model-live-1')['model'] == 'model-live-1'

    restarted = ModelRouter(settings, vault=vault)
    assert restarted.providers['openai'].api_key == 'sk-test-key-1234567890'
    assert restarted.providers['openai'].model == 'model-live-1'
    restarted.set_default_provider('openai')
    with pytest.raises(ValueError, match='another default'):
        restarted.disconnect_owner_provider('openai')
    restarted.set_default_provider('self_hosted')
    assert restarted.disconnect_owner_provider('openai')['disconnected'] is True
    assert vault.get('ai-provider:openai:api-key') is None
    assert 'openai' not in restarted._owner_provider_configs


def test_owner_provider_routes_authenticate_and_audit_without_secret_payload(tmp_path, monkeypatch):
    settings, vault, models = make_router(tmp_path)
    monkeypatch.setattr(models, '_request', lambda *args, **kwargs: ProviderResponse())
    registry = DeviceRegistry(tmp_path / 'devices.sqlite3')
    device, bearer = registry.enroll('Owner device', 'ios-pwa')
    registry.set_permissions(device['id'], registry.OWNER_SCOPES)
    memory = MemoryStore(tmp_path / 'memory.sqlite3')
    runtime = {'device_registry': registry, 'memory': memory, 'second_brain': SecondBrain(memory),
               'knowledge': KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects'), 'models': models}
    router = owner_product_router(runtime)
    test_endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/owner/ai-providers/test'))
    connect_endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/owner/ai-providers') and 'POST' in route.methods)
    with pytest.raises(HTTPException) as denied:
        test_endpoint(OwnerProviderTestBody(provider_id='openai', api_key='sk-test-key-1234567890'), None, None)
    assert denied.value.status_code == 401
    tested = test_endpoint(OwnerProviderTestBody(provider_id='openai', api_key='sk-test-key-1234567890'), device['id'], bearer)
    assert tested['credential_stored'] is False
    saved = connect_endpoint(OwnerProviderConnectBody(provider_id='openai', api_key='sk-test-key-1234567890', model='model-live-1'), device['id'], bearer)
    assert saved['ok'] is True and saved['model'] == 'model-live-1'
    events = memory.audit_entries('owner-product')
    assert any(item['action'] == 'model.provider.connected' for item in events)
    assert 'sk-test-key' not in json.dumps(events)
