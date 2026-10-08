from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from typing import Any, Iterable, Mapping

from .models import GoalSpec, ReadinessStatus, WorkPlan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PlanReview:
    id: str
    plan_id: str
    plan_version: int
    status: ReadinessStatus
    score: float
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checks: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "status": self.status.value,
            "score": self.score,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "checks": dict(self.checks),
            "created_at": self.created_at,
        }


class PlanReviewer:
    """Deterministic readiness review. Model output has no say in this decision."""

    @staticmethod
    def review(
        plan: WorkPlan,
        goal: GoalSpec,
        *,
        available_tools: Iterable[str] | None = None,
    ) -> PlanReview:
        blockers: list[str] = []
        warnings: list[str] = []
        tools = None if available_tools is None else set(str(item) for item in available_tools)

        if plan.goal_id != goal.id:
            blockers.append("plan goal_id does not match the reviewed goal")
        if not plan.work_orders:
            blockers.append("plan has no work orders")

        parent_caps = set(str(item) for item in goal.resource_scope.metadata.get("allowed_capabilities", []))
        parent_destinations = set(goal.resource_scope.allowed_destinations)
        parent_connectors = set(goal.resource_scope.allowed_connectors)
        parent_repositories = set(goal.resource_scope.allowed_repositories)
        parent_paths = set(goal.resource_scope.allowed_paths)

        order_success_criteria = 0
        verification_orders = 0
        requested_tools: list[str] = []

        for order in plan.work_orders:
            order_caps = set(order.allowed_capabilities)
            if parent_caps and not order_caps.issubset(parent_caps):
                blockers.append(f"{order.id} expands allowed capabilities beyond the goal")
            for label, child, parent in (
                ("destinations", set(order.resource_scope.allowed_destinations), parent_destinations),
                ("connectors", set(order.resource_scope.allowed_connectors), parent_connectors),
                ("repositories", set(order.resource_scope.allowed_repositories), parent_repositories),
                ("paths", set(order.resource_scope.allowed_paths), parent_paths),
            ):
                if child and (not parent or not child.issubset(parent)):
                    blockers.append(f"{order.id} expands allowed {label} beyond the goal")

            requested_tool = str(order.resource_scope.metadata.get("requested_tool") or "").strip()
            if requested_tool:
                requested_tools.append(requested_tool)
                if tools is not None and requested_tool not in tools:
                    blockers.append(f"{order.id} requests unavailable tool {requested_tool}")
                if not order.evidence_contract.requirements:
                    blockers.append(f"{order.id} requests a tool but has no evidence requirement")

            if order.evidence_contract.requirements:
                verification_orders += 1
                for requirement in order.evidence_contract.requirements:
                    if requirement.min_provenance not in {
                        "model_only", "context", "observed", "tool_verified",
                        "externally_verified", "replayable",
                    }:
                        blockers.append(f"{order.id} has an invalid evidence provenance requirement")

            if order.success_criteria:
                order_success_criteria += 1
            else:
                warnings.append(f"{order.id} has no explicit success criteria")
            if not order.expected_output.strip():
                warnings.append(f"{order.id} has no expected output")

        if goal.success_criteria and order_success_criteria == 0:
            warnings.append("goal success criteria are not traced to any work order")
        if requested_tools and verification_orders == 0:
            blockers.append("tool-backed work has no verification contract")

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        status = (
            ReadinessStatus.HOLD
            if blockers
            else ReadinessStatus.DEGRADED
            if warnings
            else ReadinessStatus.READY
        )
        score = max(0.0, 100.0 - 25.0 * len(blockers) - 5.0 * len(warnings))
        return PlanReview(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            plan_version=plan.version,
            status=status,
            score=score,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            checks={
                "work_orders": len(plan.work_orders),
                "requested_tools": requested_tools,
                "verification_orders": verification_orders,
                "goal_success_criteria": len(goal.success_criteria),
                "deterministic": True,
            },
        )


class PlanReviewStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record(self, review: PlanReview) -> PlanReview:
        payload = json.dumps(review.to_dict(), sort_keys=True, separators=(",", ":"))
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO plan_reviews(id,plan_id,plan_version,status,score,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    review.id,
                    review.plan_id,
                    review.plan_version,
                    review.status.value,
                    review.score,
                    payload,
                    review.created_at,
                ),
            )
        return review

    def latest(self, plan_id: str) -> PlanReview | None:
        row = self.connection.execute(
            """
            SELECT payload_json FROM plan_reviews
            WHERE plan_id=?
            ORDER BY created_at DESC,id DESC
            LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        return PlanReview(
            id=str(data["id"]),
            plan_id=str(data["plan_id"]),
            plan_version=int(data["plan_version"]),
            status=ReadinessStatus(str(data["status"])),
            score=float(data["score"]),
            blockers=tuple(data.get("blockers", [])),
            warnings=tuple(data.get("warnings", [])),
            checks=dict(data.get("checks", {})),
            created_at=str(data["created_at"]),
        )
