from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from future_intelligence.work_orchestration.completion_propagation import canonical_ready_ids


@dataclass(frozen=True)
class WorkConsistencyIssue:
    code: str
    message: str
    project_id: str | None = None
    plan_id: str | None = None
    work_order_id: str | None = None
    attention_id: str | None = None
    event_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "project_id": self.project_id,
            "plan_id": self.plan_id,
            "work_order_id": self.work_order_id,
            "attention_id": self.attention_id,
            "event_id": self.event_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class WorkConsistencyReport:
    passed: bool
    issues: tuple[WorkConsistencyIssue, ...]
    checks: int
    authority: str = "read_only_qualification_gate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [item.to_dict() for item in self.issues],
            "checks": self.checks,
            "authority": self.authority,
        }


class WorkConsistencyError(AssertionError):
    def __init__(self, report: WorkConsistencyReport) -> None:
        self.report = report
        codes = ", ".join(item.code for item in report.issues) or "unknown"
        super().__init__(f"canonical Work consistency failed: {codes}")


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _count(mapping: Mapping[str, Any] | None, key: str) -> int:
    try:
        return max(0, int((mapping or {}).get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _work_order_map(project_snapshots: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in project_snapshots:
        project_id = str(snapshot.get("project_id") or "")
        work_plan = snapshot.get("work_plan") or {}
        for raw in work_plan.get("work_orders") or []:
            order = dict(raw)
            metadata = ((order.get("resource_scope") or {}).get("metadata") or {})
            task_id = str(metadata.get("p10_task_id") or "")
            if task_id:
                rows[(str(snapshot.get("p10_plan", {}).get("id") or snapshot.get("plan_id") or ""), task_id)] = {
                    **order,
                    "project_id": project_id,
                }
    return rows


class WorkConsistencyGate:
    """Read-only invariant checker spanning canonical Work product projections.

    The gate owns no runtime or product authority. It compares already-authoritative
    Completion, Attention, Event, Notification-source and Living projections and
    fails qualification when those surfaces contradict one another.
    """

    @classmethod
    def evaluate(
        cls,
        *,
        global_work: Mapping[str, Any] | None = None,
        attention: Mapping[str, Any] | None = None,
        living: Mapping[str, Any] | None = None,
        project_snapshots: Iterable[Mapping[str, Any]] = (),
        canonical_events: Iterable[Mapping[str, Any]] = (),
        claim_states: Mapping[str, str] | None = None,
        approval_bindings: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> WorkConsistencyReport:
        issues: list[WorkConsistencyIssue] = []
        checks = 0
        global_work = dict(global_work or {})
        attention = dict(attention or {})
        living = dict(living or attention.get("living") or {})
        snapshots = [dict(item) for item in project_snapshots]
        events = [dict(item) for item in canonical_events]
        claim_states = {str(k): str(v).lower() for k, v in dict(claim_states or {}).items()}
        approval_bindings = {str(k): dict(v) for k, v in dict(approval_bindings or {}).items()}

        attention_items = list(attention.get("items") or [])
        attention_counts = attention.get("counts") or {}
        attention_total = _count(attention_counts, "total")
        checks += 1
        if attention_total != len(attention_items):
            issues.append(
                WorkConsistencyIssue(
                    "attention_count_mismatch",
                    "Attention total does not equal the canonical attention item count.",
                    details={"count": attention_total, "items": len(attention_items)},
                )
            )

        if living:
            checks += 2
            living_count = _count(living, "attention_count")
            if living_count != attention_total:
                issues.append(
                    WorkConsistencyIssue(
                        "living_attention_mismatch",
                        "Living Vishnu attention count disagrees with canonical Attention.",
                        details={"living": living_count, "attention": attention_total},
                    )
                )
            if bool(living.get("needs_attention")) != bool(attention_total):
                issues.append(
                    WorkConsistencyIssue(
                        "living_attention_boolean_mismatch",
                        "Living Vishnu needs-attention state disagrees with canonical Attention.",
                    )
                )

        recovery_attention = any(
            str(item.get("kind") or "") in {"recovery_required", "uncertain_effect"}
            for item in attention_items
        )
        recovery_work = any(
            _upper(item.get("status")) in {"RECOVERY_REQUIRED", "RECOVERING", "UNCERTAIN"}
            for item in global_work.get("work_orders") or []
        )
        checks += 1
        if (recovery_attention or recovery_work) and _upper(living.get("state")) in {"COMPLETED", "CELEBRATING"}:
            issues.append(
                WorkConsistencyIssue(
                    "living_completed_during_recovery",
                    "Living Vishnu cannot present completion while recovery/uncertainty exists.",
                )
            )

        work_orders = list(global_work.get("work_orders") or [])
        global_counts = global_work.get("counts") or {}
        checks += 1
        computed_completed = sum(_upper(item.get("status")) == "COMPLETED" for item in work_orders)
        if "completed" in global_counts and _count(global_counts, "completed") != computed_completed:
            issues.append(
                WorkConsistencyIssue(
                    "global_completed_count_mismatch",
                    "Global completed count disagrees with canonical WorkOrder rows.",
                    details={"count": _count(global_counts, "completed"), "rows": computed_completed},
                )
            )

        order_map = _work_order_map(snapshots)
        for snapshot in snapshots:
            project_id = str(snapshot.get("project_id") or "") or None
            p10_plan = snapshot.get("p10_plan") or {}
            work_plan = snapshot.get("work_plan") or {}
            live = snapshot.get("live_work") or {}
            plan_id = str(p10_plan.get("id") or snapshot.get("plan_id") or "") or None
            completion = work_plan.get("completion") or live.get("completion") or {}
            live_state = _upper(live.get("state"))

            checks += 1
            if live_state == "COMPLETED" and not bool(completion.get("complete")):
                issues.append(
                    WorkConsistencyIssue(
                        "live_completed_without_completion_judge",
                        "Live Work cannot be COMPLETED before the Completion Judge passes.",
                        project_id=project_id,
                        plan_id=plan_id,
                    )
                )

            completion_state = str(completion.get("completion_state") or completion.get("state") or "").lower()
            checks += 1
            if completion_state in {"verifying", "reviewing", "blocked", "in_progress"} and live_state == "COMPLETED":
                issues.append(
                    WorkConsistencyIssue(
                        "completion_state_surface_contradiction",
                        "Live Work says completed while canonical completion is not complete.",
                        project_id=project_id,
                        plan_id=plan_id,
                        details={"completion_state": completion_state, "live_state": live_state},
                    )
                )

            if p10_plan and work_plan:
                checks += 1
                expected_ready = canonical_ready_ids(p10_plan, work_plan)
                actual_ready = {str(item) for item in live.get("ready_task_ids") or []}
                if actual_ready != expected_ready:
                    issues.append(
                        WorkConsistencyIssue(
                            "dependency_readiness_mismatch",
                            "Live Work readiness disagrees with canonical dependency completion proof.",
                            project_id=project_id,
                            plan_id=plan_id,
                            details={"expected": sorted(expected_ready), "actual": sorted(actual_ready)},
                        )
                    )

            for raw in work_plan.get("work_orders") or []:
                order = dict(raw)
                decision = order.get("completion") or {}
                checks += 1
                if _upper(order.get("status")) == "COMPLETED" and not bool(decision.get("passed")):
                    issues.append(
                        WorkConsistencyIssue(
                            "work_order_completed_without_proof",
                            "A WorkOrder is marked completed without a passing completion decision.",
                            project_id=project_id,
                            plan_id=plan_id,
                            work_order_id=str(order.get("id") or "") or None,
                        )
                    )

        for item in attention_items:
            if str(item.get("kind") or "") != "approval_required":
                continue
            approval_id = str(item.get("approval_id") or "")
            expected = approval_bindings.get(approval_id)
            if not expected:
                continue
            checks += 1
            if (
                str(item.get("project_id") or "") != str(expected.get("project_id") or "")
                or str(item.get("work_order_id") or "") != str(expected.get("work_order_id") or "")
            ):
                issues.append(
                    WorkConsistencyIssue(
                        "approval_cross_project_misbinding",
                        "Approval attention is bound to the wrong Project or WorkOrder.",
                        project_id=str(item.get("project_id") or "") or None,
                        work_order_id=str(item.get("work_order_id") or "") or None,
                        attention_id=str(item.get("id") or "") or None,
                        details={"expected": expected, "approval_id": approval_id},
                    )
                )

        for event in events:
            event_name = str(event.get("event_name") or event.get("type") or "")
            if event_name != "work.order.completed":
                continue
            plan_id = str(event.get("plan_id") or "")
            task_id = str(event.get("task_id") or "")
            order = order_map.get((plan_id, task_id))
            checks += 1
            if order is not None and not bool((order.get("completion") or {}).get("passed")):
                issues.append(
                    WorkConsistencyIssue(
                        "completion_event_without_proof",
                        "work.order.completed was emitted before the Completion Judge passed.",
                        project_id=str(order.get("project_id") or "") or None,
                        plan_id=plan_id or None,
                        work_order_id=str(order.get("id") or "") or None,
                        event_id=str(event.get("event_id") or "") or None,
                    )
                )
            work_order_id = str(event.get("work_order_id") or (order or {}).get("id") or "")
            claim_state = claim_states.get(work_order_id)
            if claim_state in {"rejected", "disputed"}:
                issues.append(
                    WorkConsistencyIssue(
                        "completion_event_with_rejected_claim",
                        "Completion event exists while the current required claim is rejected/disputed.",
                        plan_id=plan_id or None,
                        work_order_id=work_order_id or None,
                        event_id=str(event.get("event_id") or "") or None,
                        details={"claim_state": claim_state},
                    )
                )

        return WorkConsistencyReport(not issues, tuple(issues), checks)

    @classmethod
    def assert_consistent(cls, **kwargs: Any) -> WorkConsistencyReport:
        report = cls.evaluate(**kwargs)
        if not report.passed:
            raise WorkConsistencyError(report)
        return report
