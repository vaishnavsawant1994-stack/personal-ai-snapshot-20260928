from __future__ import annotations

from dataclasses import replace
import json
import time
from typing import Any

from .models import WorkPlan
from .replanning import PlanDeltaStore, diff_work_plans


_ACTIVE_TASK_STATES = {
    "RUNNING",
    "WAITING_APPROVAL",
    "VERIFYING",
    "RECOVERING",
    "UNCERTAIN",
}
_MUTABLE_TASK_STATES = {"WAITING", "READY"}
_IMMUTABLE_TASK_STATES = {"COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"}


def _raw_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "objective": task.get("objective", ""),
        "dependencies": list(task.get("dependencies") or []),
        "required_capabilities": list(task.get("required_capabilities") or []),
        "action": task.get("action", ""),
        "requested_tool": task.get("requested_tool"),
        "parameters": dict(task.get("parameters") or {}),
        "depth": task.get("depth", 1),
        "risk": task.get("risk", "low"),
        "privacy": task.get("privacy", "internal"),
        "consequential": bool(task.get("consequential", False)),
        "approval_required": bool(task.get("approval_required", False)),
        "verification_required": bool(task.get("verification_required", False)),
        "retry_limit": int(task.get("retry_limit", 0)),
    }


def _history_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or "")[:80],
        "objective": str(task.get("objective") or "")[:500],
        "status": str(task.get("status") or "")[:40],
        "result_ref": str(task.get("result_ref") or "")[:300] or None,
        "operation_id": str(task.get("operation_id") or "")[:300] or None,
        "operation_plan_id": str(task.get("operation_plan_id") or "")[:300] or None,
    }


