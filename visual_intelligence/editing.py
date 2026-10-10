from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass

from .models import VisualEdge, VisualGraph, VisualNode
from .validator import validate_graph


@dataclass(slots=True)
class EditReceipt:
    instruction: str
    operations: list[dict]
    changed: bool

    def to_dict(self):
        return {'instruction': self.instruction, 'operations': list(self.operations), 'changed': self.changed}


def _copy(graph: VisualGraph) -> VisualGraph:
    return VisualGraph.from_dict(graph.to_dict())


def _find_node(graph: VisualGraph, token: str) -> VisualNode | None:
    needle = str(token or '').strip().casefold()
    if not needle:
        return None
    exact = [node for node in graph.nodes if node.id.casefold() == needle or node.label.casefold() == needle]
    if exact:
        return exact[0]
    partial = [node for node in graph.nodes if needle in node.label.casefold()]
    return partial[0] if len(partial) == 1 else None


def _split_names(value: str) -> list[str]:
    return [item.strip() for item in re.split(r'\s*,\s*|\s+and\s+', value, flags=re.I) if item.strip()]


def apply_instruction(graph: VisualGraph, instruction: str) -> tuple[VisualGraph, EditReceipt]:
    """Apply a conservative, auditable natural-language visual edit.

    The parser intentionally supports explicit visual operations only. It never invents
    architectural facts. Semantic additions must come from source analysis or a graph
    supplied by Vishnu's governed reasoning path.
    """
    result = _copy(graph)
    text = str(instruction or '').strip()
    lowered = text.casefold()
    operations: list[dict] = []
    if not text:
        raise ValueError('An edit instruction is required')

    match = re.match(r'^rename\s+(.+?)\s+to\s+(.+)$', text, re.I)
    if match:
        node = _find_node(result, match.group(1))
        if node is None:
            raise ValueError(f'Node not found or ambiguous: {match.group(1)}')
        old = node.label
        node.label = match.group(2).strip()[:160]
        if not node.label:
            raise ValueError('The new node label cannot be empty')
        operations.append({'op': 'rename', 'node_id': node.id, 'before': old, 'after': node.label})
        return result, EditReceipt(text, operations, True)

    match = re.match(r'^move\s+(.+?)\s+(left|right|up|down)(?:\s+(\d+(?:\.\d+)?))?$', text, re.I)
    if match:
        node = _find_node(result, match.group(1))
        if node is None:
            raise ValueError(f'Node not found or ambiguous: {match.group(1)}')
        amount = min(1200.0, max(10.0, float(match.group(3) or 120)))
        if node.x is None or node.y is None:
            raise ValueError('The node must be laid out before it can be moved')
        before = {'x': node.x, 'y': node.y}
        direction = match.group(2).casefold()
        if direction == 'left': node.x -= amount
        elif direction == 'right': node.x += amount
        elif direction == 'up': node.y -= amount
        else: node.y += amount
        operations.append({'op': 'move', 'node_id': node.id, 'direction': direction, 'amount': amount, 'before': before, 'after': {'x': node.x, 'y': node.y}})
        return result, EditReceipt(text, operations, True)

    match = re.match(r'^move\s+(.+?)\s+to\s+(-?\d+(?:\.\d+)?)\s*[,x ]\s*(-?\d+(?:\.\d+)?)$', text, re.I)
    if match:
        node = _find_node(result, match.group(1))
        if node is None:
            raise ValueError(f'Node not found or ambiguous: {match.group(1)}')
        before = {'x': node.x, 'y': node.y}
        node.x, node.y = float(match.group(2)), float(match.group(3))
        operations.append({'op': 'move_absolute', 'node_id': node.id, 'before': before, 'after': {'x': node.x, 'y': node.y}})
        return result, EditReceipt(text, operations, True)

    match = re.match(r'^(unhighlight|highlight)\s+(.+)$', text, re.I)
    if match:
        node = _find_node(result, match.group(2))
        if node is None:
            raise ValueError(f'Node not found or ambiguous: {match.group(2)}')
        value = match.group(1).casefold() == 'highlight'
        node.metadata['highlight'] = value
        operations.append({'op': 'highlight', 'node_id': node.id, 'value': value})
        return result, EditReceipt(text, operations, True)

    match = re.match(r'^show\s+only\s+(.+)$', text, re.I)
    if match:
        requested = _split_names(match.group(1))
        ids = []
        missing = []
        for name in requested:
            node = _find_node(result, name)
            if node is None: missing.append(name)
            else: ids.append(node.id)
        if missing:
            raise ValueError('Nodes not found or ambiguous: ' + ', '.join(missing))
        result.metadata['preferred_focus'] = ids
        operations.append({'op': 'preferred_focus', 'node_ids': ids})
        return result, EditReceipt(text, operations, True)

    match = re.match(r'^group\s+(.+?)\s+as\s+(.+)$', text, re.I)
    if match:
        members = []
        for name in _split_names(match.group(1)):
            node = _find_node(result, name)
            if node is None:
                raise ValueError(f'Node not found or ambiguous: {name}')
            members.append(node)
        group_label = match.group(2).strip()[:160]
        group_id = 'group-' + re.sub(r'[^a-z0-9]+', '-', group_label.casefold()).strip('-')[:80]
        if not group_id or group_id == 'group-':
            group_id = 'group-' + uuid.uuid4().hex[:10]
        existing = {node.id for node in result.nodes}
        if group_id in existing:
            group_id += '-' + uuid.uuid4().hex[:6]
        xs = [node.x for node in members if node.x is not None]
        ys = [node.y for node in members if node.y is not None]
        result.nodes.append(VisualNode(id=group_id, label=group_label, category='group', description='Owner-defined visual grouping', x=(sum(xs)/len(xs) if xs else None), y=(sum(ys)/len(ys) if ys else None), metadata={'member_ids': [node.id for node in members], 'visual_only': True}))
        for index, node in enumerate(members, 1):
            result.edges.append(VisualEdge(id=f'{group_id}-member-{index}', source=group_id, target=node.id, kind='groups', metadata={'visual_only': True}))
        operations.append({'op': 'group', 'group_id': group_id, 'member_ids': [node.id for node in members]})
        return result, EditReceipt(text, operations, True)

    if lowered in {'reset layout', 'relayout', 're-layout', 'auto layout'}:
        for node in result.nodes:
            node.x = None; node.y = None
        operations.append({'op': 'reset_layout', 'node_count': len(result.nodes)})
        return result, EditReceipt(text, operations, True)

    if lowered in {'simplify', 'simplify diagram', 'simplify visual'}:
        result.metadata['presentation_filter'] = {'hide_evidence_below': 'strong', 'preserve_canonical_graph': True}
        operations.append({'op': 'presentation_filter', 'value': result.metadata['presentation_filter']})
        return result, EditReceipt(text, operations, True)

    raise ValueError('Unsupported edit. Try: move <node> left/right/up/down, move <node> to x,y, rename <node> to <name>, highlight <node>, show only <nodes>, group <nodes> as <name>, simplify, or reset layout.')


