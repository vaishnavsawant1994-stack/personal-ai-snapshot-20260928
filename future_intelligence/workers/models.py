from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from future_intelligence.work_orchestration.models import ReadinessStatus


@dataclass(frozen=True)
class WorkerProfile:
    id: str
    description: str
    supported_capabilities: tuple[str, ...] = ()
    can_propose_tools: bool = True
    requires_tool: bool = False
    allow_any_available_tool: bool = False
    output_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.description.strip():
            raise ValueError("worker id and description are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "supported_capabilities": list(self.supported_capabilities),
            "can_propose_tools": self.can_propose_tools,
            "requires_tool": self.requires_tool,
            "allow_any_available_tool": self.allow_any_available_tool,
            "output_kinds": list(self.output_kinds),
            "authority": "proposal_only",
        }


@dataclass(frozen=True)
class WorkerAssignment:
    work_order_id: str
    worker_id: str
    selected_tool: str | None = None
    candidate_tools: tuple[str, ...] = ()
    matched_capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "worker_id": self.worker_id,
            "selected_tool": self.selected_tool,
            "candidate_tools": list(self.candidate_tools),
            "matched_capabilities": list(self.matched_capabilities),
            "metadata": dict(self.metadata),
            "authority": "proposal_only",
            "execution_authority": "existing_p10_p6_tool_registry",
        }


@dataclass(frozen=True)
class WorkerAssessment:
    status: ReadinessStatus
    score: float
    assignments: tuple[WorkerAssignment, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "assignments": [item.to_dict() for item in self.assignments],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "authority": "proposal_only",
        }
