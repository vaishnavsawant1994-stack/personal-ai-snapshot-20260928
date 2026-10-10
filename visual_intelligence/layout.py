from __future__ import annotations

from collections import defaultdict, deque

from .models import VisualGraph


def layout_graph(graph: VisualGraph) -> VisualGraph:
    """Apply a deterministic layered layout only to nodes without authored coordinates."""
    if not graph.nodes:
        return graph
    by_id = {node.id: node for node in graph.nodes}
    incoming: dict[str, int] = {node.id: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source in by_id and edge.target in by_id:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target] += 1

    roots = sorted((node_id for node_id, count in incoming.items() if count == 0)) or [sorted(by_id)[0]]
    level: dict[str, int] = {}
    queue = deque((root, 0) for root in roots)
    while queue:
        node_id, depth = queue.popleft()
        old = level.get(node_id)
        if old is not None and old <= depth:
            continue
        level[node_id] = depth
        for target in sorted(outgoing.get(node_id, [])):
            queue.append((target, depth + 1))
    for node_id in sorted(by_id):
        level.setdefault(node_id, 0)

    levels: dict[int, list[str]] = defaultdict(list)
    for node_id, depth in level.items():
        levels[depth].append(node_id)

    x_gap, y_gap = 260.0, 128.0
    for depth in sorted(levels):
        ids = sorted(levels[depth])
        for row, node_id in enumerate(ids):
            node = by_id[node_id]
            if node.x is None:
                node.x = 70.0 + depth * x_gap
            if node.y is None:
                node.y = 70.0 + row * y_gap
    return graph
