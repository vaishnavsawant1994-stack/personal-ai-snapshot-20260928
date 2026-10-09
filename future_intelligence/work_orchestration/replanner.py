from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import sqlite3
import uuid
from typing import Any, Iterable, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanDeltaKind(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    REMOVE = "remove"


class ReplanSafetyError(RuntimeError):
    """Raised when replanning would rewrite active or already-executed work."""


@dataclass(frozen=True)
class PlanDeltaChange:
    kind: PlanDeltaKind
    task_id: str
    changed_fields: tuple[str, ...] = ()
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "task_id": self.task_id,
            "changed_fields": list(self.changed_fields),
            "before": dict(self.before) if self.before is not None else None,
            "after": dict(self.after) if self.after is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanDeltaChange":
        return cls(
            kind=PlanDeltaKind(str(data["kind"])),
            task_id=str(data["task_id"]),
            changed_fields=tuple(str(x) for x in data.get("changed_fields", [])),
            before=dict(data["before"]) if isinstance(data.get("before"), Mapping) else None,
            after=dict(data["after"]) if isinstance(data.get("after"), Mapping) else None,
        )


@dataclass(frozen=True)
class PlanDelta:
    id: str
    goal_id: str
    from_plan_id: str | None
    to_plan_id: str
    reason: str
    changes: tuple[PlanDeltaChange, ...]
    from_version: int | None = None
    to_version: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "from_plan_id": self.from_plan_id,
            "to_plan_id": self.to_plan_id,
            "reason": self.reason,
            "changes": [item.to_dict() for item in self.changes],
            "from_version": self.from_version,
            "to_version": self.to_version,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanDelta":
        return cls(
            id=str(data["id"]),
            goal_id=str(data["goal_id"]),
            from_plan_id=str(data["from_plan_id"]) if data.get("from_plan_id") else None,
            to_plan_id=str(data["to_plan_id"]),
            reason=str(data["reason"]),
            changes=tuple(PlanDeltaChange.from_dict(item) for item in data.get("changes", [])),
            from_version=int(data["from_version"]) if data.get("from_version") is not None else None,
            to_version=int(data["to_version"]) if data.get("to_version") is not None else None,
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or _now()),
        )


_ACTIVE_STATUSES = {"RUNNING", "WAITING_APPROVAL", "VERIFYING", "RECOVERING", "UNCERTAIN"}
_MUTABLE_STATUSES = {"WAITING", "READY"}
_SEMANTIC_FIELDS = (
    "objective",
    "dependencies",
    "required_capabilities",
    "action",
    "requested_tool",
    "parameters",
    "risk",
    "privacy",
    "consequential",
    "approval_required",
    "verification_required",
    "retry_limit",
)


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def semantic_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return {field: _normalize(task.get(field)) for field in _SEMANTIC_FIELDS}


def _executed(task: Mapping[str, Any]) -> bool:
    status = str(task.get("status") or "WAITING").upper()
    if status not in _MUTABLE_STATUSES:
        return True
    return any(task.get(key) not in (None, "") for key in ("operation_plan_id", "operation_id", "result_ref"))


