from __future__ import annotations

import json

from visual_intelligence.native_maps import build_memory_graph


def test_memory_map_accepts_canonical_second_brain_src_dst_edges_and_metadata_json():
    payload = {
        'linked_second_brain': True,
        'nodes': [
            {
                'id': 'memory:mem-1',
                'memory_id': 'mem-1',
                'type': 'decision',
                'label': 'Use governed visual evidence',
                'summary': 'Architecture decision',
                'origin': 'second_brain',
                'source': 'memory',
                'confidence': 0.93,
                'metadata_json': json.dumps({
                    'origin': 'second_brain',
                    'memory_id': 'mem-1',
                    'sensitivity': 'sensitive',
                    'verified': True,
                    'evidence': [{'kind': 'conversation', 'id': 'c1'}],
                }),
            },
            {
                'id': 'memory:mem-2',
                'memory_id': 'mem-2',
                'type': 'project',
                'label': 'Vishnu Visualize',
                'summary': 'Current project',
                'origin': 'second_brain',
                'source': 'memory',
                'confidence': 0.88,
                'metadata_json': json.dumps({'sensitivity': 'normal'}),
            },
        ],
        'edges': [
            {
                'id': 'memory-relation:r1',
                'src': 'memory:mem-1',
                'dst': 'memory:mem-2',
                'relation': 'applies_to',
                'rationale': 'Second Brain relationship',
                'source': 'second_brain',
                'confidence': 1.0,
                'origin': 'second_brain',
            }
        ],
    }

    graph = build_memory_graph(payload)

    assert graph.metadata['privacy_scoped'] is True
    assert graph.metadata['linked_second_brain'] is True
    assert graph.metadata['source_edge_count'] == 1
    assert graph.metadata['projected_edge_count'] == 1
    assert len(graph.edges) == 1
    assert graph.edges[0].kind == 'applies_to'
    assert graph.edges[0].metadata['origin'] == 'second_brain'
    assert graph.edges[0].metadata['confidence'] == 1.0

    sensitive = next(node for node in graph.nodes if node.metadata['canonical_memory_id'] == 'mem-1')
    normal = next(node for node in graph.nodes if node.metadata['canonical_memory_id'] == 'mem-2')
    assert sensitive.metadata['sensitivity'] == 'sensitive'
    assert sensitive.metadata['verified'] is True
    assert sensitive.evidence[0]['sensitivity'] == 'sensitive'
    assert sensitive.evidence[0]['evidence'] == [{'kind': 'conversation', 'id': 'c1'}]
    assert normal.metadata['sensitivity'] == 'normal'
