from __future__ import annotations

import re
from hashlib import sha1
from typing import Any

from .models import EvidenceLevel, VisualEdge, VisualGraph, VisualNode, VisualType


def _slug(value: str) -> str:
    cleaned = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')[:48]
    return cleaned or sha1(value.encode('utf-8')).hexdigest()[:10]


def _node(label: str, *, category: str = 'component', description: str = '', evidence_level=EvidenceLevel.USER_SUPPLIED):
    return VisualNode(id=_slug(label), label=label.strip(), category=category, description=description, evidence_level=evidence_level)


def _from_chain(description: str, visual_type: VisualType, title: str) -> VisualGraph | None:
    candidates = [line.strip(' -\t') for line in description.splitlines() if '->' in line or '→' in line]
    if not candidates and ('->' in description or '→' in description):
        candidates = [description]
    if not candidates:
        return None
    nodes: dict[str, VisualNode] = {}
    edges: list[VisualEdge] = []
    edge_count = 0
    for line in candidates:
        labels = [part.strip(' .') for part in re.split(r'\s*(?:->|→)\s*', line) if part.strip(' .')]
        for label in labels:
            node = _node(label)
            nodes.setdefault(node.id, node)
        for source_label, target_label in zip(labels, labels[1:]):
            source, target = _slug(source_label), _slug(target_label)
            edge_count += 1
            edges.append(VisualEdge(id=f'e{edge_count}-{source}-{target}', source=source, target=target, kind='flow'))
    return VisualGraph(type=visual_type, title=title, nodes=list(nodes.values()), edges=edges, metadata={'analysis': 'explicit-chain'})


def _from_project_context(context: dict[str, Any], title: str) -> VisualGraph:
    root = _node(title, category='project', evidence_level=EvidenceLevel.STRONG)
    nodes = [root]
    edges: list[VisualEdge] = []
    edge_index = 0
    groups = [
        ('goals', 'Goals', 'goal'),
        ('tasks', 'Tasks', 'task'),
        ('milestones', 'Milestones', 'milestone'),
        ('agents', 'Agents', 'agent'),
        ('tools', 'Tools', 'tool'),
        ('sources', 'Sources', 'source'),
        ('work', 'Live work', 'work'),
    ]
    for key, label, category in groups:
        values = context.get(key) or []
        if isinstance(values, dict):
            values = list(values.values())
        if not isinstance(values, list) or not values:
            continue
        group = _node(label, category='group', evidence_level=EvidenceLevel.STRONG)
        group.id = f'group-{key}'
        nodes.append(group)
        edge_index += 1
        edges.append(VisualEdge(id=f'e{edge_index}', source=root.id, target=group.id, kind='contains'))
        for index, item in enumerate(values[:30]):
            if isinstance(item, dict):
                item_label = str(item.get('title') or item.get('name') or item.get('label') or item.get('id') or f'{label} {index + 1}')
                description = str(item.get('description') or item.get('summary') or '')
                status = str(item.get('status') or 'active')
                metadata = {k: v for k, v in item.items() if k not in {'title', 'name', 'label', 'description', 'summary'}}
            else:
                item_label, description, status, metadata = str(item), '', 'active', {}
            child = _node(item_label, category=category, description=description, evidence_level=EvidenceLevel.STRONG)
            child.id = f'{key}-{_slug(item_label)}-{index + 1}'
            child.status = status
            child.metadata.update(metadata)
            nodes.append(child)
            edge_index += 1
            edges.append(VisualEdge(id=f'e{edge_index}', source=group.id, target=child.id, kind='contains'))
    return VisualGraph(type=VisualType.PROJECT_MAP, title=title, nodes=nodes, edges=edges, metadata={'analysis': 'project-context'})


def analyze(description: str, visual_type: VisualType, title: str, context: dict[str, Any] | None = None) -> VisualGraph:
    description = str(description or '').strip()
    context = dict(context or {})
    if visual_type is VisualType.PROJECT_MAP and context:
        return _from_project_context(context, title)
    explicit = _from_chain(description, visual_type, title)
    if explicit is not None:
        return explicit

    root = _node(title, category='focus')
    root.description = description[:600]
    nodes = [root]
    edges: list[VisualEdge] = []
    bullets = []
    for line in description.splitlines():
        line = re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', '', line).strip()
        if line and line.casefold() != title.casefold():
            bullets.append(line)
    if not bullets:
        sentence_parts = [part.strip() for part in re.split(r'[.;]\s+', description) if part.strip()]
        bullets = sentence_parts[1:7] if len(sentence_parts) > 1 else []
    labels = bullets[:12] or ['Inputs', 'Analysis', 'Execution', 'Verification', 'Output']
    previous = root.id
    for index, label in enumerate(labels, 1):
        child = _node(label[:80], category='step' if visual_type in {VisualType.WORKFLOW, VisualType.SEQUENCE, VisualType.LIFECYCLE} else 'component')
        child.id = f'n{index}-{_slug(label)}'
        nodes.append(child)
        source = previous if visual_type in {VisualType.WORKFLOW, VisualType.SEQUENCE, VisualType.LIFECYCLE, VisualType.DATAFLOW} else root.id
        edges.append(VisualEdge(id=f'e{index}', source=source, target=child.id, kind='flow' if source == previous else 'relationship'))
        if visual_type in {VisualType.WORKFLOW, VisualType.SEQUENCE, VisualType.LIFECYCLE, VisualType.DATAFLOW}:
            previous = child.id
    return VisualGraph(type=visual_type, title=title, nodes=nodes, edges=edges, metadata={'analysis': 'description'})
