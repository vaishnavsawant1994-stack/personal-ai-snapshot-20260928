from __future__ import annotations

from typing import Any, Mapping


_ACTIVE_STATUSES = {
    "RUNNING",
    "VERIFYING",
    "RECOVERING",
    "RETRYING",
    "REPLANNING",
    "REVIEWING",
}
_ATTENTION_STATUSES = {"WAITING_APPROVAL", "BLOCKED", "UNCERTAIN", "RECOVERY_REQUIRED"}
_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def _count(mapping: Mapping[str, Any] | None, key: str) -> int:
    try:
        return max(0, int((mapping or {}).get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


class LivingAgentWorkProjection:
    """Deterministic presentation-only projection for the living Vishnu character.

    The projection consumes canonical Work and Attention snapshots. It owns no
    execution, policy, permission, approval, retry, recovery, review, evidence,
    or completion authority. Animation/state consumers must treat this object as
    display data only.
    """

    @staticmethod
    def _current_context(work: Mapping[str, Any], attention: Mapping[str, Any]) -> dict[str, Any]:
        items = list(attention.get("items") or [])
        if items:
            first = items[0]
            return {
                "project_name": first.get("project_name"),
                "work_order_title": first.get("work_order_title") or first.get("summary"),
                "worker_type": first.get("worker_type"),
            }

        priority = {
            "WAITING_APPROVAL": 0,
            "UNCERTAIN": 1,
            "RECOVERY_REQUIRED": 1,
            "RECOVERING": 2,
            "BLOCKED": 3,
            "VERIFYING": 4,
            "REVIEWING": 5,
            "REPLANNING": 6,
            "RETRYING": 7,
            "RUNNING": 8,
            "WAITING": 9,
            "COMPLETED": 10,
        }
        orders = list(work.get("work_orders") or [])
        orders.sort(
            key=lambda row: (
                priority.get(str(row.get("status") or "").upper(), 99),
                str(row.get("project_name") or "").lower(),
                str(row.get("title") or "").lower(),
            )
        )
        if not orders:
            return {"project_name": None, "work_order_title": None, "worker_type": None}
        first = orders[0]
        return {
            "project_name": first.get("project_name"),
            "work_order_title": first.get("title") or first.get("objective"),
            "worker_type": first.get("worker_type"),
        }

    @staticmethod
    def _running_state(worker_type: str | None) -> tuple[str, str]:
        worker = str(worker_type or "").strip().lower()
        if worker == "coding":
            return "coding", "Vishnu is coding against the current governed WorkOrder."
        if worker == "browser":
            return "browsing", "Vishnu is browsing for the current governed WorkOrder."
        if worker == "research":
            return "researching", "Vishnu is researching for the current governed WorkOrder."
        return "working", "Vishnu is working on canonical Project Work."

    @classmethod
    def project(cls, work: Mapping[str, Any], attention: Mapping[str, Any]) -> dict[str, Any]:
        task_counts = work.get("task_counts") or {}
        attention_counts = attention.get("counts") or {}
        items = list(attention.get("items") or [])
        orders = list(work.get("work_orders") or [])
        context = cls._current_context(work, attention)

        attention_total = _count(attention_counts, "total")
        approval_count = _count(attention_counts, "approval")
        recovery_count = _count(attention_counts, "recovery")
        review_count = _count(attention_counts, "review")
        blocked_count = _count(attention_counts, "blocked")
        verifying_count = _count(task_counts, "VERIFYING")

        uncertain = any(str(item.get("kind") or "") == "uncertain_effect" for item in items)
        replanning = _count(task_counts, "REPLANNING") > 0
        reviewing = _count(task_counts, "REVIEWING") > 0
        recovering = (
            recovery_count > 0
            or _count(task_counts, "RECOVERING") > 0
            or _count(task_counts, "RECOVERY_REQUIRED") > 0
        )
        waiting_approval = approval_count > 0 or _count(task_counts, "WAITING_APPROVAL") > 0
        blocked = blocked_count > 0 or _count(task_counts, "BLOCKED") > 0
        running = _count(task_counts, "RUNNING") + _count(task_counts, "RETRYING")

        if uncertain:
            state, activity, intensity = (
                "needs_attention",
                "An external effect is uncertain and requires deliberate owner review.",
                1.0,
            )
        elif waiting_approval:
            state, activity, intensity = (
                "waiting_approval",
                f"{max(approval_count, _count(task_counts, 'WAITING_APPROVAL'))} WorkOrder(s) are waiting for owner approval.",
                0.95,
            )
        elif recovering:
            state, activity, intensity = (
                "recovering",
                "Vishnu is reconciling governed recovery state; uncertain side effects are not retried blindly.",
                0.9,
            )
        elif review_count or reviewing:
            state, activity, intensity = (
                "reviewing",
                "Evidence, claims, or reviewer results require attention before completion can advance.",
                0.82,
            )
        elif blocked:
            state, activity, intensity = (
                "blocked",
                "Canonical Project Work is blocked and cannot advance automatically.",
                0.8,
            )
        elif replanning:
            state, activity, intensity = (
                "replanning",
                "Vishnu is preparing a governed replacement plan from the current canonical state.",
                0.75,
            )
        elif verifying_count:
            state, activity, intensity = (
                "verifying",
                f"{verifying_count} WorkOrder(s) are being verified against required evidence.",
                0.72,
            )
        elif running:
            state, activity = cls._running_state(context.get("worker_type"))
            intensity = 0.68
        elif _count(task_counts, "PLANNING") or _count(task_counts, "DRAFT"):
            state, activity, intensity = (
                "planning",
                "Vishnu is projecting the next governed WorkPlan; planning does not grant authority.",
                0.52,
            )
        else:
            total = sum(_count(task_counts, key) for key in task_counts)
            terminal = sum(_count(task_counts, key) for key in _TERMINAL_STATUSES)
            if total and terminal == total and not attention_total:
                state, activity, intensity = (
                    "completed",
                    "Canonical Project Work is terminal with no unresolved owner attention.",
                    0.2,
                )
            else:
                state, activity, intensity = (
                    "idle",
                    "No canonical Project Work currently requires a living-agent activity state.",
                    0.0,
                )

        active_worker_types = sorted(
            {
                str(order.get("worker_type") or "").strip()
                for order in orders
                if str(order.get("status") or "").upper() in (_ACTIVE_STATUSES | _ATTENTION_STATUSES)
                and str(order.get("worker_type") or "").strip()
            }
        )
        active_projects = {
            str(order.get("project_id") or "")
            for order in orders
            if str(order.get("status") or "").upper() in (_ACTIVE_STATUSES | _ATTENTION_STATUSES)
            and str(order.get("project_id") or "")
        }

        return {
            "authority": "presentation_only",
            "source": "canonical_work_attention",
            "state": state,
            "activity": activity,
            "intensity": intensity,
            "workers_active": len(active_worker_types),
            "active_worker_types": active_worker_types,
            "projects_active": max(len(active_projects), _count(work, "active_projects")),
            "needs_attention": attention_total > 0,
            "attention_count": attention_total,
            "approval_count": approval_count,
            "blocked_count": blocked_count,
            "recovery_count": recovery_count,
            "review_count": review_count,
            "verifying_count": verifying_count,
            "current_project_name": context.get("project_name"),
            "current_work_order_title": context.get("work_order_title"),
        }