def repair_graph(graph: VisualGraph) -> tuple[VisualGraph, dict]:
    """Deterministically repair structural defects and return a machine-readable receipt."""
    result = _copy(graph)
    before = [issue.to_dict() for issue in validate_graph(result)]
    repairs: list[dict] = []
    if not result.title.strip():
        result.title = 'Untitled visual'
        repairs.append({'op': 'title_defaulted'})

    seen: set[str] = set()
    id_map: dict[str, str] = {}
    for index, node in enumerate(result.nodes, 1):
        original = node.id
        clean = str(node.id or '').strip() or f'node-{index}'
        candidate = clean
        suffix = 2
        while candidate in seen:
            candidate = f'{clean}-{suffix}'; suffix += 1
        if candidate != original:
            id_map[original] = candidate
            node.id = candidate
            repairs.append({'op': 'node_id_repaired', 'before': original, 'after': candidate})
        seen.add(node.id)
        if not node.label.strip():
            node.label = node.id
            repairs.append({'op': 'node_label_defaulted', 'node_id': node.id})
        if node.width < 80:
            node.width = 80
            repairs.append({'op': 'node_width_clamped', 'node_id': node.id})
        if node.height < 40:
            node.height = 40
            repairs.append({'op': 'node_height_clamped', 'node_id': node.id})
        if node.x is not None and not math.isfinite(node.x):
            node.x = None; repairs.append({'op': 'node_x_reset', 'node_id': node.id})
        if node.y is not None and not math.isfinite(node.y):
            node.y = None; repairs.append({'op': 'node_y_reset', 'node_id': node.id})

    valid_ids = {node.id for node in result.nodes}
    edge_seen: set[str] = set()
    repaired_edges = []
    for index, edge in enumerate(result.edges, 1):
        if edge.source in id_map: edge.source = id_map[edge.source]
        if edge.target in id_map: edge.target = id_map[edge.target]
        if edge.source not in valid_ids or edge.target not in valid_ids or (edge.source == edge.target and not edge.metadata.get('allow_self_loop')):
            repairs.append({'op': 'edge_removed', 'edge_id': edge.id, 'reason': 'invalid_endpoint_or_self_loop'})
            continue
        base = str(edge.id or '').strip() or f'edge-{index}'
        candidate = base; suffix = 2
        while candidate in edge_seen:
            candidate = f'{base}-{suffix}'; suffix += 1
        if candidate != edge.id:
            repairs.append({'op': 'edge_id_repaired', 'before': edge.id, 'after': candidate})
            edge.id = candidate
        edge_seen.add(edge.id)
        repaired_edges.append(edge)
    result.edges = repaired_edges
    after = [issue.to_dict() for issue in validate_graph(result)]
    return result, {'before': before, 'repairs': repairs, 'after': after, 'ok': not after}
