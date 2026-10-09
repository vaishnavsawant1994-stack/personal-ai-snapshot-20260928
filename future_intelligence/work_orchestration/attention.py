from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from approvals.projection import ApprovalsProjection
from server.global_work_api import GlobalWorkService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AttentionItem:
    id: str
    kind: str
    severity: str
    status: str
    title: str
    summary: str
    reason: str
    authority: str
    action_type: str
    deep_link: str
    created_at: str | float | None = None
    updated_at: str | float | None = None
    expires_at: str | float | None = None
    project_id: str | None = None
    project_name: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    work_order_id: str | None = None
    work_order_title: str | None = None
    worker_type: str | None = None
    execution_id: str | None = None
    approval_id: str | None = None
    recovery_id: str | None = None
    claim_id: str | None = None
    evidence_id: str | None = None
    expected_effect: str | None = None
    requires_owner_action: bool = True
    requires_reauthentication: bool = False
    recoverable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


_KIND_PRIORITY = {
    "uncertain_effect": 0,
    "approval_required": 1,
    "recovery_required": 2,
    "reauthentication_required": 3,
    "verification_failed": 4,
    "review_failed": 4,
    "claim_unsupported": 5,
    "blocked": 6,
    "capability_unavailable": 7,
    "replan_required": 8,
    "retest_required": 8,
    "owner_decision_required": 9,
}
_SEVERITY_PRIORITY = {"critical": 0, "urgent": 1, "attention": 2, "review": 3, "info": 4}


def _stable_id(kind: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join(str(part or "") for part in (kind, *parts)).encode("utf-8")
    ).hexdigest()[:24]
    return f"attn-{digest}"


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text[:limit]


