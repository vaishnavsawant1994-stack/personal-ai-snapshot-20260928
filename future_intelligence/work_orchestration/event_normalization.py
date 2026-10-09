from __future__ import annotations

import hashlib
from typing import Any, Mapping


CANONICAL_WORK_EVENTS = (
    "work.goal.created",
    "work.goal.completed",
    "work.goal.failed",
    "work.plan.created",
    "work.plan.reviewed",
    "work.plan.ready",
    "work.plan.hold",
    "work.order.queued",
    "work.order.started",
    "work.order.waiting_approval",
    "work.order.reauthentication_required",
    "work.order.blocked",
    "work.order.recovery_required",
    "work.order.verifying",
    "work.order.reviewing",
    "work.order.completed",
    "work.evidence.recorded",
    "work.claim.proposed",
    "work.claim.verified",
    "work.claim.rejected",
    "work.review.passed",
    "work.review.rejected",
    "work.retest.started",
    "work.retest.completed",
    "work.replan.started",
    "work.replan.completed",
)

_SAFE_KEYS = (
    "goal_id", "project_id", "plan_id", "work_plan_id", "task_id", "work_order_id",
    "operation_id", "evidence_id", "claim_id", "delta_id", "state", "status",
    "claim_state", "review_state", "domain_claim_type", "readiness", "readiness_score",
    "score", "replan_count", "version", "from_version", "to_version", "trigger",
    "reason", "authority", "projection_mode", "evidence_gate_passed",
)

_SECRET_MARKERS = (
    "token", "password", "secret", "authorization", "cookie", "credential",
    "private_key", "api_key", "apikey", "raw_prompt", "system_prompt", "parameters",
)


def _state(event: Mapping[str, Any]) -> str:
    return str(event.get("state") or event.get("status") or "").strip().upper()


def _safe_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _SAFE_KEYS:
        value = event.get(key)
        if value is None:
            continue
        normalized = key.lower()
        if any(marker in normalized for marker in _SECRET_MARKERS):
            continue
        if isinstance(value, str):
            payload[key] = value[:1000]
        elif isinstance(value, (bool, int, float)):
            payload[key] = value
    return payload


