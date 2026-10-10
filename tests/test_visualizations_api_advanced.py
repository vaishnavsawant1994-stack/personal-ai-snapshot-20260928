from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.visualizations_api import visualizations_router
from visual_intelligence import VisualIntelligenceService


class _Registry:
    def __init__(self, *, sensitive=True, private=True):
        self.sensitive = sensitive
        self.private = private

    def authenticate(self, device_id, token):
        return device_id == 'device-1' and token == 'token-1'

    def is_active(self, device_id):
        return device_id == 'device-1'

    def authorize(self, device_id, scope):
        if device_id != 'device-1':
            return False
        if scope == 'memory:sensitive':
            return self.sensitive
        if scope == 'knowledge:private':
            return self.private
        return scope in {'ai:chat', 'memory:read', 'knowledge:read'}


class _Projects:
    def get(self, project_id):
        if project_id != 'project-1':
            return None
        return {
            'id': 'project-1',
            'name': 'Visualize',
            'goal': 'Ship advanced Visual Intelligence',
            'status': 'active',
            'milestones': [{'id': 'm1', 'title': 'Qualification', 'status': 'active'}],
            'tasks': [
                {'id': 't1', 'title': 'Deep analyzer', 'status': 'in_progress', 'owner': 'research agent', 'execution_run_id': 'run-1'},
                {'id': 't2', 'title': 'Qualification', 'status': 'needs_review', 'owner': 'qa agent', 'depends_on': ['t1']},
            ],
            'files': [{'id': 'f1', 'title': 'Visualize spec', 'indexing_state': 'ready', 'kind': 'markdown'}],
        }


class _Knowledge:
    ROWS = [
        {'id': 'doc-1', 'title': 'Architecture', 'filename': 'architecture.md', 'source': 'owner-upload', 'checksum': 'a', 'access_class': 'owner', 'metadata': {}, 'lineage_id': 'l1', 'version': 1, 'updated_at': 'now'},
        {'id': 'doc-2', 'title': 'Private Runbook', 'filename': 'private.md', 'source': 'owner-upload', 'checksum': 'b', 'access_class': 'private', 'metadata': {}, 'lineage_id': 'l2', 'version': 1, 'updated_at': 'now'},
    ]

    def __init__(self):
        self.last_access_classes = None

    def list(self, query='', limit=100, *, access_classes=None, include_history=False):
        self.last_access_classes = set(access_classes or ())
        return [row for row in self.ROWS if row['access_class'] in self.last_access_classes][:limit]

    def collections(self):
        return []

    def detail(self, document_id, include_history=False):
        row = next(item for item in self.ROWS if item['id'] == document_id)
        return {**row, 'memory_links': []}


class _LifeGraph:
    def __init__(self):
        self.allowed = None

    def graph(self, *, type=None, limit=500, allowed_sensitivities=None):
        self.allowed = set(allowed_sensitivities or ())
        rows = [
            {
                'id': 'memory:normal', 'memory_id': 'normal', 'type': 'decision', 'label': 'Normal memory',
                'summary': 'normal', 'origin': 'second_brain', 'metadata_json': json.dumps({'sensitivity': 'normal'}),
            },
            {
                'id': 'memory:secret', 'memory_id': 'secret', 'type': 'decision', 'label': 'Secret memory',
                'summary': 'secret', 'origin': 'second_brain', 'metadata_json': json.dumps({'sensitivity': 'secret'}),
            },
        ]
        visible = [row for row in rows if json.loads(row['metadata_json'])['sensitivity'] in self.allowed]
        return {'nodes': visible[:limit], 'edges': [], 'linked_second_brain': True}


def _client(tmp_path, *, sensitive=True, private=True, service=None):
    service = service or VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    knowledge = _Knowledge()
    life_graph = _LifeGraph()
    runtime = {
        'visual_intelligence': service,
        'device_registry': _Registry(sensitive=sensitive, private=private),
        'project_store': _Projects(),
        'continuity': None,
        'knowledge': knowledge,
        'second_brain_life_graph': life_graph,
    }
    app = FastAPI()
    app.include_router(visualizations_router(runtime))
    client = TestClient(app)
    client.cookies.set('pa_device', 'device-1')
    client.cookies.set('pa_token', 'token-1')
    return client, service, knowledge, life_graph


