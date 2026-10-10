from __future__ import annotations

import re

from .models import EvidenceLevel, VisualEdge, VisualGraph, VisualNode, VisualType


def _id(prefix: str, value) -> str:
    token = re.sub(r'[^a-z0-9]+', '-', str(value or '').casefold()).strip('-')[:110] or 'item'
    return f'{prefix}-{token}'


def build_knowledge_graph(knowledge, *, access_classes: set[str], query: str = '', limit: int = 120, title: str = 'Knowledge Map') -> VisualGraph:
    documents = knowledge.list(query=query, limit=max(1, min(int(limit), 250)), access_classes=set(access_classes))
    nodes: list[VisualNode] = [VisualNode(id='knowledge', label='Knowledge', category='project', description='Owner-authorized Vishnu knowledge map', evidence_level=EvidenceLevel.STRONG, metadata={'privacy_scoped': True})]
    edges: list[VisualEdge] = []
    collections = {str(item.get('id')): item for item in knowledge.collections()}
    used_collections: set[str] = set()
    memory_ids: set[str] = set()

    for index, doc in enumerate(documents, 1):
        document_id = str(doc.get('id'))
        detail = knowledge.detail(document_id, include_history=False) or doc
        metadata = dict(detail.get('metadata') or {})
        collection_id = str(metadata.get('collection_id') or '')
        node_id = _id('knowledge-document', document_id)
        evidence = [{
            'kind': 'knowledge_document', 'document_id': document_id, 'lineage_id': detail.get('lineage_id'),
            'version': detail.get('version'), 'checksum': detail.get('checksum'), 'source': detail.get('source'),
            'filename': detail.get('filename'), 'access_class': detail.get('access_class'),
        }]
        nodes.append(VisualNode(
            id=node_id, label=str(detail.get('title') or detail.get('filename') or f'Document {index}')[:160], category='knowledge',
            description=str(detail.get('source') or 'Knowledge document'), evidence_level=EvidenceLevel.VERIFIED, evidence=evidence,
            metadata={'document_id': document_id, 'lineage_id': detail.get('lineage_id'), 'version': detail.get('version'), 'access_class': detail.get('access_class'), 'updated_at': detail.get('updated_at')},
        ))
        parent = 'knowledge'
        if collection_id and collection_id in collections:
            used_collections.add(collection_id)
            parent = _id('knowledge-collection', collection_id)
        edges.append(VisualEdge(id=f'knowledge-contains-{index}', source=parent, target=node_id, kind='contains', metadata={'evidence': evidence}))
        for link_index, link in enumerate(detail.get('memory_links') or [], 1):
            memory_id = str(link.get('memory_id') or '')
            if not memory_id:
                continue
            memory_ids.add(memory_id)
            memory_node_id = _id('memory-ref', memory_id)
            edges.append(VisualEdge(
                id=f'knowledge-memory-{index}-{link_index}', source=node_id, target=memory_node_id,
                label=str(link.get('relationship') or 'supports'), kind='memory_link',
                metadata={'rationale': str(link.get('rationale') or '')[:500], 'canonical_link_id': link.get('id')},
            ))

    collection_nodes = []
    for collection_id in sorted(used_collections):
        item = collections[collection_id]
        collection_nodes.append(VisualNode(
            id=_id('knowledge-collection', collection_id), label=str(item.get('title') or 'Collection')[:160], category='group',
            description=str(item.get('description') or ''), evidence_level=EvidenceLevel.VERIFIED,
            evidence=[{'kind': 'knowledge_collection', 'collection_id': collection_id}], metadata={'collection_id': collection_id, 'item_count': item.get('item_count')},
        ))
        edges.insert(0, VisualEdge(id=f'knowledge-collection-edge-{_id("x", collection_id)}', source='knowledge', target=_id('knowledge-collection', collection_id), kind='contains'))
    nodes[1:1] = collection_nodes

    for memory_id in sorted(memory_ids):
        nodes.append(VisualNode(
            id=_id('memory-ref', memory_id), label=f'Memory {memory_id[:8]}', category='memory', description='Linked memory reference',
            evidence_level=EvidenceLevel.STRONG, evidence=[{'kind': 'memory_reference', 'memory_id': memory_id}], metadata={'memory_id': memory_id, 'reference_only': True},
        ))
    return VisualGraph(
        type=VisualType.PROJECT_MAP, title=title, nodes=nodes, edges=edges,
        metadata={'analysis': 'vishnu-knowledge-map', 'privacy_scoped': True, 'document_count': len(documents), 'access_classes': sorted(access_classes), 'query': query},
    )