class WorkEventNormalizer:
    """Translate raw orchestration signals onto the canonical `work.*` taxonomy.

    EventBus remains the only event bus. This class owns no execution, completion,
    review, evidence, notification or Activity persistence authority; it only emits
    stable canonical projections and mirrors those exact events into the existing
    audit store so Activities can consume the same taxonomy.
    """

    def __init__(self, events: Any, *, autonomy: Any = None, audit=None) -> None:
        self.events = events
        self.autonomy = autonomy
        self.audit = audit
        self._seen: set[str] = set()
        self._unsubscribers = []

        raw = {
            "p10.goal_created": self._goal_created,
            "p10.plan_ready": self._plan_created,
            "p10.hierarchical_plan_ready": self._plan_ready,
            "p10.hierarchical_plan_hold": self._plan_hold,
            "p10.task_state": self._task_state,
            "p10.task_dispatched": self._task_state,
            "p10.cancel_uncertain": self._cancel_uncertain,
            "p10.work_completion_observed": self._completion_observed,
            "p10.replan_started_versioned": self._replan_started,
            "p10.replanned_versioned": self._replan_completed,
            "p10.retest_started": lambda event: self._emit("work.retest.started", event),
            "p10.retest_completed": lambda event: self._emit("work.retest.completed", event),
        }
        for name, handler in raw.items():
            self._unsubscribers.append(events.subscribe(name, handler))
        for name in CANONICAL_WORK_EVENTS:
            self._unsubscribers.append(events.subscribe(name, lambda event, canonical=name: self._audit(canonical, event)))

    @staticmethod
    def event_id(event_name: str, event: Mapping[str, Any]) -> str:
        payload = _safe_payload(event)
        raw = "|".join(
            str(payload.get(key) or "")
            for key in (
                "goal_id", "project_id", "plan_id", "work_plan_id", "task_id",
                "work_order_id", "operation_id", "evidence_id", "claim_id", "delta_id",
                "state", "status", "claim_state", "replan_count", "version",
            )
        )
        return "workevt-" + hashlib.sha256(f"{event_name}|{raw}".encode("utf-8")).hexdigest()[:40]

    def _emit(self, event_name: str, source: Mapping[str, Any], **extra: Any) -> None:
        if event_name not in CANONICAL_WORK_EVENTS:
            raise ValueError(f"non-canonical Work event: {event_name}")
        payload = {**_safe_payload(source), **_safe_payload(extra)}
        event_id = self.event_id(event_name, payload)
        if event_id in self._seen:
            return
        self._seen.add(event_id)
        payload.update({"event_id": event_id, "canonical": True, "event_name": event_name})
        self.events.emit(event_name, **payload)

    def _audit(self, event_name: str, event: Mapping[str, Any]) -> None:
        if self.audit is None:
            return
        payload = _safe_payload(event)
        payload.update({
            "event_id": str(event.get("event_id") or self.event_id(event_name, event)),
            "canonical_event": event_name,
        })
        try:
            self.audit("work", event_name, payload)
        except Exception:
            # Activity projection must never gain authority over the runtime.
            pass

    def _goal_created(self, event: Mapping[str, Any]) -> None:
        self._emit("work.goal.created", event)

    def _plan_created(self, event: Mapping[str, Any]) -> None:
        self._emit("work.plan.created", event)

    def _plan_ready(self, event: Mapping[str, Any]) -> None:
        self._emit("work.plan.reviewed", event)
        self._emit("work.review.passed", event, review_state="passed")
        self._emit("work.plan.ready", event)

    def _plan_hold(self, event: Mapping[str, Any]) -> None:
        self._emit("work.plan.reviewed", event)
        self._emit("work.review.rejected", event, review_state="rejected")
        self._emit("work.plan.hold", event)

    def _task_state(self, event: Mapping[str, Any]) -> None:
        state = _state(event)
        mapping = {
            "WAITING": "work.order.queued",
            "READY": "work.order.queued",
            "RUNNING": "work.order.started",
            "WAITING_APPROVAL": "work.order.waiting_approval",
            "REAUTHENTICATION_REQUIRED": "work.order.reauthentication_required",
            "BLOCKED": "work.order.blocked",
            "FAILED": "work.order.blocked",
            "RECOVERING": "work.order.recovery_required",
            "RECOVERY_REQUIRED": "work.order.recovery_required",
            "UNCERTAIN": "work.order.recovery_required",
            "VERIFYING": "work.order.verifying",
            "REVIEWING": "work.order.reviewing",
        }
        if state in mapping:
            self._emit(mapping[state], event, state=state)
            return
        if state != "COMPLETED":
            return
        # Raw P10 completion is execution completion only. Completion Judge is the
        # sole source of `work.order.completed` through completion_propagation.
        plan_id = str(event.get("plan_id") or "")
        task_id = str(event.get("task_id") or "")
        if not plan_id or not task_id or self.autonomy is None:
            self._emit("work.order.verifying", event, state="VERIFYING")
            return
        try:
            decision = self.autonomy.work_order_completion(plan_id, task_id, owner_id="owner")
        except (KeyError, RuntimeError, PermissionError):
            self._emit("work.order.verifying", event, state="VERIFYING")
            return
        if bool(decision.get("passed")):
            return
        completion_state = str(decision.get("state") or "verifying").lower()
        if "review" in completion_state:
            self._emit("work.order.reviewing", event, state="REVIEWING", review_state=decision.get("review_state"))
        elif completion_state in {"blocked", "failed", "cancelled"}:
            self._emit("work.order.blocked", event, state=completion_state.upper())
        else:
            self._emit("work.order.verifying", event, state="VERIFYING")

    def _cancel_uncertain(self, event: Mapping[str, Any]) -> None:
        self._emit("work.order.recovery_required", event, state="UNCERTAIN")

    def _completion_observed(self, event: Mapping[str, Any]) -> None:
        evidence_id = event.get("evidence_id")
        claim_id = event.get("claim_id")
        if evidence_id:
            self._emit("work.evidence.recorded", event)
        if claim_id:
            self._emit("work.claim.proposed", event)
            claim_state = str(event.get("claim_state") or "").lower()
            if bool(event.get("evidence_gate_passed")) or claim_state in {"supported", "verified"}:
                self._emit("work.claim.verified", event, claim_state="verified")
            elif claim_state in {"rejected", "disputed"} or not bool(event.get("evidence_gate_passed")):
                self._emit("work.claim.rejected", event, claim_state=claim_state or "rejected")

    def _replan_started(self, event: Mapping[str, Any]) -> None:
        self._emit("work.replan.started", event)

    def _replan_completed(self, event: Mapping[str, Any]) -> None:
        self._emit("work.replan.completed", event)

    def close(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubscribers.clear()
