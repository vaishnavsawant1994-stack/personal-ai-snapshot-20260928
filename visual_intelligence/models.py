from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VisualType(str, Enum):
    ARCHITECTURE = 'architecture'
    WORKFLOW = 'workflow'
    SEQUENCE = 'sequence'
    DATAFLOW = 'dataflow'
    LIFECYCLE = 'lifecycle'
    PROJECT_MAP = 'project_map'


class VisualMode(str, Enum):
    LIVE = 'live'
    MANUAL = 'manual'
    SNAPSHOT = 'snapshot'


class EvidenceLevel(str, Enum):
    VERIFIED = 'verified'
    STRONG = 'strong'
    INFERRED = 'inferred'
    USER_SUPPLIED = 'user_supplied'
    UNVERIFIED = 'unverified'


@dataclass(slots=True)
class VisualNode:
    id: str
    label: str
    category: str = 'component'
    description: str = ''
    x: float | None = None
    y: float | None = None
    width: float = 190.0
    height: float = 72.0
    status: str = 'active'
    evidence_level: EvidenceLevel = EvidenceLevel.UNVERIFIED
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'category': self.category,
            'description': self.description,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'status': self.status,
            'evidence_level': self.evidence_level.value,
            'evidence': list(self.evidence),
            'metadata': dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> 'VisualNode':
        return cls(
            id=str(value['id']),
            label=str(value.get('label') or value['id']),
            category=str(value.get('category') or 'component'),
            description=str(value.get('description') or ''),
            x=float(value['x']) if value.get('x') is not None else None,
            y=float(value['y']) if value.get('y') is not None else None,
            width=float(value.get('width') or 190),
            height=float(value.get('height') or 72),
            status=str(value.get('status') or 'active'),
            evidence_level=EvidenceLevel(str(value.get('evidence_level') or EvidenceLevel.UNVERIFIED.value)),
            evidence=list(value.get('evidence') or []),
            metadata=dict(value.get('metadata') or {}),
        )


@dataclass(slots=True)
class VisualEdge:
    id: str
    source: str
    target: str
    label: str = ''
    kind: str = 'relationship'
    directed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'source': self.source,
            'target': self.target,
            'label': self.label,
            'kind': self.kind,
            'directed': self.directed,
            'metadata': dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> 'VisualEdge':
        return cls(
            id=str(value['id']),
            source=str(value['source']),
            target=str(value['target']),
            label=str(value.get('label') or ''),
            kind=str(value.get('kind') or 'relationship'),
            directed=bool(value.get('directed', True)),
            metadata=dict(value.get('metadata') or {}),
        )


@dataclass(slots=True)
class VisualGraph:
    type: VisualType
    title: str
    nodes: list[VisualNode] = field(default_factory=list)
    edges: list[VisualEdge] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'type': self.type.value,
            'title': self.title,
            'nodes': [node.to_dict() for node in self.nodes],
            'edges': [edge.to_dict() for edge in self.edges],
            'views': list(self.views),
            'metadata': dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> 'VisualGraph':
        return cls(
            type=VisualType(str(value.get('type') or VisualType.ARCHITECTURE.value)),
            title=str(value.get('title') or 'Untitled visual'),
            nodes=[VisualNode.from_dict(item) for item in value.get('nodes') or []],
            edges=[VisualEdge.from_dict(item) for item in value.get('edges') or []],
            views=list(value.get('views') or []),
            metadata=dict(value.get('metadata') or {}),
        )
