from __future__ import annotations

import pytest

from visual_intelligence import VisualIntelligenceService
from visual_intelligence.deep_repository import _python_facts, _resolve_import, _script_facts
from visual_intelligence.models import VisualEdge, VisualGraph, VisualNode, VisualType
from visual_intelligence.native_maps import build_knowledge_graph, build_live_work_graph, build_memory_graph
from visual_intelligence.validator import VisualValidationError, assert_valid_graph


def test_create_chain_path_reach_and_artifact(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    item = service.create(
        owner_id='owner',
        title='Request path',
        visual_type='architecture',
        description='Browser -> API -> Redis -> PostgreSQL',
    )

    assert item['node_count'] == 4
    assert item['edge_count'] == 3
    graph = item['graph']
    ids = {node['label']: node['id'] for node in graph['nodes']}

    path = service.path('owner', item['id'], ids['Browser'], ids['PostgreSQL'])
    assert path['found'] is True
    assert path['hops'] == 3
    assert path['node_ids'][0] == ids['Browser']
    assert path['node_ids'][-1] == ids['PostgreSQL']

    reach = service.reach('owner', item['id'], ids['API'], 'downstream')
    assert ids['API'] in reach['node_ids']
    assert ids['Redis'] in reach['node_ids']
    assert ids['PostgreSQL'] in reach['node_ids']
    assert reach['max_hops'] == 2

    artifact = service.artifact('owner', item['id'])
    assert '<svg' in artifact
    assert 'Request path' in artifact
    assert 'Vishnu Visualize' in artifact
    service.close()


def test_project_map_and_revision_history(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    item = service.create(
        owner_id='owner',
        title='Launch project',
        visual_type='project_map',
        source_kind='project',
        project_id='project-1',
        description='Visualize this project',
        context={
            'goals': [{'title': 'Ship Visualize', 'status': 'active'}],
            'tasks': [{'title': 'Build viewer', 'status': 'working'}],
            'agents': [{'name': 'Frontend agent', 'status': 'working'}],
            'sources': ['Architecture specification'],
        },
    )
    assert item['type'] == 'project_map'
    assert item['project_id'] == 'project-1'
    assert item['node_count'] >= 9

    graph = item['graph']
    graph['nodes'][0]['description'] = 'Updated project description'
    updated = service.update('owner', item['id'], graph=graph, reason='owner edit')
    assert updated['graph']['nodes'][0]['description'] == 'Updated project description'
    revisions = service.revisions('owner', item['id'])
    assert [row['revision'] for row in revisions] == [2, 1]
    assert revisions[0]['reason'] == 'owner edit'
    service.close()


def test_compare_visuals(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    before = service.create(owner_id='owner', title='Before', description='App -> API', visual_type='architecture')
    after = service.create(owner_id='owner', title='After', description='App -> API -> Database', visual_type='architecture')
    delta = service.compare('owner', before['id'], after['id'])
    assert delta['summary']['added'] >= 1
    assert delta['summary']['removed'] == 0
    service.close()


def test_validation_rejects_missing_relationship_target():
    graph = VisualGraph(
        type=VisualType.ARCHITECTURE,
        title='Broken graph',
        nodes=[VisualNode(id='api', label='API')],
        edges=[VisualEdge(id='edge-1', source='api', target='missing')],
    )
    with pytest.raises(VisualValidationError) as exc:
        assert_valid_graph(graph)
    assert any(issue.code == 'missing_edge_target' for issue in exc.value.issues)


def test_generate_validate_repair_keeps_last_good_candidate(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    broken = VisualGraph(
        type=VisualType.ARCHITECTURE,
        title='Repair me',
        nodes=[VisualNode(id='api', label='API', width=20, height=10)],
        edges=[VisualEdge(id='dangling', source='api', target='missing')],
    )
    item = service.create(owner_id='owner', title='Repair me', visual_type='architecture', graph=broken)
    assert item['validation']['ok'] is True
    assert item['edge_count'] == 0
    assert item['graph']['nodes'][0]['width'] >= 80
    assert item['graph']['metadata']['validation_repair']['repairs']
    service.close()


def test_natural_language_edit_exports_presentation_and_shared_3d(tmp_path):
    service = VisualIntelligenceService(tmp_path / 'visuals.sqlite3')
    item = service.create(owner_id='owner', title='Architecture', description='Browser -> API -> Database', visual_type='architecture')
    api_node = next(node for node in item['graph']['nodes'] if node['label'] == 'API')
    before_x = api_node['x']
    result = service.edit('owner', item['id'], 'Move API right 180')
    edited_api = next(node for node in result['visualization']['graph']['nodes'] if node['label'] == 'API')
    assert edited_api['x'] == before_x + 180
    assert result['receipt']['operations'][0]['op'] == 'move'

    renamed = service.edit('owner', item['id'], 'Rename API to Request Gateway')
    assert any(node['label'] == 'Request Gateway' for node in renamed['visualization']['graph']['nodes'])

    presentation = service.presentation('owner', item['id'])
    assert presentation['schema'] == 'vishnu.visual.presentation.v1'
    assert presentation['slides'][0]['id'] == 'overview'
    scene = service.scene('owner', item['id'], dimension='3d')
    assert scene['schema'] == 'vishnu.visual.scene.v1'
    assert scene['dimension'] == '3d'
    assert all('z' in node['position'] for node in scene['nodes'])

    expected = {
        'html': 'text/html', 'svg': 'image/svg+xml', 'json': 'application/json',
        'png': 'image/png', 'webp': 'image/webp', 'pdf': 'application/pdf',
    }
    for fmt, mime_prefix in expected.items():
        payload, mime, filename = service.export('owner', item['id'], fmt)
        assert payload
        assert mime.startswith(mime_prefix)
        assert filename.endswith('.' + fmt)
    service.close()


def test_source_fact_extractors_preserve_line_evidence_inputs():
    python = """from app.db import store\nfrom fastapi import APIRouter\nrouter=APIRouter()\n\n@router.get('/health')\ndef health():\n    return store.ok()\n"""
    symbols, imports = _python_facts(python)
    health = next(symbol for symbol in symbols if symbol['name'] == 'health')
    assert health['line_start'] == 6
    assert health['routes'] == [{'method': 'GET', 'path': '/health'}]
    assert any(item['module'] == 'app.db' and item['line'] == 1 for item in imports)

    script = "import api from './api';\nexport function run() { return api(); }\napp.post('/jobs', run);\n"
    js_symbols, js_imports = _script_facts(script)
    assert any(item['name'] == 'run' and item['line_start'] == 2 for item in js_symbols)
    assert any(item['module'] == './api' for item in js_imports)
    assert _resolve_import('src/app.js', './api', {'src/app.js', 'src/api.js'}) == 'src/api.js'


class _FakeKnowledge:
    def list(self, query='', limit=100, *, access_classes=None, include_history=False):
        rows = [
            {'id': 'doc-1', 'title': 'Architecture', 'filename': 'architecture.md', 'source': 'owner-upload', 'checksum': 'abc', 'access_class': 'owner', 'metadata': {'collection_id': 'col-1'}, 'lineage_id': 'lin-1', 'version': 2, 'updated_at': 'now'},
            {'id': 'doc-2', 'title': 'Runbook', 'filename': 'runbook.md', 'source': 'owner-upload', 'checksum': 'def', 'access_class': 'private', 'metadata': {}, 'lineage_id': 'lin-2', 'version': 1, 'updated_at': 'now'},
        ]
        allowed = set(access_classes or {'owner', 'private'})
        return [row for row in rows if row['access_class'] in allowed][:limit]

    def collections(self):
        return [{'id': 'col-1', 'title': 'System', 'description': 'Core system docs', 'item_count': 1}]

    def detail(self, document_id, include_history=False):
        row = next(item for item in self.list(access_classes={'owner', 'private'}) if item['id'] == document_id)
        return {**row, 'memory_links': ([{'id': 'link-1', 'memory_id': 'mem-1', 'relationship': 'supports', 'rationale': 'Architecture decision'}] if document_id == 'doc-1' else [])}


def test_native_knowledge_memory_and_live_work_maps_are_privacy_scoped():
    knowledge = build_knowledge_graph(_FakeKnowledge(), access_classes={'owner'})
    assert knowledge.metadata['privacy_scoped'] is True
    assert knowledge.metadata['document_count'] == 1
    assert any(node.category == 'knowledge' for node in knowledge.nodes)
    assert any(edge.kind == 'memory_link' for edge in knowledge.edges)

    memory = build_memory_graph({
        'nodes': [{'id': 'mem-1', 'title': 'Architecture preference', 'type': 'preference', 'sensitivity': 'normal'}],
        'edges': [],
    })
    assert memory.metadata['privacy_scoped'] is True
    assert memory.nodes[0].metadata['sensitivity'] == 'normal'

    live = build_live_work_graph({
        'id': 'project-1', 'name': 'Visualize', 'goal': 'Ship advanced Visualize', 'status': 'active',
        'tasks': [
            {'id': 't1', 'title': 'Build analyzer', 'status': 'in_progress', 'owner': 'research agent', 'execution_run_id': 'run-1'},
            {'id': 't2', 'title': 'Verify', 'status': 'needs_review', 'owner': 'qa agent', 'depends_on': ['t1']},
        ],
        'milestones': [{'id': 'm1', 'title': 'Qualification', 'status': 'active'}],
        'files': [{'id': 'f1', 'title': 'Architecture spec', 'indexing_state': 'ready', 'kind': 'markdown'}],
    })
    assert live.metadata['live'] is True
    assert any(node.category == 'agent' for node in live.nodes)
    assert any(edge.kind == 'depends_on' for edge in live.edges)
