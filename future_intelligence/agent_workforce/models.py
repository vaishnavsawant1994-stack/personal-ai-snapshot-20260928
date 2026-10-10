from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentVersionState(str, Enum):
    CANDIDATE = "candidate"
    EXPERIMENTAL = "experimental"
    STABLE = "stable"
    PREFERRED = "preferred"
    DEGRADED = "degraded"
    ARCHIVED = "archived"


class AgentInstanceState(str, Enum):
    STARTING = "starting"
    IDLE = "idle"
    ASSIGNED = "assigned"
    PLANNING = "planning"
    WORKING = "working"
    WAITING_DEPENDENCY = "waiting_dependency"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_RESOURCE = "waiting_resource"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    RETRYING = "retrying"
    RECOVERING = "recovering"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


ACTIVE_INSTANCE_STATES = {
    AgentInstanceState.ASSIGNED.value,
    AgentInstanceState.PLANNING.value,
    AgentInstanceState.WORKING.value,
    AgentInstanceState.WAITING_DEPENDENCY.value,
    AgentInstanceState.WAITING_APPROVAL.value,
    AgentInstanceState.WAITING_RESOURCE.value,
    AgentInstanceState.VERIFYING.value,
    AgentInstanceState.REVIEWING.value,
    AgentInstanceState.BLOCKED.value,
    AgentInstanceState.RETRYING.value,
    AgentInstanceState.RECOVERING.value,
    AgentInstanceState.PAUSED.value,
}


@dataclass(frozen=True)
class AgentTemplate:
    id: str
    slug: str
    name: str
    role: str
    description: str = ""
    system_owned: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class AgentVersion:
    id: str
    template_id: str
    version: str
    state: AgentVersionState
    instructions: str = ""
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory_policy: str = "project_only"
    model_policy: dict[str, Any] = field(default_factory=dict)
    parent_version_id: str | None = None
    qualification: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    promoted_at: str | None = None


@dataclass(frozen=True)
class AgentInstance:
    id: str
    template_id: str
    version_id: str
    project_id: str | None
    state: AgentInstanceState
    current_work_order_id: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class AgentAssignment:
    id: str
    instance_id: str
    project_id: str
    work_order_id: str
    version_id: str
    status: str = "assigned"
    assigned_at: str = ""
    completed_at: str | None = None


@dataclass(frozen=True)
class AgentTeamMember:
    project_id: str
    instance_id: str
    role: str
    is_manager: bool = False
    joined_at: str = ""


@dataclass(frozen=True)
class AgentEvolutionObservation:
    id: str
    template_id: str
    version_id: str
    project_id: str | None
    work_order_id: str | None
    kind: str
    score: float | None
    summary: str
    evidence_ref: str | None = None
    created_at: str = ""
