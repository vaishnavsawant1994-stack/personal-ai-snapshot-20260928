from __future__ import annotations

import hashlib
from typing import Any

from notifications.service import EVENTS


WORK_NOTIFICATION_EVENTS = {
    "work.order.waiting_approval": (
        "needs_review",
        "Needs your review",
        "A governed WorkOrder is waiting for your approval.",
    ),
    "work.order.reauthentication_required": (
        "needs_review",
        "Needs your review",
        "A governed WorkOrder requires fresh owner authentication.",
    ),
    "work.order.blocked": (
        "blocked_work",
        "Blocked work",
        "A WorkOrder is blocked and needs attention.",
    ),
    "work.order.recovery_required": (
        "blocked_work",
        "Recovery required",
        "A WorkOrder requires recovery before it can continue.",
    ),
    "work.review.rejected": (
        "needs_review",
        "Needs your review",
        "A WorkOrder review did not pass.",
    ),
    "work.claim.rejected": (
        "needs_review",
        "Needs your review",
        "A WorkOrder completion claim could not be verified.",
    ),
    "work.order.completed": (
        "work_completed",
        "Work completed",
        "Vishnu completed and verified a WorkOrder.",
    ),
    "work.goal.completed": (
        "work_completed",
        "Work completed",
        "Vishnu completed and verified a Project goal.",
    ),
}


class WorkNotificationBridge:
    """Project canonical Work events into the existing NotificationService.

    Raw P10 signals are deliberately not consumed here. WorkEventNormalizer owns
    raw->canonical translation; this bridge owns no event bus, persistence, policy,
    approval, completion, or delivery authority.
    """

    _P10_STATE_EVENTS = {
        "WAITING_APPROVAL": "work.order.waiting_approval",
        "BLOCKED": "work.order.blocked",
        "FAILED": "work.order.blocked",
        "RECOVERING": "work.order.recovery_required",
        "RECOVERY_REQUIRED": "work.order.recovery_required",
        "UNCERTAIN": "work.order.recovery_required",
        "COMPLETED": "work.order.completed",
    }

    def __init__(self, events, notifications) -> None:
        self.events = events
        self.notifications = notifications
        self._unsubscribers = []
        EVENTS.update(WORK_NOTIFICATION_EVENTS)
        for event_name in WORK_NOTIFICATION_EVENTS:
            self._unsubscribers.append(
                events.subscribe(
                    event_name,
                    lambda event, name=event_name: notifications._on_event(name, event),
                )
            )

    @staticmethod
    def _event_id(event_name: str, event: dict[str, Any]) -> str:
        raw = "|".join(
            str(value or "")
            for value in (
                event_name,
                event.get("goal_id"),
                event.get("plan_id"),
                event.get("task_id"),
                event.get("work_order_id"),
                event.get("operation_id"),
                event.get("state"),
                event.get("state_version"),
            )
        )
        return "work-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    def _emit(self, event_name: str, source: dict[str, Any]) -> None:
        payload = {
            # Intentionally derive a canonical notification identity rather than
            # reusing the triggering evidence/claim event_id. Multiple proof events
            # may re-evaluate the same completion decision and must dedupe to one.
            "event_id": self._event_id(event_name, source),
            "goal_id": source.get("goal_id"),
            "plan_id": source.get("plan_id"),
            "task_id": source.get("task_id"),
            "work_order_id": source.get("work_order_id"),
            "operation_id": source.get("operation_id"),
            "state": source.get("state"),
            "authority": "notification_projection_only",
        }
        self.events.emit(event_name, **payload)

    def _on_task_dispatched(self, event: dict[str, Any]) -> None:
        state = str(event.get("state") or "").upper()
        event_name = self._P10_STATE_EVENTS.get(state)
        if event_name and state != "COMPLETED":
            self._emit(event_name, event)

    def _on_cancel_uncertain(self, event: dict[str, Any]) -> None:
        self._emit("work.order.recovery_required", {**event, "state": "UNCERTAIN"})

    def close(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubscribers.clear()
