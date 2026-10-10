from __future__ import annotations

from typing import Any, Mapping


LEARNING_EVENTS = {
    "work.order.blocked": ("work_blocked", -0.8),
    "work.order.recovery_required": ("recovery_required", -1.0),
    "work.claim.rejected": ("claim_rejected", -1.0),
    "work.review.rejected": ("review_rejected", -0.9),
    "work.order.completed": ("verified_completion", 1.0),
    "work.claim.verified": ("verified_claim", 0.8),
    "work.review.passed": ("review_passed", 0.8),
}


class AgentLearningEventBridge:
    """Project canonical Work outcomes -> durable agent learning observations.

    Canonical Work remains authoritative. This bridge only records bounded,
    provenance-linked observations for the exact agent version assigned to the
    WorkOrder. Replaying the same canonical event is idempotent.
    """

    def __init__(self, workforce, events) -> None:
        self.workforce = workforce
        self.events = events
        self._unsubscribers = [
            events.subscribe(name, self._handler(name)) for name in LEARNING_EVENTS
        ]

    def _handler(self, event_name: str):
        def handle(event: Mapping[str, Any]) -> None:
            self.observe(event_name, event)
        return handle

    @staticmethod
    def _summary(event_name: str, event: Mapping[str, Any]) -> str:
        state = str(event.get("state") or event.get("status") or "").strip()
        reason = " ".join(str(event.get("reason") or "").split())[:700]
        claim_state = str(event.get("claim_state") or "").strip()
        review_state = str(event.get("review_state") or "").strip()
        parts = [f"Canonical {event_name}"]
        if state:
            parts.append(f"state={state}")
        if claim_state:
            parts.append(f"claim={claim_state}")
        if review_state:
            parts.append(f"review={review_state}")
        if reason:
            parts.append(f"reason={reason}")
        return "; ".join(parts)[:1000]

    def observe(self, event_name: str, event: Mapping[str, Any]) -> dict | None:
        config = LEARNING_EVENTS.get(event_name)
        if config is None:
            return None
        work_order_id = str(event.get("work_order_id") or event.get("task_id") or "").strip()
        event_id = str(event.get("event_id") or "").strip()
        if not work_order_id or not event_id:
            return None
        assignment = self.workforce._assignment_for_work_order(work_order_id)
        if assignment is None:
            return None
        instance = self.workforce.store.get_instance(assignment["instance_id"])
        project_id = str(event.get("project_id") or assignment.get("project_id") or "").strip()
        if project_id != str(assignment.get("project_id") or ""):
            # A mismatched canonical projection can never contaminate another Project.
            return None
        evidence_ref = f"work-event:{event_id}"[:1000]
        with self.workforce.store.lock:
            existing = self.workforce.store.connection.execute(
                """SELECT * FROM agent_evolution_observations
                   WHERE template_id=? AND version_id=? AND evidence_ref=? LIMIT 1""",
                (instance["template_id"], assignment["version_id"], evidence_ref),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            kind, score = config
            observation = self.workforce.record_learning(
                instance["template_id"],
                assignment["version_id"],
                kind=kind,
                summary=self._summary(event_name, event),
                project_id=project_id,
                work_order_id=work_order_id,
                score=score,
                evidence_ref=evidence_ref,
            )
        return observation

    def close(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubscribers.clear()
