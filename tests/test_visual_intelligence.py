from __future__ import annotations

import pytest

from visual_intelligence import VisualIntelligenceService
from visual_intelligence.models import VisualEdge, VisualGraph, VisualNode, VisualType
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