def build_memory_graph(payload: dict, *, title: str = 'Memory Map') -> VisualGraph:
    raw_nodes = list(payload.get('nodes') or [])
    raw_edges = list(payload.get('edges') or [])
    nodes: list[VisualNode] = []
    seen: set[str] = set()
    id_map: dict[str, str] = {}
    for index, item in enumerate(raw_nodes, 1):
        original = str(item.get('id') or item.get('node_id') or index)
        node_id = _id('memory', original)
        while node_id in seen:
            node_id += f'-{index}'
        seen.add(node_id); id_map[original] = node_id
        label = str(item.get('label') or item.get('title') or item.get('name') or item.get('type') or f'Memory {index}')[:160]
        sensitivity = str(item.get('sensitivity') or (item.get('metadata') or {}).get('sensitivity') or 'normal')
        nodes.append(VisualNode(
            id=node_id, label=label, category=str(item.get('type') or item.get('category') or 'memory'),
            description=str(item.get('description') or item.get('summary') or '')[:1000], evidence_level=EvidenceLevel.STRONG,
            evidence=[{'kind': 'canonical_memory_node', 'memory_id': original, 'sensitivity': sensitivity}],
            metadata={**dict(item.get('metadata') or {}), 'canonical_memory_id': original, 'sensitivity': sensitivity, 'privacy_scoped': True},
        ))
    edges: list[VisualEdge] = []
    for index, item in enumerate(raw_edges, 1):
        source = str(item.get('source') or item.get('from') or '')
        target = str(item.get('target') or item.get('to') or '')
        if source not in id_map or target not in id_map:
            continue
        edges.append(VisualEdge(
            id=_id('memory-edge', item.get('id') or index), source=id_map[source], target=id_map[target],
            label=str(item.get('label') or item.get('relationship') or ''), kind=str(item.get('kind') or item.get('type') or 'relationship'),
            metadata={'canonical_edge': dict(item)},
        ))
    return VisualGraph(
        type=VisualType.PROJECT_MAP, title=title, nodes=nodes, edges=edges,
        metadata={'analysis': 'vishnu-memory-map', 'privacy_scoped': True, 'source_node_count': len(raw_nodes), 'source_edge_count': len(raw_edges)},
    )


