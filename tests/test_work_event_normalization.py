from core.events import EventBus
from future_intelligence.work_orchestration.event_normalization import (
    CANONICAL_WORK_EVENTS,
    WorkEventNormalizer,
)


EXPECTED = (
    "work.goal.created", "work.goal.completed", "work.goal.failed",
    "work.plan.created", "work.plan.reviewed", "work.plan.ready", "work.plan.hold",
    "work.order.queued", "work.order.started", "work.order.waiting_approval",
    "work.order.reauthentication_required", "work.order.blocked", "work.order.recovery_required",
    "work.order.verifying", "work.order.reviewing", "work.order.completed",
    "work.evidence.recorded", "work.claim.proposed", "work.claim.verified", "work.claim.rejected",
    "work.review.passed", "work.review.rejected", "work.retest.started", "work.retest.completed",
    "work.replan.started", "work.replan.completed",
)


class _Autonomy:
    def __init__(self, *, passed=False, state="verifying"):
        self.passed = passed; self.state = state
    def work_order_completion(self, plan_id, task_id, *, owner_id):
        return {"passed": self.passed, "state": self.state, "review_state": self.state}


def _capture(events):
    rows=[]
    for name in CANONICAL_WORK_EVENTS:
        events.subscribe(name, lambda event, n=name: rows.append((n, dict(event))))
    return rows


def test_taxonomy_is_frozen_to_the_product_contract():
    assert CANONICAL_WORK_EVENTS == EXPECTED
    assert len(CANONICAL_WORK_EVENTS) == len(set(CANONICAL_WORK_EVENTS))


def test_raw_p10_states_normalize_without_raw_completed_becoming_canonical_complete():
    events=EventBus(); rows=_capture(events); normalizer=WorkEventNormalizer(events,autonomy=_Autonomy(passed=False,state="verifying"))
    common={"goal_id":"g","plan_id":"p","task_id":"t","work_order_id":"wo","operation_id":"op"}
    events.emit("p10.task_dispatched",**common,state="WAITING_APPROVAL")
    events.emit("p10.task_dispatched",**common,state="UNCERTAIN")
    events.emit("p10.task_dispatched",**common,state="COMPLETED")
    names=[name for name,_ in rows]
    assert names == ["work.order.waiting_approval","work.order.recovery_required","work.order.verifying"]
    assert "work.order.completed" not in names
    normalizer.close()


def test_raw_completed_that_already_passes_judge_still_does_not_emit_completed_here():
    events=EventBus(); rows=_capture(events); normalizer=WorkEventNormalizer(events,autonomy=_Autonomy(passed=True,state="complete"))
    events.emit("p10.task_state",goal_id="g",plan_id="p",task_id="t",state="COMPLETED")
    assert rows == []
    normalizer.close()


def test_completion_observation_preserves_real_evidence_and_claim_ids():
    events=EventBus(); rows=_capture(events); normalizer=WorkEventNormalizer(events)
    events.emit("p10.work_completion_observed",goal_id="g",plan_id="p",task_id="t",work_order_id="wo",evidence_id="ev-1",claim_id="cl-1",claim_state="verified",evidence_gate_passed=True,projection_mode="observe_only")
    names=[name for name,_ in rows]
    assert names == ["work.evidence.recorded","work.claim.proposed","work.claim.verified"]
    assert all(row["evidence_id"] == "ev-1" for _,row in rows)
    assert all(row["claim_id"] == "cl-1" for _,row in rows)
    normalizer.close()


def test_review_and_replan_events_normalize_to_single_taxonomy():
    events=EventBus(); rows=_capture(events); normalizer=WorkEventNormalizer(events)
    events.emit("p10.hierarchical_plan_ready",goal_id="g",plan_id="p",work_plan_id="wp",readiness="ready",readiness_score=100)
    events.emit("p10.replan_started_versioned",goal_id="g",plan_id="p",replan_count=1,reason="new evidence",trigger="review")
    events.emit("p10.replanned_versioned",goal_id="g",plan_id="p",replan_count=1,delta_id="d1",reason="new evidence",trigger="review")
    names=[name for name,_ in rows]
    assert names == ["work.plan.reviewed","work.review.passed","work.plan.ready","work.replan.started","work.replan.completed"]
    normalizer.close()


def test_canonical_events_are_audited_with_safe_payload_only():
    events=EventBus(); audited=[]
    normalizer=WorkEventNormalizer(events,audit=lambda category,action,payload: audited.append((category,action,dict(payload))))
    events.emit("p10.task_state",goal_id="g",plan_id="p",task_id="t",state="BLOCKED",token="never",system_prompt="never",parameters={"secret":"never"})
    assert len(audited) == 1
    category,action,payload=audited[0]
    assert category == "work" and action == "work.order.blocked"
    assert payload["canonical_event"] == "work.order.blocked"
    assert payload["goal_id"] == "g" and payload["task_id"] == "t"
    serialized=repr(payload).lower()
    assert "never" not in serialized and "token" not in serialized and "system_prompt" not in serialized and "parameters" not in serialized
    normalizer.close()


def test_duplicate_raw_transition_emits_and_audits_once_per_normalizer_lifetime():
    events=EventBus(); rows=_capture(events); audited=[]
    normalizer=WorkEventNormalizer(events,audit=lambda c,a,p: audited.append((c,a,p)))
    payload={"goal_id":"g","plan_id":"p","task_id":"t","operation_id":"op","state":"WAITING_APPROVAL"}
    events.emit("p10.task_dispatched",**payload); events.emit("p10.task_dispatched",**payload)
    assert [name for name,_ in rows] == ["work.order.waiting_approval"]
    assert len(audited) == 1
    normalizer.close()
