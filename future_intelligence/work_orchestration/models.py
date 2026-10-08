from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReadinessStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    HOLD = "hold"


class WorkPlanStatus(StrEnum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    READY = "ready"
    DEGRADED = "degraded"
    HOLD = "hold"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrderStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_RESOURCE = "waiting_resource"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


@dataclass(frozen=True)
class ResourceScope:
    allowed_repositories: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    allowed_connectors: tuple[str, ...] = ()
    allowed_destinations: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_repositories": list(self.allowed_repositories),
            "allowed_paths": list(self.allowed_paths),
            "allowed_connectors": list(self.allowed_connectors),
            "allowed_destinations": list(self.allowed_destinations),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ResourceScope":
        data = data or {}
        return cls(
            allowed_repositories=_tuple(data.get("allowed_repositories")),
            allowed_paths=_tuple(data.get("allowed_paths")),
            allowed_connectors=_tuple(data.get("allowed_connectors")),
            allowed_destinations=_tuple(data.get("allowed_destinations")),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True)
class ExecutionBudget:
    max_cost: float | None = None
    max_runtime_seconds: int | None = None
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if self.max_cost is not None and self.max_cost < 0:
            raise ValueError("max_cost must be non-negative")
        if self.max_runtime_seconds is not None and self.max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds must be non-negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cost": self.max_cost,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ExecutionBudget":
        data = data or {}
        return cls(
            max_cost=data.get("max_cost"),
            max_runtime_seconds=data.get("max_runtime_seconds"),
            max_attempts=int(data.get("max_attempts", 1)),
        )


@dataclass(frozen=True)
class EvidenceRequirement:
    kind: str
    required: bool = True
    min_count: int = 1
    min_provenance: str = "tool_verified"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("evidence requirement kind is required")
        if self.min_count < 1:
            raise ValueError("min_count must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "required": self.required,
            "min_count": self.min_count,
            "min_provenance": self.min_provenance,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceRequirement":
        return cls(
            kind=str(data.get("kind", "")),
            required=bool(data.get("required", True)),
            min_count=int(data.get("min_count", 1)),
            min_provenance=str(data.get("min_provenance", "tool_verified")),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True)
class EvidenceContract:
    requirements: tuple[EvidenceRequirement, ...] = ()
    require_review: bool = True
    require_retest: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": [item.to_dict() for item in self.requirements],
            "require_review": self.require_review,
            "require_retest": self.require_retest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "EvidenceContract":
        data = data or {}
        return cls(
            requirements=tuple(EvidenceRequirement.from_dict(item) for item in data.get("requirements", [])),
            require_review=bool(data.get("require_review", True)),
            require_retest=bool(data.get("require_retest", False)),
        )


@dataclass(frozen=True)
class GoalSpec:
    id: str
    title: str
    objective: str
    desired_outcome: str
    project_id: str | None = None
    deliverables: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    resource_scope: ResourceScope = field(default_factory=ResourceScope)
    priority: int = 50
    deadline: str | None = None
    data_classification: str = "internal"
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    approval_policy: Mapping[str, Any] = field(default_factory=dict)
    created_from: str = "user"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("goal id is required")
        if not self.title.strip():
            raise ValueError("goal title is required")
        if not self.objective.strip():
            raise ValueError("goal objective is required")
        if not self.desired_outcome.strip():
            raise ValueError("desired_outcome is required")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "objective": self.objective,
            "desired_outcome": self.desired_outcome,
            "deliverables": list(self.deliverables),
            "success_criteria": list(self.success_criteria),
            "constraints": list(self.constraints),
            "resource_scope": self.resource_scope.to_dict(),
            "priority": self.priority,
            "deadline": self.deadline,
            "data_classification": self.data_classification,
            "budget": self.budget.to_dict(),
            "approval_policy": dict(self.approval_policy),
            "created_from": self.created_from,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GoalSpec":
        return cls(
            id=str(data["id"]),
            project_id=data.get("project_id"),
            title=str(data["title"]),
            objective=str(data["objective"]),
            desired_outcome=str(data["desired_outcome"]),
            deliverables=_tuple(data.get("deliverables")),
            success_criteria=_tuple(data.get("success_criteria")),
            constraints=_tuple(data.get("constraints")),
            resource_scope=ResourceScope.from_dict(data.get("resource_scope")),
            priority=int(data.get("priority", 50)),
            deadline=data.get("deadline"),
            data_classification=str(data.get("data_classification", "internal")),
            budget=ExecutionBudget.from_dict(data.get("budget")),
            approval_policy=_mapping(data.get("approval_policy")),
            created_from=str(data.get("created_from", "user")),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    objective: str
    success_criteria: tuple[str, ...] = ()
    work_order_ids: tuple[str, ...] = ()
    sequence: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip() or not self.objective.strip():
            raise ValueError("milestone id, title, and objective are required")
        if self.sequence < 0:
            raise ValueError("milestone sequence must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "success_criteria": list(self.success_criteria),
            "work_order_ids": list(self.work_order_ids),
            "sequence": self.sequence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Milestone":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            objective=str(data["objective"]),
            success_criteria=_tuple(data.get("success_criteria")),
            work_order_ids=_tuple(data.get("work_order_ids")),
            sequence=int(data.get("sequence", 0)),
        )


@dataclass(frozen=True)
class WorkOrder:
    id: str
    plan_id: str
    title: str
    objective: str
    worker_type: str
    project_id: str | None = None
    project_task_id: str | None = None
    status: WorkOrderStatus = WorkOrderStatus.DRAFT
    priority: int = 50
    dependencies: tuple[str, ...] = ()
    allowed_capabilities: tuple[str, ...] = ()
    resource_scope: ResourceScope = field(default_factory=ResourceScope)
    expected_output: str = ""
    success_criteria: tuple[str, ...] = ()
    evidence_contract: EvidenceContract = field(default_factory=EvidenceContract)
    verification_strategy: Mapping[str, Any] = field(default_factory=dict)
    falsifier: str | None = None
    retest_strategy: Mapping[str, Any] = field(default_factory=dict)
    approval_policy: Mapping[str, Any] = field(default_factory=dict)
    retry_policy: Mapping[str, Any] = field(default_factory=dict)
    time_budget_seconds: int | None = None
    cost_budget: float | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        for label, value in (("work order id", self.id), ("plan id", self.plan_id), ("title", self.title), ("objective", self.objective), ("worker_type", self.worker_type)):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if self.id in self.dependencies:
            raise ValueError("work order cannot depend on itself")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.time_budget_seconds is not None and self.time_budget_seconds < 0:
            raise ValueError("time_budget_seconds must be non-negative")
        if self.cost_budget is not None and self.cost_budget < 0:
            raise ValueError("cost_budget must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "project_task_id": self.project_task_id,
            "title": self.title,
            "objective": self.objective,
            "worker_type": self.worker_type,
            "status": self.status.value,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "allowed_capabilities": list(self.allowed_capabilities),
            "resource_scope": self.resource_scope.to_dict(),
            "expected_output": self.expected_output,
            "success_criteria": list(self.success_criteria),
            "evidence_contract": self.evidence_contract.to_dict(),
            "verification_strategy": dict(self.verification_strategy),
            "falsifier": self.falsifier,
            "retest_strategy": dict(self.retest_strategy),
            "approval_policy": dict(self.approval_policy),
            "retry_policy": dict(self.retry_policy),
            "time_budget_seconds": self.time_budget_seconds,
            "cost_budget": self.cost_budget,
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.workflow_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkOrder":
        return cls(
            id=str(data["id"]),
            plan_id=str(data["plan_id"]),
            project_id=data.get("project_id"),
            project_task_id=data.get("project_task_id"),
            title=str(data["title"]),
            objective=str(data["objective"]),
            worker_type=str(data["worker_type"]),
            status=WorkOrderStatus(str(data.get("status", WorkOrderStatus.DRAFT.value))),
            priority=int(data.get("priority", 50)),
            dependencies=_tuple(data.get("dependencies")),
            allowed_capabilities=_tuple(data.get("allowed_capabilities")),
            resource_scope=ResourceScope.from_dict(data.get("resource_scope")),
            expected_output=str(data.get("expected_output", "")),
            success_criteria=_tuple(data.get("success_criteria")),
            evidence_contract=EvidenceContract.from_dict(data.get("evidence_contract")),
            verification_strategy=_mapping(data.get("verification_strategy")),
            falsifier=data.get("falsifier"),
            retest_strategy=_mapping(data.get("retest_strategy")),
            approval_policy=_mapping(data.get("approval_policy")),
            retry_policy=_mapping(data.get("retry_policy")),
            time_budget_seconds=data.get("time_budget_seconds"),
            cost_budget=data.get("cost_budget"),
            workflow_id=data.get("workflow_id"),
            workflow_run_id=data.get("workflow_run_id"),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class WorkPlan:
    id: str
    goal_id: str
    version: int
    summary: str
    project_id: str | None = None
    milestones: tuple[Milestone, ...] = ()
    work_orders: tuple[WorkOrder, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence_contract: EvidenceContract = field(default_factory=EvidenceContract)
    critic: Mapping[str, Any] = field(default_factory=dict)
    readiness: ReadinessStatus = ReadinessStatus.HOLD
    status: WorkPlanStatus = WorkPlanStatus.DRAFT
    supersedes_plan_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.goal_id.strip() or not self.summary.strip():
            raise ValueError("plan id, goal id, and summary are required")
        if self.version < 1:
            raise ValueError("plan version must be at least 1")
        ids = [order.id for order in self.work_orders]
        if len(ids) != len(set(ids)):
            raise ValueError("work order ids must be unique")
        known = set(ids)
        for order in self.work_orders:
            if order.plan_id != self.id:
                raise ValueError(f"work order {order.id} belongs to a different plan")
            unknown = set(order.dependencies) - known
            if unknown:
                raise ValueError(f"work order {order.id} has unknown dependencies: {sorted(unknown)}")
        for milestone in self.milestones:
            unknown = set(milestone.work_order_ids) - known
            if unknown:
                raise ValueError(f"milestone {milestone.id} references unknown work orders: {sorted(unknown)}")
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        graph = {order.id: tuple(order.dependencies) for order in self.work_orders}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise ValueError("work order dependency graph contains a cycle")
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "project_id": self.project_id,
            "version": self.version,
            "summary": self.summary,
            "milestones": [item.to_dict() for item in self.milestones],
            "work_orders": [item.to_dict() for item in self.work_orders],
            "assumptions": list(self.assumptions),
            "evidence_contract": self.evidence_contract.to_dict(),
            "critic": dict(self.critic),
            "readiness": self.readiness.value,
            "status": self.status.value,
            "supersedes_plan_id": self.supersedes_plan_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkPlan":
        return cls(
            id=str(data["id"]),
            goal_id=str(data["goal_id"]),
            project_id=data.get("project_id"),
            version=int(data["version"]),
            summary=str(data["summary"]),
            milestones=tuple(Milestone.from_dict(item) for item in data.get("milestones", [])),
            work_orders=tuple(WorkOrder.from_dict(item) for item in data.get("work_orders", [])),
            assumptions=_tuple(data.get("assumptions")),
            evidence_contract=EvidenceContract.from_dict(data.get("evidence_contract")),
            critic=_mapping(data.get("critic")),
            readiness=ReadinessStatus(str(data.get("readiness", ReadinessStatus.HOLD.value))),
            status=WorkPlanStatus(str(data.get("status", WorkPlanStatus.DRAFT.value))),
            supersedes_plan_id=data.get("supersedes_plan_id"),
            created_at=str(data.get("created_at", utc_now_iso())),
        )