def _task_signature(task: dict[str, Any]) -> str:
    payload = _raw_task(task)
    payload.pop("id", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _task_id_from_order(order) -> str:
    return str(order.resource_scope.metadata.get("p10_task_id") or order.id)


def _enrich_projection(
    before: WorkPlan | None,
    after: WorkPlan,
    *,
    preserved_semantic_task_ids: set[str],
    reason: str,
    trigger: str,
) -> WorkPlan:
    if before is None:
        return after
    old_by_task = {_task_id_from_order(order): order for order in before.work_orders}
    enriched_orders = []
    for base in after.work_orders:
        task_id = _task_id_from_order(base)
        prior = old_by_task.get(task_id)
        if prior is None or task_id not in preserved_semantic_task_ids:
            enriched_orders.append(base)
            continue
        enriched_orders.append(
            replace(
                prior,
                id=base.id,
                plan_id=after.id,
                project_id=after.project_id or prior.project_id,
                status=base.status,
                dependencies=base.dependencies,
                workflow_id=base.workflow_id,
                workflow_run_id=base.workflow_run_id,
                created_at=base.created_at,
                updated_at=base.updated_at,
            )
        )

    old_order_to_task = {order.id: _task_id_from_order(order) for order in before.work_orders}
    new_task_to_order = {_task_id_from_order(order): order.id for order in enriched_orders}
    milestones = []
    for milestone in before.milestones:
        task_ids = [old_order_to_task.get(order_id) for order_id in milestone.work_order_ids]
        if task_ids and all(task_id and task_id in new_task_to_order for task_id in task_ids):
            milestones.append(
                replace(
                    milestone,
                    work_order_ids=tuple(new_task_to_order[str(task_id)] for task_id in task_ids),
                )
            )

    critic = {
        **dict(after.critic),
        "versioned_replanning": True,
        "replan_reason": str(reason)[:1000],
        "replan_trigger": str(trigger)[:120],
        "semantic_history_preserved": bool(preserved_semantic_task_ids),
    }
    if before.critic.get("hierarchical_planning"):
        critic["preserved_hierarchical_context"] = True

    return WorkPlan(
        id=after.id,
        goal_id=after.goal_id,
        project_id=after.project_id or before.project_id,
        version=after.version,
        summary=before.summary if before.summary.strip() else after.summary,
        milestones=tuple(milestones),
        work_orders=tuple(enriched_orders),
        assumptions=before.assumptions,
        evidence_contract=before.evidence_contract,
        critic=critic,
        readiness=after.readiness,
        status=after.status,
        supersedes_plan_id=after.supersedes_plan_id,
        created_at=after.created_at,
    )


def install(cls) -> None:
    """Install versioned, history-preserving replanning above the existing P10 runtime.

    Replanning remains planning-only. It cannot approve, execute, verify, recover or
    expand permissions. Active/uncertain work must resolve before its task graph can
    be replaced.
    """
    if getattr(cls, "_versioned_replanning_installed", False):
        return

    original_status = cls.status
    original_work_plan = cls.work_plan

    def replan(
        self,
        plan_id,
        replacement_tasks,
        *,
        owner_id="owner",
        reason="changed conditions",
        trigger="manual",
    ):
        if not isinstance(replacement_tasks, list):
            raise ValueError("replacement tasks must be a list")
        reason = str(reason or "changed conditions")[:1000]
        trigger = str(trigger or "manual")[:120]

        with self._lock:
            plan = self.plan(plan_id, owner_id=owner_id)
            if str(plan.get("state")) in {"COMPLETED", "CANCELLED"}:
                raise RuntimeError("terminal plan cannot be replanned")
            if int(plan.get("replan_count", 0)) >= self.MAX_REPLANS:
                plan["state"] = "BLOCKED"
                self._save_plan(plan)
                raise RuntimeError("replan limit exceeded")

            active = [
                str(task.get("id"))
                for task in plan.get("tasks", [])
                if str(task.get("status") or "").upper() in _ACTIVE_TASK_STATES
            ]
            if active:
                raise RuntimeError(
                    "active, approval-pending, verification, recovery, or uncertain work must resolve before replanning"
                )

            goal = self.goal(plan["goal_id"], owner_id=owner_id)
            old_tasks = [dict(task) for task in plan.get("tasks", [])]
            old_by_id = {str(task.get("id")): task for task in old_tasks}
            completed = [
                task for task in old_tasks if str(task.get("status") or "").upper() == "COMPLETED"
            ]
            protected_ids = {
                str(task.get("id"))
                for task in old_tasks
                if str(task.get("status") or "").upper() in _IMMUTABLE_TASK_STATES
            }

            combined = [_raw_task(task) for task in completed] + [dict(task) for task in replacement_tasks]
            clean = self._validate_tasks(combined, goal)
            replacement_clean = clean[len(completed) :]
            reused = sorted({str(task["id"]) for task in replacement_clean} & protected_ids)
            if reused:
                raise ValueError(
                    "replacement tasks cannot reuse immutable execution task ids: " + ", ".join(reused)
                )

            completed_by_id = {str(task["id"]): task for task in completed}
            new_tasks = [completed_by_id.get(str(task["id"]), task) for task in clean]
            new_by_id = {str(task["id"]): task for task in new_tasks}
            preserved_semantic_ids = set(completed_by_id)
            for task_id, task in new_by_id.items():
                previous = old_by_id.get(task_id)
                if previous is None:
                    continue
                if str(previous.get("status") or "").upper() in _MUTABLE_TASK_STATES:
                    if _task_signature(previous) == _task_signature(task):
                        preserved_semantic_ids.add(task_id)

            retired_now = [
                _history_task(task)
                for task in old_tasks
                if str(task.get("status") or "").upper() != "COMPLETED"
            ]
            retired = list(plan.get("retired_tasks") or []) + retired_now
            plan["retired_tasks"] = retired[-200:]
            history = list(plan.get("replan_history") or [])
            history.append(
                {
                    "sequence": int(plan.get("replan_count", 0)) + 1,
                    "reason": reason,
                    "trigger": trigger,
                    "preserved_completed_task_ids": sorted(completed_by_id),
                    "retired_task_ids": [item["id"] for item in retired_now],
                    "created_at": time.time(),
                }
            )
            plan["replan_history"] = history[-self.MAX_REPLANS :]
            plan["tasks"] = new_tasks
            plan["replan_count"] = int(plan.get("replan_count", 0)) + 1
            plan["state"] = "COMPLETED" if new_tasks and all(
                str(task.get("status") or "").upper() == "COMPLETED" for task in new_tasks
            ) else "READY"
            self._save_plan(plan)
            goal["state"] = "COMPLETED" if plan["state"] == "COMPLETED" else "READY"
            self._save_goal(goal)

            bridge = getattr(self, "_work_bridge", None)
            delta = None
            work_plan = None
            projection_error_type = None
            if bridge is not None:
                try:
                    before = bridge.work_plan_for_p10(plan_id)
                    projected = bridge.project_plan(plan, goal, force_new_version=True)
                    enriched = _enrich_projection(
                        before,
                        projected,
                        preserved_semantic_task_ids=preserved_semantic_ids,
                        reason=reason,
                        trigger=trigger,
                    )
                    work_plan = bridge.work.save_plan(enriched, source_p10_plan_id=str(plan_id))
                    delta = diff_work_plans(
                        before,
                        work_plan,
                        source_p10_plan_id=str(plan_id),
                        reason=reason,
                        trigger=trigger,
                        preserved_completed_task_ids=tuple(sorted(completed_by_id)),
                        retired_task_ids=tuple(item["id"] for item in retired_now),
                    )
                    PlanDeltaStore(bridge.connection).record(delta)
                except Exception as exc:
                    projection_error_type = type(exc).__name__
                    try:
                        self._event(
                            "replan_projection_error",
                            goal_id=plan["goal_id"],
                            plan_id=plan_id,
                            replan_count=plan["replan_count"],
                            error_type=projection_error_type,
                            authority="p10_replan_already_persisted",
                        )
                    except Exception:
                        pass

            self._event(
                "replanned_versioned",
                goal_id=plan["goal_id"],
                plan_id=plan_id,
                replan_count=plan["replan_count"],
                reason=reason[:300],
                trigger=trigger,
                preserved_completed=len(completed_by_id),
                retired=len(retired_now),
                delta_id=delta.id if delta is not None else None,
                work_plan_id=work_plan.id if work_plan is not None else None,
                projection_error_type=projection_error_type,
                authority="planning_only",
            )
            if projection_error_type is not None:
                result = dict(plan)
                result["work_projection"] = {
                    "state": "failed",
                    "error_type": projection_error_type,
                    "p10_replan_persisted": True,
                }
                return result
            return plan

    def work_plan_versions(self, plan_id, *, owner_id="owner"):
        self.plan(plan_id, owner_id=owner_id)
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        with bridge.lock:
            rows = bridge.connection.execute(
                """
                SELECT payload_json FROM work_plans
                WHERE source_p10_plan_id=?
                ORDER BY version,created_at,id
                """,
                (str(plan_id),),
            ).fetchall()
        return [WorkPlan.from_dict(json.loads(row[0])).to_dict() for row in rows]

    def work_plan_deltas(self, plan_id, *, owner_id="owner", limit=100):
        self.plan(plan_id, owner_id=owner_id)
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        with bridge.lock:
            return [
                item.to_dict()
                for item in PlanDeltaStore(bridge.connection).list_for_source(str(plan_id), limit=limit)
            ]

    def work_plan(self, plan_id, *, owner_id="owner"):
        result = original_work_plan(self, plan_id, owner_id=owner_id)
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            return result
        with bridge.lock:
            latest = PlanDeltaStore(bridge.connection).latest_for_source(str(plan_id))
        if latest is not None:
            result = dict(result)
            result["latest_delta"] = latest.to_dict()
        return result

    def status(self):
        result = original_status(self)
        bridge = getattr(self, "_work_bridge", None)
        delta_count = 0
        if bridge is not None:
            with bridge.lock:
                delta_count = int(bridge.connection.execute("SELECT COUNT(*) FROM plan_deltas").fetchone()[0])
        result["versioned_replanning"] = {
            "installed": True,
            "authority": "planning_only",
            "active_work_rewrite": "blocked",
            "completed_work": "immutable",
            "max_replans": int(self.MAX_REPLANS),
            "deltas": delta_count,
        }
        return result

    cls.replan = replan
    cls.work_plan_versions = work_plan_versions
    cls.work_plan_deltas = work_plan_deltas
    cls.work_plan = work_plan
    cls.status = status
    cls._versioned_replanning_installed = True
