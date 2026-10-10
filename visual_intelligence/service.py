from __future__ import annotations

from pathlib import Path
from typing import Any

from .analyzer import analyze
from .editing import apply_instruction, repair_graph
from .exporters import export_graph, supported_export_formats
from .graph_ops import compare_graphs, reachable, shortest_path
from .layout import layout_graph
from .models import VisualGraph, VisualMode, VisualType
from .projections import presentation_projection, scene_projection
from .renderer import render_html, render_svg
from .store import VisualStore
from .validator import assert_valid_graph, validate_graph


class VisualIntelligenceService:
    def __init__(self, path: str | Path, *, events=None):
        self.store = VisualStore(path)
        self.events = events

    def _emit(self, name: str, **payload):
        if self.events is not None:
            self.events.emit(name, **payload)

    def _prepare(self, graph: VisualGraph) -> VisualGraph:
        """Compile a graph through layout -> validate -> deterministic repair -> validate.

        A failed candidate never reaches the store, so the last persisted revision remains
        authoritative. Repairs are recorded in graph metadata as machine-readable receipts.
        """
        layout_graph(graph)
        issues = validate_graph(graph)
        if issues:
            repaired, receipt = repair_graph(graph)
            layout_graph(repaired)
            assert_valid_graph(repaired)
            repaired.metadata['validation_repair'] = receipt
            graph.title = repaired.title
            graph.type = repaired.type
            graph.nodes = repaired.nodes
            graph.edges = repaired.edges
            graph.views = repaired.views
            graph.metadata = repaired.metadata
        assert_valid_graph(graph)
        return graph

    def create(
        self,
        *,
        owner_id: str,
        title: str,
        visual_type: str | VisualType = VisualType.ARCHITECTURE,
        mode: str | VisualMode = VisualMode.MANUAL,
        description: str = '',
        context: dict[str, Any] | None = None,
        graph: dict[str, Any] | VisualGraph | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        source_kind: str = 'description',
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        visual_type = visual_type if isinstance(visual_type, VisualType) else VisualType(str(visual_type))
        mode = mode if isinstance(mode, VisualMode) else VisualMode(str(mode))
        title = str(title or 'Untitled visual').strip()[:160]
        if graph is None:
            typed = analyze(description, visual_type, title, context=context)
        elif isinstance(graph, VisualGraph):
            typed = graph
        else:
            typed = VisualGraph.from_dict(graph)
            typed.title = title
            typed.type = visual_type
        self._prepare(typed)
        created = self.store.create(
            owner_id=owner_id,
            title=title,
            visual_type=visual_type,
            mode=mode,
            graph=typed,
            project_id=project_id,
            conversation_id=conversation_id,
            source_kind=source_kind,
            source_ref=source_ref,
            description=description,
        )
        self._emit('visualization.created', visualization_id=created['id'], owner_id=owner_id, type=visual_type.value, project_id=project_id)
        return self.enrich(created)

    def enrich(self, item: dict[str, Any]) -> dict[str, Any]:
        graph = VisualGraph.from_dict(item['graph'])
        result = dict(item)
        result['graph'] = graph.to_dict()
        result['node_count'] = len(graph.nodes)
        result['edge_count'] = len(graph.edges)
        issues = [issue.to_dict() for issue in validate_graph(graph)]
        result['validation'] = {'ok': not issues, 'issues': issues}
        result['svg'] = render_svg(graph)
        result['capabilities'] = {
            'edit': True, 'repair': True, 'presentation': True, 'scene_2d': True, 'scene_3d': True,
            'exports': supported_export_formats(), 'last_good_persistence': True,
        }
        return result

    def list(self, owner_id: str, *, project_id: str | None = None, limit: int = 100):
        return [self.enrich(item) for item in self.store.list(owner_id, project_id=project_id, limit=limit)]

    def get(self, owner_id: str, visual_id: str):
        item = self.store.get(owner_id, visual_id)
        return self.enrich(item) if item else None

    def update(self, owner_id: str, visual_id: str, *, title: str | None = None, mode: str | VisualMode | None = None, graph: dict[str, Any] | None = None, reason: str = 'update'):
        current = self.store.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        if graph is not None:
            typed = VisualGraph.from_dict(graph)
            typed.title = str(title or current['title'])
            self._prepare(typed)
            return self.enrich(self.store.update_graph(owner_id, visual_id, typed, reason=reason, title=title))
        parsed_mode = None if mode is None else (mode if isinstance(mode, VisualMode) else VisualMode(str(mode)))
        return self.enrich(self.store.patch(owner_id, visual_id, title=title, mode=parsed_mode))

    def edit(self, owner_id: str, visual_id: str, instruction: str):
        current = self.store.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        graph = VisualGraph.from_dict(current['graph'])
        edited, receipt = apply_instruction(graph, instruction)
        self._prepare(edited)
        updated = self.store.update_graph(owner_id, visual_id, edited, reason=f'natural-language edit: {instruction[:80]}')
        result = self.enrich(updated)
        self._emit('visualization.edited', visualization_id=visual_id, owner_id=owner_id, operations=receipt.operations)
        return {'visualization': result, 'receipt': receipt.to_dict()}

    def repair(self, owner_id: str, visual_id: str):
        current = self.store.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        graph = VisualGraph.from_dict(current['graph'])
        repaired, receipt = repair_graph(graph)
        self._prepare(repaired)
        if receipt['repairs']:
            current = self.store.update_graph(owner_id, visual_id, repaired, reason='deterministic validation repair')
        result = self.enrich(current)
        self._emit('visualization.repaired', visualization_id=visual_id, owner_id=owner_id, repair_count=len(receipt['repairs']))
        return {'visualization': result, 'receipt': receipt}

    def refresh(self, owner_id: str, visual_id: str, *, description: str | None = None, context: dict[str, Any] | None = None, reason: str = 'refresh'):
        current = self.store.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        description = current['description'] if description is None else str(description)
        graph = analyze(description, VisualType(current['type']), current['title'], context=context)
        self._prepare(graph)
        return self.enrich(self.store.update_graph(owner_id, visual_id, graph, reason=reason))

    def revisions(self, owner_id: str, visual_id: str):
        if self.store.get(owner_id, visual_id) is None:
            raise KeyError(visual_id)
        return self.store.revisions(owner_id, visual_id)

    def reach(self, owner_id: str, visual_id: str, origin: str, direction: str = 'downstream'):
        item = self.store.get(owner_id, visual_id)
        if item is None:
            raise KeyError(visual_id)
        return reachable(VisualGraph.from_dict(item['graph']), origin, direction)

    def path(self, owner_id: str, visual_id: str, source: str, target: str):
        item = self.store.get(owner_id, visual_id)
        if item is None:
            raise KeyError(visual_id)
        return shortest_path(VisualGraph.from_dict(item['graph']), source, target)

    def compare(self, owner_id: str, before_id: str, after_id: str):
        before = self.store.get(owner_id, before_id); after = self.store.get(owner_id, after_id)
        if before is None: raise KeyError(before_id)
        if after is None: raise KeyError(after_id)
        return compare_graphs(VisualGraph.from_dict(before['graph']), VisualGraph.from_dict(after['graph']))

    def presentation(self, owner_id: str, visual_id: str):
        item = self.store.get(owner_id, visual_id)
        if item is None: raise KeyError(visual_id)
        return presentation_projection(VisualGraph.from_dict(item['graph']))

    def scene(self, owner_id: str, visual_id: str, *, dimension: str = '3d'):
        item = self.store.get(owner_id, visual_id)
        if item is None: raise KeyError(visual_id)
        return scene_projection(VisualGraph.from_dict(item['graph']), dimension=dimension)

    def export(self, owner_id: str, visual_id: str, fmt: str):
        item = self.store.get(owner_id, visual_id)
        if item is None: raise KeyError(visual_id)
        return export_graph(VisualGraph.from_dict(item['graph']), fmt)

    def artifact(self, owner_id: str, visual_id: str) -> str:
        item = self.store.get(owner_id, visual_id)
        if item is None: raise KeyError(visual_id)
        return render_html(VisualGraph.from_dict(item['graph']))

    def delete(self, owner_id: str, visual_id: str) -> bool:
        deleted = self.store.delete(owner_id, visual_id)
        if deleted:
            self._emit('visualization.deleted', visualization_id=visual_id, owner_id=owner_id)
        return deleted

    def close(self):
        self.store.close()