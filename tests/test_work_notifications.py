from pathlib import Path

from core.events import EventBus
from future_intelligence.work_orchestration.notification_bridge import WorkNotificationBridge
from notifications.service import NotificationService


class _Registry:
    def list(self):
        return [{"id": "device-1", "revoked": False, "metadata": {}}]

    def metadata(self, _device_id):
        return {}

    def set_metadata(self, *_args, **_kwargs):
        return True


class _Preferences:
    def get(self, key, default=None):
        if key == "notifications_preferences":
            return {"quiet_hours": {"enabled": False}}
        return default

    def set(self, *_args, **_kwargs):
        return True


def _setup(tmp_path: Path):
    events = EventBus()
    notifications = NotificationService(
        tmp_path / "notifications.sqlite3",
        _Registry(),
        events=events,
        owner_preferences=_Preferences(),
        start_scheduler=False,
    )
    bridge = WorkNotificationBridge(events, notifications)
    return events, notifications, bridge


def test_work_notification_bridge_deduplicates_same_canonical_transition(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    payload = {
        "event_id": "wait-1",
        "goal_id": "goal-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "operation_id": "op-1",
        "state": "WAITING_APPROVAL",
    }
    events.emit("work.order.waiting_approval", **payload)
    events.emit("work.order.waiting_approval", **payload)

    rows = notifications.list("device-1")
    assert len(rows) == 1
    assert rows[0]["category"] == "needs_review"
    assert rows[0]["title"] == "Needs your review"
    bridge.close(); notifications.close()


def test_raw_p10_completion_no_longer_creates_notification_and_canonical_completion_does(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    common = {
        "goal_id": "goal-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "operation_id": "op-1",
    }
    events.emit("p10.task_dispatched", **common, state="RUNNING")
    events.emit("p10.task_dispatched", **common, state="COMPLETED")
    assert notifications.list("device-1") == []

    events.emit("work.order.completed", **common, event_id="canonical-complete-1", state="COMPLETED")
    rows = notifications.list("device-1")
    assert len(rows) == 1
    assert rows[0]["category"] == "work_completed"
    assert "verified" in rows[0]["body"].lower()
    bridge.close(); notifications.close()


def test_recovery_and_rejected_review_use_existing_attention_categories(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    # Raw P10 uncertainty is ignored by the notification bridge after normalization.
    events.emit(
        "p10.task_dispatched",
        goal_id="goal-1",
        plan_id="plan-1",
        task_id="task-1",
        operation_id="op-1",
        state="UNCERTAIN",
        project_name="Sensitive Project Name",
    )
    assert notifications.list("device-1") == []

    events.emit(
        "work.order.recovery_required",
        event_id="recovery-1",
        goal_id="goal-1",
        plan_id="plan-1",
        task_id="task-1",
        operation_id="op-1",
        state="UNCERTAIN",
        project_name="Sensitive Project Name",
    )
    events.emit(
        "work.review.rejected",
        event_id="review-1",
        project_id="project-1",
        work_order_id="wo-1",
    )
    rows = notifications.list("device-1")
    assert {row["category"] for row in rows} == {"blocked_work", "needs_review"}
    assert all("Sensitive Project Name" not in row["body"] for row in rows)
    bridge.close(); notifications.close()


def test_work_bridge_creates_no_raw_p10_subscription_or_notification_persistence_authority():
    assert not hasattr(WorkNotificationBridge, "_insert")
    assert not hasattr(WorkNotificationBridge, "save_preferences")
