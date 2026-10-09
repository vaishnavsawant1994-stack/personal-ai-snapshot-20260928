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


def test_work_notification_bridge_deduplicates_same_state_transition(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    payload = {
        "goal_id": "goal-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "operation_id": "op-1",
        "state": "WAITING_APPROVAL",
    }
    events.emit("p10.task_dispatched", **payload)
    events.emit("p10.task_dispatched", **payload)

    rows = notifications.list("device-1")
    assert len(rows) == 1
    assert rows[0]["category"] == "needs_review"
    assert rows[0]["title"] == "Needs your review"
    bridge.close(); notifications.close()


def test_work_notification_bridge_only_notifies_verified_completion_path(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    common = {
        "goal_id": "goal-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "operation_id": "op-1",
    }
    events.emit("p10.task_dispatched", **common, state="RUNNING")
    assert notifications.list("device-1") == []

    # P10 emits task_dispatched=COMPLETED only after P6 reports VERIFIED/RECOVERED.
    events.emit("p10.task_dispatched", **common, state="COMPLETED")
    rows = notifications.list("device-1")
    assert len(rows) == 1
    assert rows[0]["category"] == "work_completed"
    assert "verified" in rows[0]["body"].lower()
    bridge.close(); notifications.close()


def test_uncertain_and_rejected_review_use_existing_attention_categories(tmp_path):
    events, notifications, bridge = _setup(tmp_path)
    events.emit(
        "p10.task_dispatched",
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
    # Lock-screen/in-app notification copy remains generic; Project details belong in the app.
    assert all("Sensitive Project Name" not in row["body"] for row in rows)
    bridge.close(); notifications.close()


def test_work_bridge_creates_no_notification_persistence_authority():
    assert not hasattr(WorkNotificationBridge, "_insert")
    assert not hasattr(WorkNotificationBridge, "save_preferences")
