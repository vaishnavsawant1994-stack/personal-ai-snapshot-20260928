from __future__ import annotations

import math
from dataclasses import dataclass

from .models import VisualGraph


@dataclass(slots=True, frozen=True)
class ValidationIssue:
    code: str
    message: str
    object_id: str | None = None

    def to_dict(self):
        return {'code': self.code, 'message': self.message, 'object_id': self.object_id}


class VisualValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__('; '.join(issue.message for issue in issues))


def validate_graph(graph: VisualGraph, *, max_nodes: int = 500, max_edges: int = 1500) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not graph.title.strip():
        issues.append(ValidationIssue('title_required', 'Visual title is required.'))
    if len(graph.nodes) > max_nodes:
        issues.append(ValidationIssue('too_many_nodes', f'Visual exceeds {max_nodes} nodes.'))
    if len(graph.edges) > max_edges:
        issues.append(ValidationIssue('too_many_edges', f'Visual exceeds {max_edges} relationships.'))

    node_ids: set[str] = set()
    for node in graph.nodes:
        if not node.id.strip():
            issues.append(ValidationIssue('node_id_required', 'Every node needs a stable ID.'))
            continue
        if node.id in node_ids:
            issues.append(ValidationIssue('duplicate_node_id', f'Duplicate node ID: {node.id}', node.id))
        node_ids.add(node.id)
        if not node.label.strip():
            issues.append(ValidationIssue('node_label_required', 'Node label is required.', node.id))
        if node.width < 80 or node.height < 40:
            issues.append(ValidationIssue('node_too_small', 'Node size is below the legibility floor.', node.id))
        for coordinate in (node.x, node.y):
            if coordinate is not None and not math.isfinite(coordinate):
                issues.append(ValidationIssue('invalid_coordinate', 'Node coordinates must be finite.', node.id))

    edge_ids: set[str] = set()
    for edge in graph.edges:
        if edge.id in edge_ids:
            issues.append(ValidationIssue('duplicate_edge_id', f'Duplicate relationship ID: {edge.id}', edge.id))
        edge_ids.add(edge.id)
        if edge.source not in node_ids:
            issues.append(ValidationIssue('missing_edge_source', f'Unknown relationship source: {edge.source}', edge.id))
        if edge.target not in node_ids:
            issues.append(ValidationIssue('missing_edge_target', f'Unknown relationship target: {edge.target}', edge.id))
        if edge.source == edge.target and not bool(edge.metadata.get('allow_self_loop')):
            issues.append(ValidationIssue('self_loop_not_allowed', 'Self relationships require allow_self_loop.', edge.id))
    return issues


def assert_valid_graph(graph: VisualGraph) -> VisualGraph:
    issues = validate_graph(graph)
    if issues:
        raise VisualValidationError(issues)
    return graph
