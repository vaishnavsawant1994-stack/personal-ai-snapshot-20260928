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
    "work.order.failed": (
        "blocked_work",
        "Blocked work",
        "A WorkOrder failed and needs attention.",
    ),
    "work.order.recovery_required": (
        "blocked_work",
        "Recovery required",
        "A WorkOrder requires recovery before it can continue.",
    ),
    "work.order.uncertain": (
        "blocked_work",
        "Outcome needs reconciliation",
        "An external WorkOrder outcome is uncertain. Open Vishnu to review it.",
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
    """Translate qualified orchestration events into the existing notification service.

    The bridge owns no persistence or notification delivery policy. It emits stable,
    generic work events and delegates quiet-hours, channels, push, and dedupe to the
    existing NotificationService.
    """

    _P10_STATE_EVENTS = {
        "WAITING_APPROVAL": "work.order.waiting_approval",
        "BLOCKED": "work.order.blocked",
        "FAILED": "work.order.failed",
        "RECOVERING": "work.order.recovery_required",
        "RECOVERY_REQUIRED": "work.order.recovery_required",
        "UNCERTAIN": "work.order.uncertain",
        # P10 only reaches COMPLETED from the governed dispatch path after the
        # P6 operation outcome is VERIFIED or RECOVERED.
        "COMPLETED": "work.order.completed",
    }

    def __init__(self, events, notifications) -> None:
        self.events = events
        self.notifications = notifications
        self._unsubscribers = []
        EVENTS.update(WORK_NOTIFICATION_EVENTS)
        # NotificationService subscribed before FutureIntelligenceProgram exists,
        # so subscribe the newly introduced work events explicitly while reusing
        # its canonical delivery method and existing database.
        for event_name in WORK_NOTIFICATION_EVENTS:
            self._unsubscribers.append(
                events.subscribe(
                    event_name,
                    lambda event, name=event_name: notifications._on_event(name, event),
                )
            )
        self._unsubscribers.extend(
            [
                events.subscribe("p10.task_dispatched", self._on_task_dispatched),
                events.subscribe("p10.cancel_uncertain", self._on_cancel_uncertain),
            ]
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
                event.get("operation_id"),
                event.get("state"),
                event.get("state_version"),
            )
        )
        return "work-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    def _emit(self, event_name: str, source: dict[str, Any]) -> None:
        payload = {
            "event_id": self._event_id(event_name, source),
            "goal_id": source.get("goal_id"),
            "plan_id": source.get("plan_id"),
            "task_id": source.get("task_id"),
            "operation_id": source.get("operation_id"),
            "state": source.get("state"),
            "authority": "notification_projection_only",
        }
        self.events.emit(event_name, **payload)

    def _on_task_dispatched(self, event: dict[str, Any]) -> None:
        state = str(event.get("state") or "").upper()
        event_name = self._P10_STATE_EVENTS.get(state)
        if event_name:
            self._emit(event_name, event)

    def _on_cancel_uncertain(self, event: dict[str, Any]) -> None:
        self._emit("work.order.uncertain", {**event, "state": "UNCERTAIN"})

    def close(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubscribers.clear()
