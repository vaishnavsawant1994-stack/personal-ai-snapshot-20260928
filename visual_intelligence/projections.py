from __future__ import annotations

from collections import defaultdict

from .models import VisualGraph


_CATEGORY_DEPTH = {
    'project': 0.0, 'external': -1.0, 'frontend': 0.4, 'api': 0.7, 'backend': 1.0, 'agent': 1.4,
    'tool': 1.7, 'database': 2.0, 'security': 1.2, 'cloud': 2.4, 'symbol': 0.8, 'group': 0.2, 'component': 1.0,
}


def scene_projection(graph: VisualGraph, *, dimension: str = '3d') -> dict:
    dimension = str(dimension or '3d').lower()
    if dimension not in {'2d', '3d'}:
        raise ValueError('dimension must be 2d or 3d')
    nodes = []
    for index, node in enumerate(graph.nodes):
        x = float(node.x or 0.0)
        y = float(node.y or 0.0)
        z = 0.0 if dimension == '2d' else float(node.metadata.get('z', _CATEGORY_DEPTH.get(node.category, 1.0) * 180 + (index % 5) * 9))
        nodes.append({
            'id': node.id, 'label': node.label, 'category': node.category, 'status': node.status,
            'position': {'x': x, 'y': y, 'z': z},
            'size': {'width': node.width, 'height': node.height, 'depth': float(node.metadata.get('depth', 54.0))},
            'evidence_level': node.evidence_level.value, 'metadata': dict(node.metadata),
        })
    edges = [{'id': edge.id, 'source': edge.source, 'target': edge.target, 'kind': edge.kind, 'label': edge.label, 'directed': edge.directed, 'metadata': dict(edge.metadata)} for edge in graph.edges]
    return {
        'schema': 'vishnu.visual.scene.v1', 'dimension': dimension, 'visual_type': graph.type.value,
        'title': graph.title, 'nodes': nodes, 'edges': edges,
        'metadata': {**dict(graph.metadata), 'canonical_ids': True, 'projection_only': True},
    }


def _slide(graph: VisualGraph, *, slide_id: str, title: str, node_ids: list[str], purpose: str) -> dict:
    allowed = set(node_ids)
    edge_ids = [edge.id for edge in graph.edges if edge.source in allowed and edge.target in allowed]
    return {'id': slide_id, 'title': title, 'purpose': purpose, 'node_ids': node_ids, 'edge_ids': edge_ids}


def presentation_projection(graph: VisualGraph) -> dict:
    slides = [_slide(graph, slide_id='overview', title='Overview', node_ids=[node.id for node in graph.nodes], purpose='Complete system overview')]
    categories: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        categories[node.category].append(node.id)

    preferred = [
        ('agents', {'agent'}, 'Agents', 'Agents and autonomous execution'),
        ('memory', {'database'}, 'Memory & Data', 'Memory, knowledge and persisted data'),
        ('security', {'security'}, 'Security', 'Identity, policy and security boundaries'),
        ('interfaces', {'frontend', 'api'}, 'Interfaces & APIs', 'User surfaces and API boundaries'),
        ('tools', {'tool'}, 'Tools & Integrations', 'Tools, connectors and external capabilities'),
        ('infrastructure', {'cloud'}, 'Infrastructure', 'Deployment and infrastructure components'),
    ]
    for slide_id, kinds, title, purpose in preferred:
        seed = {node.id for node in graph.nodes if node.category in kinds}
        if not seed:
            continue
        connected = set(seed)
        for edge in graph.edges:
            if edge.source in seed or edge.target in seed:
                connected.add(edge.source); connected.add(edge.target)
        slides.append(_slide(graph, slide_id=slide_id, title=title, node_ids=[node.id for node in graph.nodes if node.id in connected], purpose=purpose))

    authored = []
    for index, view in enumerate(graph.views):
        ids = [str(item) for item in (view.get('node_ids') or []) if any(node.id == str(item) for node in graph.nodes)]
        if ids:
            authored.append(_slide(graph, slide_id=str(view.get('id') or f'view-{index+1}'), title=str(view.get('title') or f'View {index+1}'), node_ids=ids, purpose=str(view.get('description') or 'Authored visual view')))
    slides.extend(authored)
    return {'schema': 'vishnu.visual.presentation.v1', 'title': graph.title, 'slides': slides, 'metadata': {'canonical_ids': True, 'slide_count': len(slides)}}