def build_live_work_graph(project: dict, *, title: str | None = None) -> VisualGraph:
    project_id = str(project.get('id') or project.get('project_id') or 'project')
    root_id = _id('project', project_id)
    nodes = [VisualNode(
        id=root_id, label=str(project.get('name') or 'Project'), category='project', description=str(project.get('goal') or ''),
        status=str(project.get('status') or 'active'), evidence_level=EvidenceLevel.VERIFIED,
        evidence=[{'kind': 'project_record', 'project_id': project_id}], metadata={'project_id': project_id, 'live_work': True},
    )]
    edges: list[VisualEdge] = []
    task_ids: dict[str, str] = {}
    agent_ids: dict[str, str] = {}

    for index, milestone in enumerate(project.get('milestones') or [], 1):
        mid = str(milestone.get('id') or index); node_id = _id('milestone', mid)
        nodes.append(VisualNode(id=node_id, label=str(milestone.get('title') or milestone.get('name') or f'Milestone {index}')[:160], category='milestone', description=str(milestone.get('description') or ''), status=str(milestone.get('status') or 'pending'), evidence_level=EvidenceLevel.VERIFIED, evidence=[{'kind': 'project_milestone', 'project_id': project_id, 'milestone_id': mid}], metadata={'milestone_id': mid}))
        edges.append(VisualEdge(id=f'{root_id}-milestone-{index}', source=root_id, target=node_id, kind='milestone'))

    for index, task in enumerate(project.get('tasks') or [], 1):
        task_key = str(task.get('id') or task.get('task_id') or index); node_id = _id('task', task_key); task_ids[task_key] = node_id
        status = str(task.get('status') or 'pending')
        evidence = [{'kind': 'project_task', 'project_id': project_id, 'task_id': task_key, 'execution_run_id': task.get('execution_run_id')}]
        nodes.append(VisualNode(
            id=node_id, label=str(task.get('title') or task.get('name') or task.get('description') or f'Task {index}')[:160], category='task',
            description=str(task.get('description') or '')[:1000], status=status, evidence_level=EvidenceLevel.VERIFIED, evidence=evidence,
            metadata={'task_id': task_key, 'execution_run_id': task.get('execution_run_id'), 'approval_state': task.get('approval_state'), 'live_work': True},
        ))
        edges.append(VisualEdge(id=f'{root_id}-task-{index}', source=root_id, target=node_id, kind='work_item', metadata={'evidence': evidence}))
        owner = str(task.get('owner') or '').strip()
        if owner:
            agent_id = agent_ids.setdefault(owner, _id('agent', owner))
            if not any(node.id == agent_id for node in nodes):
                nodes.append(VisualNode(id=agent_id, label=owner.title(), category='agent', status='active' if status == 'in_progress' else 'available', evidence_level=EvidenceLevel.VERIFIED, evidence=[{'kind': 'project_task_owner', 'project_id': project_id, 'owner': owner}], metadata={'owner': owner, 'live_work': True}))
            edges.append(VisualEdge(id=f'{agent_id}-task-{index}', source=agent_id, target=node_id, kind='executes'))
        run_id = str(task.get('execution_run_id') or '').strip()
        if run_id:
            run_node_id = _id('run', run_id)
            nodes.append(VisualNode(id=run_node_id, label=f'Run {run_id[:10]}', category='execution', status=status, evidence_level=EvidenceLevel.VERIFIED, evidence=[{'kind': 'execution_run', 'run_id': run_id, 'task_id': task_key}], metadata={'execution_run_id': run_id, 'live_work': True}))
            edges.append(VisualEdge(id=f'{node_id}-run', source=node_id, target=run_node_id, kind='execution'))

    for task in project.get('tasks') or []:
        source_key = str(task.get('id') or task.get('task_id') or '')
        source_id = task_ids.get(source_key)
        if not source_id:
            continue
        deps = task.get('depends_on') or task.get('dependencies') or []
        if isinstance(deps, str): deps = [deps]
        for dep in deps:
            target_id = task_ids.get(str(dep))
            if target_id:
                edges.append(VisualEdge(id=f'dep-{source_id}-{target_id}', source=target_id, target=source_id, kind='depends_on'))

    for index, item in enumerate(project.get('files') or [], 1):
        file_id = str(item.get('id') or index); node_id = _id('source', file_id)
        nodes.append(VisualNode(id=node_id, label=str(item.get('title') or item.get('filename') or f'Source {index}')[:160], category='source', status=str(item.get('indexing_state') or 'stored'), evidence_level=EvidenceLevel.VERIFIED, evidence=[{'kind': 'project_file', 'project_id': project_id, 'file_id': file_id}], metadata={'file_id': file_id, 'kind': item.get('kind')}))
        edges.append(VisualEdge(id=f'{root_id}-source-{index}', source=root_id, target=node_id, kind='source'))

    return VisualGraph(
        type=VisualType.PROJECT_MAP, title=title or f"{project.get('name') or 'Project'} · Live Work", nodes=nodes, edges=edges,
        metadata={'analysis': 'vishnu-live-work', 'project_id': project_id, 'live': True, 'canonical_work_state': True},
    )