class WorkAttentionService:
    """Read-only canonical projection of owner attention across governed Work.

    ApprovalManager, P10/P6, ToolRegistry, and recovery remain authoritative.
    This service only joins already-safe projections so every surface can show
    the same attention state without inventing a second decision system.
    """

    def __init__(
        self,
        runtime: dict,
        store,
        *,
        work_service: GlobalWorkService | None = None,
        approvals_projection: ApprovalsProjection | None = None,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.work_service = work_service or GlobalWorkService(runtime, store)
        if approvals_projection is None:
            executor = runtime.get("agent_executor")
            manager = getattr(executor, "approvals", None) if executor is not None else None
            if manager is None:
                raise RuntimeError("approval authority unavailable")
            approvals_projection = ApprovalsProjection(manager)
        self.approvals = approvals_projection

    @staticmethod
    def _work_key(item: dict) -> tuple[str, str]:
        return (str(item.get("plan_id") or ""), str(item.get("task_id") or ""))

    @staticmethod
    def _work_context(item: dict) -> dict[str, Any]:
        return {
            "project_id": item.get("project_id"),
            "project_name": item.get("project_name"),
            "goal_id": item.get("goal_id"),
            "plan_id": item.get("plan_id"),
            "plan_version": item.get("plan_version"),
            "work_order_id": item.get("work_order_id"),
            "work_order_title": item.get("title"),
            "worker_type": item.get("worker_type"),
            "execution_id": item.get("execution_id"),
        }

    @staticmethod
    def _work_link(item: dict, *, section: str = "live") -> str:
        project_id = _safe_text(item.get("project_id"), 160)
        work_order_id = _safe_text(item.get("work_order_id"), 200)
        if project_id:
            suffix = f"&work_order={work_order_id}" if work_order_id else ""
            return f"/iphone/?project={project_id}&section={section}{suffix}"
        return "/iphone/"

    def _enrich_work_orders(self, snapshot: dict[str, Any]) -> list[dict]:
        """Join safe P10 identifiers needed to bind approval/recovery context."""
        rows = [dict(item) for item in snapshot.get("work_orders") or []]
        if not rows:
            return rows
        autonomy = self.work_service._autonomy()
        by_plan: dict[str, dict[str, dict]] = {}
        work_meta: dict[str, dict[str, Any]] = {}
        for project in snapshot.get("projects") or []:
            plan_id = str(project.get("plan_id") or "")
            if not plan_id or plan_id in by_plan:
                continue
            try:
                p10 = autonomy.plan(plan_id, owner_id="owner")
                work_plan = autonomy.work_plan(plan_id, owner_id="owner")
            except (KeyError, RuntimeError):
                continue
            by_plan[plan_id] = {
                str(task.get("id") or ""): dict(task)
                for task in p10.get("tasks") or []
                if task.get("id")
            }
            work_meta[plan_id] = {
                "goal_id": work_plan.get("goal_id"),
                "plan_version": int(work_plan.get("version") or 1),
            }
        for row in rows:
            plan_id = str(row.get("plan_id") or "")
            task_id = str(row.get("task_id") or "")
            task = by_plan.get(plan_id, {}).get(task_id, {})
            row.update(work_meta.get(plan_id, {}))
            row["execution_id"] = (
                task.get("operation_id")
                or task.get("result_ref")
                or task.get("execution_id")
            )
            row["recovery_id"] = task.get("recovery_id") or task.get("operation_id")
        return rows

    def _approval_items(
        self,
        work_orders: list[dict],
        *,
        owner_id: str,
        device_id: str | None,
        session_id: str | None,
        limit: int,
    ) -> tuple[list[AttentionItem], set[str]]:
        pending = self.approvals.pending(
            owner_id=owner_id,
            device_id=device_id,
            session_id=session_id,
            limit=limit,
        )
        by_execution = {
            str(item.get("execution_id")): item
            for item in work_orders
            if item.get("execution_id")
        }
        result: list[AttentionItem] = []
        mapped_work_orders: set[str] = set()
        for approval in pending:
            execution_id = str(approval.get("execution_id") or "")
            work = by_execution.get(execution_id, {})
            work_order_id = str(work.get("work_order_id") or "")
            if work_order_id:
                mapped_work_orders.add(work_order_id)
            title = _safe_text(work.get("title") or "Approval required", 200)
            tool_id = _safe_text(approval.get("tool_id"), 160)
            destination = _safe_text(approval.get("destination"), 240)
            effect = f"{tool_id} → {destination}" if destination else tool_id
            summary = (
                f"{_safe_text(work.get('project_name'), 120)} · {title}"
                if work.get("project_name")
                else title
            )
            approval_id = str(approval.get("approval_id") or "")
            result.append(
                AttentionItem(
                    id=_stable_id("approval_required", approval_id, execution_id),
                    kind="approval_required",
                    severity="urgent",
                    status="pending",
                    title="Needs your approval",
                    summary=summary,
                    reason="A governed external or consequential action is waiting for the owner.",
                    expected_effect=effect or None,
                    authority="approval_manager",
                    action_type="review_approval",
                    deep_link=f"/iphone/?section=approvals&approval={approval_id}",
                    created_at=approval.get("created_at"),
                    updated_at=approval.get("created_at"),
                    expires_at=approval.get("expires_at"),
                    approval_id=approval_id or None,
                    requires_owner_action=True,
                    **self._work_context(work),
                )
            )
        return result, mapped_work_orders

    def _work_items(
        self,
        work_orders: list[dict],
        *,
        approval_bound_work_orders: set[str],
    ) -> list[AttentionItem]:
        result: list[AttentionItem] = []
        for work in work_orders:
            status = str(work.get("status") or "").upper()
            work_order_id = str(work.get("work_order_id") or "")
            base = {
                **self._work_context(work),
                "updated_at": work.get("updated_at"),
                "created_at": work.get("updated_at"),
                "requires_owner_action": True,
            }
            if status == "WAITING_APPROVAL":
                if work_order_id in approval_bound_work_orders:
                    continue
                result.append(
                    AttentionItem(
                        id=_stable_id("owner_decision_required", work.get("plan_id"), work.get("task_id")),
                        kind="owner_decision_required",
                        severity="review",
                        status="waiting_approval",
                        title="Approval context is pending",
                        summary=_safe_text(work.get("title") or "WorkOrder is waiting for approval"),
                        reason="The WorkOrder reports WAITING_APPROVAL but no owner-visible approval ticket is currently mapped.",
                        authority="existing_p10_p6_runtime",
                        action_type="inspect_work",
                        deep_link=self._work_link(work),
                        **base,
                    )
                )
            elif status == "UNCERTAIN":
                result.append(
                    AttentionItem(
                        id=_stable_id("uncertain_effect", work.get("plan_id"), work.get("task_id")),
                        kind="uncertain_effect",
                        severity="critical",
                        status="uncertain",
                        title="External effect is uncertain",
                        summary=_safe_text(work.get("title") or "Work outcome is uncertain"),
                        reason="The runtime cannot prove whether the external side effect occurred. Do not retry blindly.",
                        authority="recovery_authority",
                        action_type="inspect_recovery",
                        deep_link=self._work_link(work),
                        recoverable=True,
                        **base,
                    )
                )
            elif status in {"RECOVERY_REQUIRED", "RECOVERING"}:
                result.append(
                    AttentionItem(
                        id=_stable_id("recovery_required", work.get("plan_id"), work.get("task_id")),
                        kind="recovery_required",
                        severity="urgent",
                        status=status.lower(),
                        title="Recovery required",
                        summary=_safe_text(work.get("title") or "WorkOrder requires recovery"),
                        reason="The governed runtime requires recovery or reconciliation before this work can continue.",
                        authority="recovery_authority",
                        action_type="inspect_recovery",
                        deep_link=self._work_link(work),
                        recoverable=True,
                        **base,
                    )
                )
            elif status == "BLOCKED":
                result.append(
                    AttentionItem(
                        id=_stable_id("blocked", work.get("plan_id"), work.get("task_id")),
                        kind="blocked",
                        severity="attention",
                        status="blocked",
                        title="Work is blocked",
                        summary=_safe_text(work.get("title") or "WorkOrder is blocked"),
                        reason="The WorkOrder cannot continue until its blocker is resolved.",
                        authority="existing_p10_p6_runtime",
                        action_type="inspect_work",
                        deep_link=self._work_link(work),
                        **base,
                    )
                )
            elif status == "FAILED":
                result.append(
                    AttentionItem(
                        id=_stable_id("verification_failed", work.get("plan_id"), work.get("task_id")),
                        kind="verification_failed",
                        severity="attention",
                        status="failed",
                        title="Work failed or could not be verified",
                        summary=_safe_text(work.get("title") or "WorkOrder failed"),
                        reason="The canonical WorkOrder is failed and must be inspected before the Project can be considered complete.",
                        authority="existing_p10_p6_runtime",
                        action_type="inspect_work",
                        deep_link=self._work_link(work),
                        **base,
                    )
                )
        return result

    @staticmethod
    def _sort_key(item: AttentionItem) -> tuple:
        return (
            _KIND_PRIORITY.get(item.kind, 99),
            _SEVERITY_PRIORITY.get(item.severity, 99),
            str(item.project_name or "").lower(),
            str(item.work_order_title or item.title or "").lower(),
            item.id,
        )

    def summary(
        self,
        *,
        owner_id: str = "owner",
        device_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        work = self.work_service.summary(work_order_limit=500)
        work_orders = self._enrich_work_orders(work)
        approval_items, mapped = self._approval_items(
            work_orders,
            owner_id=owner_id,
            device_id=device_id,
            session_id=session_id,
            limit=limit,
        )
        items = approval_items + self._work_items(
            work_orders,
            approval_bound_work_orders=mapped,
        )
        items.sort(key=self._sort_key)
        items = items[:limit]
        counts = {
            "total": len(items),
            "approval": sum(item.kind == "approval_required" for item in items),
            "recovery": sum(item.kind in {"recovery_required", "uncertain_effect"} for item in items),
            "review": sum(item.kind in {"verification_failed", "review_failed", "claim_unsupported"} for item in items),
            "blocked": sum(item.kind == "blocked" for item in items),
            "urgent": sum(item.severity in {"critical", "urgent"} for item in items),
        }
        return {
            "authority": "read_only_projection",
            "decision_authorities": {
                "approval": "approval_manager",
                "execution": "existing_p10_p6_runtime",
                "recovery": "recovery_authority",
            },
            "updated_at": _now(),
            "counts": counts,
            "items": [item.to_dict() for item in items],
        }

    def detail(
        self,
        attention_id: str,
        *,
        owner_id: str = "owner",
        device_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        snapshot = self.summary(
            owner_id=owner_id,
            device_id=device_id,
            session_id=session_id,
            limit=200,
        )
        return next((item for item in snapshot["items"] if item["id"] == str(attention_id)), None)
