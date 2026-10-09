from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import sqlite3
import uuid
from typing import Any, Mapping

from .models import WorkOrder, WorkPlan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanDeltaAction(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    REMOVE = "remove"


@dataclass(frozen=True)
class PlanDeltaItem:
    action: PlanDeltaAction
    task_id: str
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "task_id": self.task_id,
            "before": dict(self.before) if self.before is not None else None,
            "after": dict(self.after) if self.after is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanDeltaItem":
        before = data.get("before")
        after = data.get("after")
        return cls(
            action=PlanDeltaAction(str(data["action"])),
            task_id=str(data["task_id"]),
            before=dict(before) if isinstance(before, Mapping) else None,
            after=dict(after) if isinstance(after, Mapping) else None,
        )


@dataclass(frozen=True)
class PlanDelta:
    id: str
    goal_id: str
    source_p10_plan_id: str
    from_plan_id: str | None
    to_plan_id: str
    reason: str
    trigger: str
    items: tuple[PlanDeltaItem, ...] = ()
    preserved_completed_task_ids: tuple[str, ...] = ()
    retired_task_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "source_p10_plan_id": self.source_p10_plan_id,
            "from_plan_id": self.from_plan_id,
            "to_plan_id": self.to_plan_id,
            "reason": self.reason,
            "trigger": self.trigger,
            "items": [item.to_dict() for item in self.items],
            "preserved_completed_task_ids": list(self.preserved_completed_task_ids),
            "retired_task_ids": list(self.retired_task_ids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanDelta":
        return cls(
            id=str(data["id"]),
            goal_id=str(data["goal_id"]),
            source_p10_plan_id=str(data["source_p10_plan_id"]),
            from_plan_id=data.get("from_plan_id"),
            to_plan_id=str(data["to_plan_id"]),
            reason=str(data.get("reason") or "changed conditions"),
            trigger=str(data.get("trigger") or "manual"),
            items=tuple(PlanDeltaItem.from_dict(item) for item in data.get("items", [])),
            preserved_completed_task_ids=tuple(str(x) for x in data.get("preserved_completed_task_ids", [])),
            retired_task_ids=tuple(str(x) for x in data.get("retired_task_ids", [])),
            created_at=str(data.get("created_at") or _now()),
        )


def _task_id(order: WorkOrder) -> str:
    return str(order.resource_scope.metadata.get("p10_task_id") or order.id)


def _semantic_map(plan: WorkPlan | None) -> dict[str, dict[str, Any]]:
    if plan is None:
        return {}
    id_to_task = {order.id: _task_id(order) for order in plan.work_orders}
    out: dict[str, dict[str, Any]] = {}
    for order in plan.work_orders:
        task_id = _task_id(order)
        scope = order.resource_scope.to_dict()
        out[task_id] = {
            "title": order.title,
            "objective": order.objective,
            "worker_type": order.worker_type,
            "priority": order.priority,
            "dependencies": [id_to_task.get(dep, dep) for dep in order.dependencies],
            "allowed_capabilities": list(order.allowed_capabilities),
            "resource_scope": scope,
            "expected_output": order.expected_output,
            "success_criteria": list(order.success_criteria),
            "evidence_contract": order.evidence_contract.to_dict(),
            "verification_strategy": dict(order.verification_strategy),
            "falsifier": order.falsifier,
            "retest_strategy": dict(order.retest_strategy),
            "approval_policy": dict(order.approval_policy),
            "retry_policy": dict(order.retry_policy),
            "time_budget_seconds": order.time_budget_seconds,
            "cost_budget": order.cost_budget,
        }
    return out


def diff_work_plans(
    before: WorkPlan | None,
    after: WorkPlan,
    *,
    source_p10_plan_id: str,
    reason: str,
    trigger: str,
    preserved_completed_task_ids: tuple[str, ...] = (),
    retired_task_ids: tuple[str, ...] = (),
) -> PlanDelta:
    old = _semantic_map(before)
    new = _semantic_map(after)
    items: list[PlanDeltaItem] = []
    for task_id in sorted(old.keys() - new.keys()):
        items.append(PlanDeltaItem(PlanDeltaAction.REMOVE, task_id, before=old[task_id]))
    for task_id in sorted(new.keys() - old.keys()):
        items.append(PlanDeltaItem(PlanDeltaAction.ADD, task_id, after=new[task_id]))
    for task_id in sorted(old.keys() & new.keys()):
        if old[task_id] != new[task_id]:
            items.append(
                PlanDeltaItem(
                    PlanDeltaAction.MODIFY,
                    task_id,
                    before=old[task_id],
                    after=new[task_id],
                )
            )
    return PlanDelta(
        id=str(uuid.uuid4()),
        goal_id=after.goal_id,
        source_p10_plan_id=str(source_p10_plan_id),
        from_plan_id=before.id if before is not None else None,
        to_plan_id=after.id,
        reason=str(reason or "changed conditions")[:1000],
        trigger=str(trigger or "manual")[:120],
        items=tuple(items),
        preserved_completed_task_ids=tuple(preserved_completed_task_ids),
        retired_task_ids=tuple(retired_task_ids),
    )


class PlanDeltaStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record(self, delta: PlanDelta) -> PlanDelta:
        payload = json.dumps(delta.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO plan_deltas(id,goal_id,from_plan_id,to_plan_id,reason,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    delta.id,
                    delta.goal_id,
                    delta.from_plan_id,
                    delta.to_plan_id,
                    delta.reason,
                    payload,
                    delta.created_at,
                ),
            )
        return delta

    def list_for_source(self, source_p10_plan_id: str, *, limit: int = 100) -> list[PlanDelta]:
        rows = self.connection.execute(
            "SELECT payload_json FROM plan_deltas ORDER BY created_at,id LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        result = []
        for row in rows:
            data = json.loads(row[0])
            if str(data.get("source_p10_plan_id")) == str(source_p10_plan_id):
                result.append(PlanDelta.from_dict(data))
        return result

    def latest_for_source(self, source_p10_plan_id: str) -> PlanDelta | None:
        rows = self.connection.execute(
            "SELECT payload_json FROM plan_deltas ORDER BY created_at DESC,id DESC LIMIT 500"
        ).fetchall()
        for row in rows:
            data = json.loads(row[0])
            if str(data.get("source_p10_plan_id")) == str(source_p10_plan_id):
                return PlanDelta.from_dict(data)
        return None