def test_advanced_visualize_api_requires_owner_session(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    app = FastAPI()
    app.include_router(visualizations_router({
        'visual_intelligence': service,
        'device_registry': _Registry(),
        'project_store': _Projects(),
        'continuity': None,
        'knowledge': _Knowledge(),
        'second_brain_life_graph': _LifeGraph(),
    }))
    with TestClient(app) as client:
        assert client.get('/iphone/api/visualizations').status_code == 401
    service.close()


def test_native_map_http_endpoints_enforce_privacy_and_use_real_service(tmp_path):
    client, service, knowledge, life_graph = _client(tmp_path, sensitive=True, private=False)
    try:
        live = client.post('/iphone/api/visualizations/live-work-map', json={'project_id': 'project-1'})
        assert live.status_code == 200
        live_visual = live.json()['visualization']
        assert live_visual['mode'] == 'live'
        assert live_visual['source_kind'] == 'live_work'
        assert any(node['category'] == 'agent' for node in live_visual['graph']['nodes'])

        knowledge_response = client.post('/iphone/api/visualizations/knowledge-map', json={'query': 'architecture'})
        assert knowledge_response.status_code == 200
        assert 'private' not in knowledge.last_access_classes
        knowledge_visual = knowledge_response.json()['visualization']
        assert knowledge_visual['source_kind'] == 'knowledge'
        assert knowledge_visual['graph']['metadata']['privacy_scoped'] is True

        normal = client.post('/iphone/api/visualizations/memory-map', json={})
        assert normal.status_code == 200
        assert life_graph.allowed == {'normal'}
        assert normal.json()['visualization']['node_count'] == 1

        sensitive = client.post('/iphone/api/visualizations/memory-map', json={'include_sensitive': True})
        assert sensitive.status_code == 200
        assert life_graph.allowed == {'normal', 'sensitive', 'secret'}
        assert sensitive.json()['visualization']['node_count'] == 2
    finally:
        client.close()
        service.close()


def test_sensitive_memory_map_fails_closed_without_permission(tmp_path):
    client, service, _, life_graph = _client(tmp_path, sensitive=False)
    try:
        response = client.post('/iphone/api/visualizations/memory-map', json={'include_sensitive': True})
        assert response.status_code == 403
        assert life_graph.allowed is None
    finally:
        client.close()
        service.close()


def test_edit_presentation_scene_and_export_are_real_http_routes(tmp_path):
    client, service, _, _ = _client(tmp_path)
    try:
        created = client.post('/iphone/api/visualizations', json={
            'title': 'Runtime', 'type': 'architecture', 'description': 'Browser -> API -> Database',
        })
        assert created.status_code == 200
        visual = created.json()['visualization']
        visual_id = visual['id']

        edit = client.post(f'/iphone/api/visualizations/{visual_id}/edit', json={'instruction': 'Highlight API'})
        assert edit.status_code == 200
        assert edit.json()['receipt']['operations'][0]['op'] == 'highlight'
        assert 'vv-authored-highlight' in edit.json()['visualization']['svg']

        presentation = client.get(f'/iphone/api/visualizations/{visual_id}/presentation')
        assert presentation.status_code == 200
        assert presentation.json()['schema'] == 'vishnu.visual.presentation.v1'

        scene = client.get(f'/iphone/api/visualizations/{visual_id}/scene?dimension=3d')
        assert scene.status_code == 200
        assert scene.json()['schema'] == 'vishnu.visual.scene.v1'
        assert scene.json()['dimension'] == '3d'

        exported = client.get(f'/iphone/api/visualizations/{visual_id}/export?format=json')
        assert exported.status_code == 200
        assert exported.headers['content-type'].startswith('application/json')
        assert exported.json()['title'] == 'Runtime'
    finally:
        client.close()
        service.close()


def test_persisted_private_and_sensitive_visuals_recheck_device_scope(tmp_path):
    shared = VisualIntelligenceService(tmp_path / 'shared-visuals.sqlite3')
    privileged, _, privileged_knowledge, privileged_life = _client(
        tmp_path,
        sensitive=True,
        private=True,
        service=shared,
    )
    try:
        ordinary = privileged.post('/iphone/api/visualizations', json={
            'title': 'Public architecture', 'type': 'architecture', 'description': 'App -> API',
        })
        assert ordinary.status_code == 200
        ordinary_id = ordinary.json()['visualization']['id']

        knowledge = privileged.post('/iphone/api/visualizations/knowledge-map', json={'title': 'Private Knowledge'})
        assert knowledge.status_code == 200
        knowledge_visual = knowledge.json()['visualization']
        knowledge_id = knowledge_visual['id']
        assert 'private' in knowledge_visual['graph']['metadata']['access_classes']
        assert 'private' in privileged_knowledge.last_access_classes

        memory = privileged.post('/iphone/api/visualizations/memory-map', json={
            'title': 'Sensitive Memory', 'include_sensitive': True,
        })
        assert memory.status_code == 200
        memory_visual = memory.json()['visualization']
        memory_id = memory_visual['id']
        assert set(memory_visual['graph']['metadata']['allowed_sensitivities']) == {'normal', 'sensitive', 'secret'}
        assert privileged_life.allowed == {'normal', 'sensitive', 'secret'}

        refreshed_knowledge = privileged.post(f'/iphone/api/visualizations/{knowledge_id}/refresh', json={})
        assert refreshed_knowledge.status_code == 200
        assert 'private' in refreshed_knowledge.json()['visualization']['graph']['metadata']['access_classes']
        refreshed_memory = privileged.post(f'/iphone/api/visualizations/{memory_id}/refresh', json={})
        assert refreshed_memory.status_code == 200
        assert set(refreshed_memory.json()['visualization']['graph']['metadata']['allowed_sensitivities']) == {'normal', 'sensitive', 'secret'}
    finally:
        privileged.close()

    restricted, _, _, restricted_life = _client(
        tmp_path,
        sensitive=False,
        private=False,
        service=shared,
    )
    try:
        listed = restricted.get('/iphone/api/visualizations')
        assert listed.status_code == 200
        visible_ids = {item['id'] for item in listed.json()['visualizations']}
        assert ordinary_id in visible_ids
        assert knowledge_id not in visible_ids
        assert memory_id not in visible_ids

        for visual_id in (knowledge_id, memory_id):
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}').status_code == 403
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}/export?format=json').status_code == 403
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}/artifact').status_code == 403
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}/revisions').status_code == 403
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}/presentation').status_code == 403
            assert restricted.get(f'/iphone/api/visualizations/{visual_id}/scene?dimension=3d').status_code == 403
            assert restricted.post(f'/iphone/api/visualizations/{visual_id}/refresh', json={}).status_code == 403
            assert restricted.post(f'/iphone/api/visualizations/{visual_id}/edit', json={'instruction': 'Highlight anything'}).status_code == 403
            assert restricted.delete(f'/iphone/api/visualizations/{visual_id}').status_code == 403

        compare = restricted.post('/iphone/api/visualizations/compare', json={
            'before_id': ordinary_id,
            'after_id': memory_id,
        })
        assert compare.status_code == 403
        assert restricted_life.allowed is None
    finally:
        restricted.close()
        shared.close()
