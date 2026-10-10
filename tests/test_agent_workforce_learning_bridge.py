from __future__ import annotations

from core.events import EventBus
from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore
from future_intelligence.agent_workforce.learning_bridge import AgentLearningEventBridge


def setup(tmp_path):
    events = EventBus()
    service = AgentWorkforceService(AgentWorkforceStore(tmp_path / "agents.sqlite3"), events=events)
    coding = service.store.get_template_by_slug("coding")
    instance = service.create_instance(coding["id"], project_id="project-a")
    assignment = service.store.assign(instance["id"], project_id="project-a", work_order_id="work-a")
    bridge = AgentLearningEventBridge(service, events)
    return events, service, coding, instance, assignment, bridge


def test_blocked_work_automatically_records_exact_agent_version_learning(tmp_path):
    events, service, coding, instance, assignment, bridge = setup(tmp_path)
    events.emit(
        "work.order.blocked",
        event_id="workevt-blocked-1",
        work_order_id="work-a",
        project_id="project-a",
        state="BLOCKED",
        reason="Verification failed after repository change",
    )
    rows = service.store.list_observations(coding["id"], version_id=assignment["version_id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "work_blocked"
    assert rows[0]["project_id"] == "project-a"
    assert rows[0]["work_order_id"] == "work-a"
    assert rows[0]["evidence_ref"] == "work-event:workevt-blocked-1"
    assert "Verification failed" in rows[0]["summary"]
    assert rows[0]["score"] == -0.8
    bridge.close()


def test_replayed_canonical_event_is_idempotent(tmp_path):
    events, service, coding, _instance, assignment, bridge = setup(tmp_path)
    payload = dict(
        event_id="workevt-recovery-1",
        work_order_id="work-a",
        project_id="project-a",
        state="RECOVERY_REQUIRED",
    )
    events.emit("work.order.recovery_required", **payload)
    events.emit("work.order.recovery_required", **payload)
    rows = service.store.list_observations(coding["id"], version_id=assignment["version_id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "recovery_required"
    bridge.close()


def test_mismatched_project_event_never_contaminates_assignment(tmp_path):
    events, service, coding, _instance, assignment, bridge = setup(tmp_path)
    events.emit(
        "work.review.rejected",
        event_id="workevt-cross-project",
        work_order_id="work-a",
        project_id="project-b",
        review_state="rejected",
    )
    assert service.store.list_observations(coding["id"], version_id=assignment["version_id"]) == []
    bridge.close()


def test_unassigned_or_noncanonical_events_do_not_create_learning(tmp_path):
    events, service, coding, _instance, assignment, bridge = setup(tmp_path)
    events.emit("work.order.blocked", event_id="workevt-no-assignment", work_order_id="unknown", project_id="project-a")
    events.emit("work.order.blocked", work_order_id="work-a", project_id="project-a")
    events.emit("random.event", event_id="random-1", work_order_id="work-a", project_id="project-a")
    assert service.store.list_observations(coding["id"], version_id=assignment["version_id"]) == []
    bridge.close()


def test_success_events_record_positive_learning_for_same_version(tmp_path):
    events, service, coding, _instance, assignment, bridge = setup(tmp_path)
    events.emit(
        "work.order.completed",
        event_id="workevt-complete-1",
        work_order_id="work-a",
        project_id="project-a",
        state="COMPLETED",
    )
    rows = service.store.list_observations(coding["id"], version_id=assignment["version_id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "verified_completion"
    assert rows[0]["score"] == 1.0
    bridge.close()