def prepare_safe_replacement(
    current_plan: Mapping[str, Any],
    replacement_tasks: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return a safe P10 replacement while preserving immutable completed work.

    Replanning is rejected while any task is actively dispatching, awaiting canonical
    approval/verification/recovery, or uncertain. Completed work is injected unchanged
    when a model omits it. Any other task that has already executed must be replaced
    with a new task id instead of silently reusing its identity.
    """
    current_tasks = [dict(item) for item in current_plan.get("tasks", []) if isinstance(item, Mapping)]
    active = [
        str(task.get("id"))
        for task in current_tasks
        if str(task.get("status") or "").upper() in _ACTIVE_STATUSES
    ]
    if active:
        raise ReplanSafetyError(
            "cannot replan while work is active, awaiting approval/verification/recovery, or uncertain: "
            + ", ".join(active)
        )

    replacements = [dict(item) for item in replacement_tasks if isinstance(item, Mapping)]
    ids = [str(item.get("id") or "") for item in replacements]
    if not ids or any(not item for item in ids):
        raise ReplanSafetyError("replacement plan must contain stable task ids")
    if len(ids) != len(set(ids)):
        raise ReplanSafetyError("replacement plan contains duplicate task ids")

    current_by_id = {str(item.get("id")): item for item in current_tasks}
    replacement_by_id = {str(item.get("id")): item for item in replacements}

    completed: list[dict[str, Any]] = []
    for task_id, original in current_by_id.items():
        status = str(original.get("status") or "WAITING").upper()
        if not _executed(original):
            continue
        incoming = replacement_by_id.get(task_id)
        if status == "COMPLETED":
            if incoming is not None and semantic_task(incoming) != semantic_task(original):
                raise ReplanSafetyError(f"completed task {task_id} is immutable")
            completed.append(dict(original))
            continue
        if incoming is not None:
            raise ReplanSafetyError(
                f"executed task id {task_id} cannot be reused; create a new task id for replacement work"
            )

    completed_ids = {str(item["id"]) for item in completed}
    merged = completed + [item for item in replacements if str(item.get("id")) not in completed_ids]
    known = {str(item.get("id")) for item in merged}
    for item in merged:
        task_id = str(item.get("id"))
        dependencies = [str(dep) for dep in item.get("dependencies", [])]
        if task_id in dependencies or any(dep not in known for dep in dependencies):
            raise ReplanSafetyError(f"replacement task {task_id} has an invalid dependency")
    return merged


def compute_task_delta(
    before_tasks: Iterable[Mapping[str, Any]],
    after_tasks: Iterable[Mapping[str, Any]],
) -> tuple[PlanDeltaChange, ...]:
    before = {str(item.get("id")): dict(item) for item in before_tasks if isinstance(item, Mapping)}
    after = {str(item.get("id")): dict(item) for item in after_tasks if isinstance(item, Mapping)}
    changes: list[PlanDeltaChange] = []

    for task_id in sorted(set(after) - set(before)):
        changes.append(PlanDeltaChange(kind=PlanDeltaKind.ADD, task_id=task_id, after=semantic_task(after[task_id])))
    for task_id in sorted(set(before) - set(after)):
        changes.append(PlanDeltaChange(kind=PlanDeltaKind.REMOVE, task_id=task_id, before=semantic_task(before[task_id])))
    for task_id in sorted(set(before) & set(after)):
        old = semantic_task(before[task_id])
        new = semantic_task(after[task_id])
        changed = tuple(field for field in _SEMANTIC_FIELDS if old.get(field) != new.get(field))
        if changed:
            changes.append(
                PlanDeltaChange(
                    kind=PlanDeltaKind.MODIFY,
                    task_id=task_id,
                    changed_fields=changed,
                    before=old,
                    after=new,
                )
            )
    return tuple(changes)


class PlanDeltaStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record(
        self,
        *,
        goal_id: str,
        from_plan_id: str | None,
        to_plan_id: str,
        reason: str,
        changes: Iterable[PlanDeltaChange],
        from_version: int | None = None,
        to_version: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlanDelta:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("replan reason is required")
        delta = PlanDelta(
            id=str(uuid.uuid4()),
            goal_id=str(goal_id),
            from_plan_id=str(from_plan_id) if from_plan_id else None,
            to_plan_id=str(to_plan_id),
            reason=reason[:1000],
            changes=tuple(changes),
            from_version=from_version,
            to_version=to_version,
            metadata=dict(metadata or {}),
        )
        payload = json.dumps(delta.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO plan_deltas(id,goal_id,from_plan_id,to_plan_id,reason,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (delta.id, delta.goal_id, delta.from_plan_id, delta.to_plan_id, delta.reason, payload, delta.created_at),
            )
        return delta

    def list_for_goal(self, goal_id: str) -> list[PlanDelta]:
        rows = self.connection.execute(
            """
            SELECT payload_json FROM plan_deltas
            WHERE goal_id=?
            ORDER BY created_at,id
            """,
            (str(goal_id),),
        ).fetchall()
        return [PlanDelta.from_dict(json.loads(row[0])) for row in rows]

    def latest_for_plan(self, plan_id: str) -> PlanDelta | None:
        row = self.connection.execute(
            """
            SELECT payload_json FROM plan_deltas
            WHERE to_plan_id=?
            ORDER BY created_at DESC,id DESC
            LIMIT 1
            """,
            (str(plan_id),),
        ).fetchone()
        return PlanDelta.from_dict(json.loads(row[0])) if row else None
