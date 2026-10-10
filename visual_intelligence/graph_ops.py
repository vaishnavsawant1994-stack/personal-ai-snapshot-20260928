from __future__ import annotations

from collections import defaultdict, deque

from .models import VisualGraph


def adjacency(graph: VisualGraph):
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source].append((edge.target, edge.id))
        incoming[edge.target].append((edge.source, edge.id))
    return outgoing, incoming


def reachable(graph: VisualGraph, origin: str, direction: str = 'downstream') -> dict:
    node_ids = {node.id for node in graph.nodes}
    if origin not in node_ids:
        raise KeyError(origin)
    outgoing, incoming = adjacency(graph)
    table = incoming if direction == 'upstream' else outgoing
    queue = deque([(origin, 0)])
    seen = {origin}
    edge_ids: set[str] = set()
    max_hops = 0
    while queue:
        current, hops = queue.popleft()
        max_hops = max(max_hops, hops)
        for target, edge_id in table.get(current, []):
            edge_ids.add(edge_id)
            if target not in seen:
                seen.add(target)
                queue.append((target, hops + 1))
    return {'origin': origin, 'direction': direction, 'node_ids': sorted(seen), 'edge_ids': sorted(edge_ids), 'max_hops': max_hops}


def shortest_path(graph: VisualGraph, source: str, target: str) -> dict:
    node_ids = {node.id for node in graph.nodes}
    if source not in node_ids or target not in node_ids:
        raise KeyError(source if source not in node_ids else target)
    outgoing, _ = adjacency(graph)
    queue = deque([source])
    parent: dict[str, tuple[str, str] | None] = {source: None}
    while queue:
        current = queue.popleft()
        if current == target:
            break
        for next_id, edge_id in outgoing.get(current, []):
            if next_id not in parent:
                parent[next_id] = (current, edge_id)
                queue.append(next_id)
    if target not in parent:
        return {'source': source, 'target': target, 'found': False, 'node_ids': [], 'edge_ids': []}
    nodes = [target]
    edges = []
    current = target
    while parent[current] is not None:
        previous, edge_id = parent[current]
        edges.append(edge_id)
        nodes.append(previous)
        current = previous
    nodes.reverse(); edges.reverse()
    return {'source': source, 'target': target, 'found': True, 'node_ids': nodes, 'edge_ids': edges, 'hops': len(edges)}


def compare_graphs(before: VisualGraph, after: VisualGraph) -> dict:
    before_nodes = {node.id: node.to_dict() for node in before.nodes}
    after_nodes = {node.id: node.to_dict() for node in after.nodes}
    before_edges = {edge.id: edge.to_dict() for edge in before.edges}
    after_edges = {edge.id: edge.to_dict() for edge in after.edges}
    added_nodes = sorted(set(after_nodes) - set(before_nodes))
    removed_nodes = sorted(set(before_nodes) - set(after_nodes))
    changed_nodes = sorted(key for key in set(before_nodes) & set(after_nodes) if before_nodes[key] != after_nodes[key])
    added_edges = sorted(set(after_edges) - set(before_edges))
    removed_edges = sorted(set(before_edges) - set(after_edges))
    changed_edges = sorted(key for key in set(before_edges) & set(after_edges) if before_edges[key] != after_edges[key])
    return {
        'before_title': before.title,
        'after_title': after.title,
        'nodes': {'added': added_nodes, 'removed': removed_nodes, 'changed': changed_nodes},
        'edges': {'added': added_edges, 'removed': removed_edges, 'changed': changed_edges},
        'summary': {
            'added': len(added_nodes) + len(added_edges),
            'removed': len(removed_nodes) + len(removed_edges),
            'changed': len(changed_nodes) + len(changed_edges),
        },
    }
