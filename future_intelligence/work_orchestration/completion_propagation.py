from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


_ACTIVE = {"RUNNING", "VERIFYING", "REVIEWING", "RECOVERING", "RETRYING"}
_BLOCKED = {"BLOCKED", "UNCERTAIN", "FAILED", "RECOVERY_REQUIRED", "HOLD"}
_TERMINAL_PLAN = {"COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"}


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip()
    return text.upper() if text else default


def _order_by_task(work_plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in work_plan.get("work_orders") or []:
        if not isinstance(raw, Mapping):
            continue
        order = dict(raw)
        metadata = ((order.get("resource_scope") or {}).get("metadata") or {})
        task_id = str(metadata.get("p10_task_id") or "")
        if task_id:
            result[task_id] = order
    return result


def canonical_task_rows(
    p10_plan: Mapping[str, Any],
    work_plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project P10 execution through the authoritative Completion Judge."""
    order_by_task = _order_by_task(work_plan)
    rows: list[dict[str, Any]] = []
    for raw_task in p10_plan.get("tasks") or []:
        if not isinstance(raw_task, Mapping):
            continue
        task = dict(raw_task)
        task_id = str(task.get("id") or "")
        order = order_by_task.get(task_id) or {}
        completion = dict(order.get("completion") or {})
        raw_status = _upper(task.get("status"))
        canonical_status = _upper(order.get("status"), raw_status)
        passed = bool(completion.get("passed"))

        if raw_status == "COMPLETED":
            if passed:
                canonical_status = "COMPLETED"
            elif canonical_status not in {"VERIFYING", "REVIEWING", "BLOCKED", "HOLD"}:
                canonical_status = "VERIFYING"
        elif passed:
            # Completion proof cannot invent execution completion before P10 is terminal.
            canonical_status = raw_status
        else:
            # Active/approval/recovery execution state remains authoritative until
            # execution is terminal; the judge only gates completion.
            canonical_status = raw_status

        rows.append(
            {
                "task_id": task_id,
                "status": canonical_status,
                "execution_status": raw_status,
                "dependencies": [str(item) for item in task.get("dependencies") or []],
                "completion": completion,
                "work_order": order,
                "task": task,
            }
        )
    return rows


def canonical_ready_ids(
    p10_plan: Mapping[str, Any],
    work_plan: Mapping[str, Any],
) -> set[str]:
    rows = canonical_task_rows(p10_plan, work_plan)
    completed = {row["task_id"] for row in rows if row["status"] == "COMPLETED"}
    return {
        row["task_id"]
        for row in rows
        if row["execution_status"] == "WAITING"
        and set(row["dependencies"]).issubset(completed)
    }


def canonical_live_projection(
    p10_plan: Mapping[str, Any],
    work_plan: Mapping[str, Any],
) -> dict[str, Any]:
    rows = canonical_task_rows(p10_plan, work_plan)
    ready = canonical_ready_ids(p10_plan, work_plan)
    counts = Counter(row["status"] for row in rows)
    raw_plan_state = _upper(p10_plan.get("state"))
    work_status = _upper(work_plan.get("status"), raw_plan_state)
    completion = dict(work_plan.get("completion") or {})
    plan_passed = bool(completion.get("complete"))
    if raw_plan_state == "COMPLETED":
        if plan_passed:
            state = "COMPLETED"
        elif work_status in {"VERIFYING", "REVIEWING", "HOLD", "BLOCKED"}:
            state = work_status
        else:
            state = "VERIFYING"
    else:
        state = raw_plan_state

    return {
        "state": state,
        "execution_state": raw_plan_state,
        "completion": completion,
        "task_counts": dict(counts),
        "ready_task_ids": sorted(ready),
        "active_task_ids": [row["task_id"] for row in rows if row["status"] in _ACTIVE],
        "waiting_approval_task_ids": [row["task_id"] for row in rows if row["status"] == "WAITING_APPROVAL"],
        "blocked_task_ids": [row["task_id"] for row in rows if row["status"] in _BLOCKED],
        "replan_count": int(p10_plan.get("replan_count") or 0),
        "updated_at": p10_plan.get("updated_at"),
        "completion_authority": "deterministic_completion_judge",
    }


def canonicalize_global_summary(
    summary: Mapping[str, Any],
    autonomy: Any,
    *,
    living_state_fn,
) -> dict[str, Any]:
    """Reconcile a GlobalWorkService summary with canonical Work completion."""
    projected = dict(summary)
    original_orders = [dict(item) for item in summary.get("work_orders") or []]
    plan_ids = {str(item.get("plan_id") or "") for item in original_orders if str(item.get("plan_id") or "")}
    plans: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], set[str]]] = {}

    for plan_id in plan_ids:
        try:
            p10_plan = autonomy.plan(plan_id, owner_id="owner")
            work_plan = autonomy.work_plan(plan_id, owner_id="owner")
        except (KeyError, RuntimeError):
            continue
        rows = canonical_task_rows(p10_plan, work_plan)
        plans[plan_id] = (
            dict(p10_plan),
            dict(work_plan),
            {row["task_id"]: row for row in rows},
            canonical_ready_ids(p10_plan, work_plan),
        )

    orders: list[dict[str, Any]] = []
    task_counts: Counter[str] = Counter()
    project_counts: dict[str, Counter[str]] = {}
    for item in original_orders:
        plan_id = str(item.get("plan_id") or "")
        task_id = str(item.get("task_id") or "")
        bundle = plans.get(plan_id)
        row = bundle[2].get(task_id) if bundle is not None else None
        ready_ids = bundle[3] if bundle is not None else set()
        updated = dict(item)
        if row is not None:
            updated["execution_status"] = row["execution_status"]
            updated["status"] = row["status"]
            updated["completion"] = row["completion"]
            updated["ready"] = task_id in ready_ids
        elif _upper(updated.get("status")) == "COMPLETED":
            updated["execution_status"] = "COMPLETED"
            updated["status"] = "VERIFYING"
            updated["ready"] = False
        status = _upper(updated.get("status"))
        task_counts[status] += 1
        project_id = str(updated.get("project_id") or "")
        project_counts.setdefault(project_id, Counter())[status] += 1
        orders.append(updated)

    projects = []
    for project in summary.get("projects") or []:
        row = dict(project)
        project_id = str(row.get("project_id") or "")
        plan_id = str(row.get("plan_id") or "")
        bundle = plans.get(plan_id)
        row["task_counts"] = dict(project_counts.get(project_id, Counter()))
        if bundle is not None:
            p10_plan, work_plan, _, _ = bundle
            raw_state = _upper(p10_plan.get("state"))
            canonical_state = _upper(work_plan.get("status"), raw_state)
            completion = dict(work_plan.get("completion") or {})
            row["execution_state"] = raw_state
            if raw_state == "COMPLETED":
                if bool(completion.get("complete")):
                    row["state"] = "COMPLETED"
                elif canonical_state in {"VERIFYING", "REVIEWING", "HOLD", "BLOCKED"}:
                    row["state"] = canonical_state
                else:
                    row["state"] = "VERIFYING"
            else:
                row["state"] = raw_state
            row["completion"] = completion
        projects.append(row)

    active = sum(task_counts[state] for state in _ACTIVE)
    approval = task_counts["WAITING_APPROVAL"]
    blocked = sum(task_counts[state] for state in _BLOCKED)
    verifying = task_counts["VERIFYING"] + task_counts["REVIEWING"]
    recovering = task_counts["RECOVERING"] + task_counts["RECOVERY_REQUIRED"]
    ready = sum(1 for item in orders if item.get("ready"))
    completed = task_counts["COMPLETED"]
    active_projects = sum(1 for item in projects if _upper(item.get("state")) not in _TERMINAL_PLAN)
    living_state, living_detail = living_state_fn(
        active=active,
        approval=approval,
        blocked=blocked,
        ready=ready,
        verifying=verifying,
    )

    priority = {
        "WAITING_APPROVAL": 0,
        "BLOCKED": 1,
        "UNCERTAIN": 1,
        "FAILED": 1,
        "RECOVERY_REQUIRED": 1,
        "HOLD": 1,
        "VERIFYING": 2,
        "REVIEWING": 2,
        "RECOVERING": 2,
        "RETRYING": 2,
        "RUNNING": 2,
        "WAITING": 3,
        "COMPLETED": 5,
    }
    orders.sort(
        key=lambda item: (
            priority.get(_upper(item.get("status")), 4),
            0 if item.get("ready") else 1,
            str(item.get("project_name") or "").lower(),
            str(item.get("title") or "").lower(),
        )
    )

    projected["completion_authority"] = "deterministic_completion_judge"
    projected["task_counts"] = dict(task_counts)
    projected["counts"] = {
        "active": active,
        "verifying": verifying,
        "recovering": recovering,
        "waiting_approval": approval,
        "blocked": blocked,
        "ready": ready,
        "completed": completed,
        "work_orders": sum(task_counts.values()),
    }
    projected["active_projects"] = active_projects
    projected["living"] = {"state": living_state, "detail": living_detail}
    projected["projects"] = projects
    projected["work_orders"] = orders
    return projected


def install(autonomy: Any) -> None:
    """Install canonical completion reconciliation on product read models."""
    from server.global_work_api import GlobalWorkService
    from server.project_work_api import ProjectWorkService
    from .living_projection import LivingAgentWorkProjection

    if not getattr(GlobalWorkService, "_canonical_completion_installed", False):
        original_summary = GlobalWorkService.summary

        def summary(self, *args, **kwargs):
            raw = original_summary(self, *args, **kwargs)
            return canonicalize_global_summary(raw, self._autonomy(), living_state_fn=self._living_state)

        GlobalWorkService.summary = summary
        GlobalWorkService._canonical_completion_installed = True

    if not getattr(ProjectWorkService, "_canonical_completion_installed", False):
        original_snapshot = ProjectWorkService.snapshot

        def snapshot(self, project_id):
            result = original_snapshot(self, project_id)
            p10_plan = result.get("p10_plan")
            work_plan = result.get("work_plan")
            if isinstance(p10_plan, Mapping) and isinstance(work_plan, Mapping):
                result = dict(result)
                result["live_work"] = canonical_live_projection(p10_plan, work_plan)
            return result

        ProjectWorkService.snapshot = snapshot
        ProjectWorkService._canonical_completion_installed = True

    if not getattr(LivingAgentWorkProjection, "_canonical_completion_installed", False):
        original_project = LivingAgentWorkProjection.project.__func__

        def project(cls, work, attention):
            result = original_project(cls, work, attention)
            if result.get("state") == "completed":
                counts = work.get("task_counts") or {}
                total = sum(max(0, int(value or 0)) for value in counts.values())
                completed = max(0, int(counts.get("COMPLETED", 0) or 0))
                if not total or completed != total:
                    corrected = dict(result)
                    corrected["state"] = "idle"
                    corrected["activity"] = "Canonical Project Work is not complete; Completion Judge proof is still required."
                    corrected["intensity"] = 0.0
                    return corrected
            return result

        LivingAgentWorkProjection.project = classmethod(project)
        LivingAgentWorkProjection._canonical_completion_installed = True


def bind_notifications(bridge: Any, autonomy: Any) -> None:
    """Ensure completion notifications are emitted only from canonical proof."""
    if getattr(bridge, "_canonical_completion_bound", False):
        return

    mapping = dict(getattr(bridge, "_P10_STATE_EVENTS", {}))
    mapping.pop("COMPLETED", None)
    bridge._P10_STATE_EVENTS = mapping

    def evaluate(event: Mapping[str, Any]) -> None:
        plan_id = str(event.get("plan_id") or "")
        task_id = str(event.get("task_id") or "")
        if not plan_id or not task_id:
            return
        try:
            decision = autonomy.work_order_completion(plan_id, task_id, owner_id="owner")
        except (KeyError, RuntimeError):
            return
        if not bool(decision.get("passed")):
            return

        source = {
            **dict(event),
            "state": "COMPLETED",
            "state_version": decision.get("score") or decision.get("state"),
        }
        bridge._emit("work.order.completed", source)

        try:
            report = autonomy.work_completion(plan_id, owner_id="owner")
        except (KeyError, RuntimeError):
            return
        if bool(report.get("complete")):
            bridge._emit(
                "work.goal.completed",
                {**source, "task_id": None, "state_version": report.get("score") or report.get("state")},
            )

    for event_name in (
        "work_completion_observed",
        "work.review.passed",
        "work.claim.verified",
        "work.evidence.recorded",
    ):
        bridge._unsubscribers.append(bridge.events.subscribe(event_name, evaluate))
    bridge._canonical_completion_bound = True
