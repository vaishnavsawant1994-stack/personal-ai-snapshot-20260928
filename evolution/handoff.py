from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from future_intelligence.work_orchestration.models import (
    EvidenceContract,
    EvidenceRequirement,
    ExecutionBudget,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)

from .models import CandidateStatus, EvolutionDecision
from .store import EvolutionStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvolutionHandoff:
    id: str
    candidate_id: str
    owner_decision_id: str
    base_body_revision: str
    candidate_hash: str
    goal_id: str
    plan_id: str
    work_order_id: str
    created_at: str

    @classmethod
    def from_row(cls, row) -> "EvolutionHandoff":
        return cls(**{key: row[key] for key in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


class EvolutionHandoffService:
    """Owner decision -> immutable handoff + canonical Work.

    The owner decision is persisted first in the evolution database. Work and
    the handoff record are then committed together in one Work-database
    transaction. A failure therefore cannot create unapproved executable work.
    """

    def __init__(
        self,
        *,
        evolution_store: EvolutionStore,
        work_store,
        software_repository: str = "vaishnavsawant1994-stack/vishnu",
    ) -> None:
        self.evolution_store = evolution_store
        self.work_store = work_store
        self.software_repository = str(software_repository)
        self._migrate()

    def _migrate(self) -> None:
        with self.work_store.connection:
            self.work_store.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolution_handoffs(
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    owner_decision_id TEXT NOT NULL UNIQUE,
                    base_body_revision TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    goal_id TEXT NOT NULL UNIQUE,
                    plan_id TEXT NOT NULL UNIQUE,
                    work_order_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolution_handoffs_created
                    ON evolution_handoffs(created_at, id);
                """
            )

    def get(self, candidate_id: str) -> EvolutionHandoff | None:
        row = self.work_store.connection.execute(
            "SELECT * FROM evolution_handoffs WHERE candidate_id = ?",
            (str(candidate_id),),
        ).fetchone()
        return EvolutionHandoff.from_row(row) if row else None

    def list(self) -> list[EvolutionHandoff]:
        rows = self.work_store.connection.execute(
            "SELECT * FROM evolution_handoffs ORDER BY created_at, id"
        ).fetchall()
        return [EvolutionHandoff.from_row(row) for row in rows]

    def reject(self, candidate_id: str, *, owner_id: str, reason: str) -> None:
        if str(owner_id) != "owner":
            raise PermissionError("only the canonical owner may reject an evolution candidate")
        candidate = self.evolution_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if self.get(candidate_id) is not None or candidate.status in {
            CandidateStatus.HANDED_OFF,
            CandidateStatus.ADOPTION_APPROVED,
            CandidateStatus.ADOPTED,
        }:
            raise ValueError("handed-off candidate cannot be retroactively rejected")
        decision_id = f"owner-reject-{_digest(candidate.id, str(reason))[:24]}"
        self.evolution_store.record_decision(
            candidate.id,
            EvolutionDecision.REJECT,
            actor_id="owner",
            reason=reason,
            payload={"owner_decision": True},
            decision_id=decision_id,
        )
        self.evolution_store.update_candidate(candidate.id, status=CandidateStatus.REJECTED)

    def approve(
        self,
        candidate_id: str,
        *,
        owner_id: str,
        reason: str,
        base_body_revision: str,
    ) -> EvolutionHandoff:
        if str(owner_id) != "owner":
            raise PermissionError("only the canonical owner may approve an evolution candidate")
        existing = self.get(candidate_id)
        if existing is not None:
            # The immutable handoff is already authoritative. Never replay an
            # older implementation-approval request into a later lifecycle
            # state such as ADOPTION_APPROVED or ADOPTED.
            return existing

        candidate = self.evolution_store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate.status not in {CandidateStatus.RECOMMENDED, CandidateStatus.DEFERRED}:
            raise ValueError(f"candidate is not eligible for owner handoff: {candidate.status.value}")
        revision = str(base_body_revision or "").strip()
        explanation = str(reason or "").strip()
        if not revision or not explanation:
            raise ValueError("reason and base_body_revision are required")

        decision_id = f"owner-approve-{_digest(candidate.id, revision)[:24]}"
        self.evolution_store.record_decision(
            candidate.id,
            EvolutionDecision.APPROVE,
            actor_id="owner",
            reason=explanation,
            payload={
                "owner_decision": True,
                "base_body_revision": revision,
                "candidate_hash": candidate.candidate_hash,
            },
            decision_id=decision_id,
        )

        suffix = candidate.candidate_hash[:20]
        handoff = EvolutionHandoff(
            id=f"handoff-evo-{suffix}",
            candidate_id=candidate.id,
            owner_decision_id=decision_id,
            base_body_revision=revision,
            candidate_hash=candidate.candidate_hash,
            goal_id=f"goal-evo-{suffix}",
            plan_id=f"plan-evo-{suffix}",
            work_order_id=f"work-evo-{suffix}",
            created_at=_now(),
        )
        goal = GoalSpec(
            id=handoff.goal_id,
            title=candidate.title,
            objective=candidate.proposed_change,
            desired_outcome=candidate.expected_benefit,
            deliverables=(candidate.proposed_change,),
            success_criteria=tuple(candidate.test_plan),
            constraints=(
                "Do not change owner authority or bypass existing permissions/approvals.",
                "Do not merge, deploy, or activate a software-body revision without a separate authorized adoption step.",
            ),
            resource_scope=ResourceScope(
                allowed_repositories=(self.software_repository,),
                metadata={
                    "evolution_candidate_id": candidate.id,
                    "owner_decision_id": decision_id,
                    "base_body_revision": revision,
                },
            ),
            budget=ExecutionBudget(max_attempts=1),
            approval_policy={
                "implementation_handoff": "owner_approved",
                "owner_decision_id": decision_id,
                "external_actions": "existing_governance_required",
            },
            created_from="evolution_owner_handoff",
            created_at=handoff.created_at,
            updated_at=handoff.created_at,
        )
        order = WorkOrder(
            id=handoff.work_order_id,
            plan_id=handoff.plan_id,
            title=candidate.title,
            objective=candidate.proposed_change,
            worker_type="software_engineering",
            status=WorkOrderStatus.QUEUED,
            allowed_capabilities=(),
            resource_scope=goal.resource_scope,
            expected_output=candidate.expected_benefit,
            success_criteria=tuple(candidate.test_plan),
            evidence_contract=EvidenceContract(
                requirements=(
                    EvidenceRequirement(
                        kind="evolution_implementation_verification",
                        required=True,
                        min_count=1,
                        min_provenance="tool_verified",
                    ),
                ),
                require_review=True,
                require_retest=True,
            ),
            verification_strategy={
                "test_plan": list(candidate.test_plan),
                "owner_adoption_required": True,
            },
            approval_policy={
                "owner_decision_id": decision_id,
                "merge": "separate_owner_adoption_required",
                "deploy": "separate_owner_adoption_required",
            },
            retry_policy={"max_retries": 0, "unknown_effect": "recovery_required"},
            created_at=handoff.created_at,
            updated_at=handoff.created_at,
        )
        plan = WorkPlan(
            id=handoff.plan_id,
            goal_id=handoff.goal_id,
            version=1,
            summary=f"Owner-approved evolution implementation: {candidate.title}",
            work_orders=(order,),
            evidence_contract=order.evidence_contract,
            critic={
                "evolution_candidate_id": candidate.id,
                "candidate_hash": candidate.candidate_hash,
                "owner_decision_id": decision_id,
                "base_body_revision": revision,
                "adoption_authority": "owner_separate_step",
            },
            readiness=ReadinessStatus.READY,
            status=WorkPlanStatus.READY,
            created_at=handoff.created_at,
        )
        self._commit_work_handoff(handoff, goal, plan, order)
        self.evolution_store.update_candidate(candidate.id, status=CandidateStatus.HANDED_OFF)
        return handoff

    def _commit_work_handoff(
        self,
        handoff: EvolutionHandoff,
        goal: GoalSpec,
        plan: WorkPlan,
        order: WorkOrder,
    ) -> None:
        con = self.work_store.connection
        try:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM evolution_handoffs WHERE candidate_id = ?",
                (handoff.candidate_id,),
            ).fetchone()
            if existing is not None:
                con.commit()
                return

            work_row = con.execute("SELECT payload_json FROM work_orders WHERE id = ?", (order.id,)).fetchone()
            if work_row is not None:
                persisted = json.loads(work_row[0])
                metadata = ((persisted.get("resource_scope") or {}).get("metadata") or {})
                if str(metadata.get("evolution_candidate_id") or "") != handoff.candidate_id:
                    raise ValueError("deterministic WorkOrder id collides with unrelated work")

            con.execute(
                """
                INSERT OR IGNORE INTO work_goals(
                    id, project_id, source_p10_goal_id, payload_json, created_at, updated_at
                ) VALUES (?, NULL, NULL, ?, ?, ?)
                """,
                (goal.id, _json(goal.to_dict()), goal.created_at, goal.updated_at),
            )
            con.execute(
                """
                INSERT OR IGNORE INTO work_plans(
                    id, goal_id, project_id, source_p10_plan_id,
                    version, status, payload_json, created_at
                ) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?)
                """,
                (plan.id, plan.goal_id, plan.version, plan.status.value, _json(plan.to_dict()), plan.created_at),
            )
            con.execute(
                """
                INSERT OR IGNORE INTO work_orders(
                    id, plan_id, project_id, project_task_id, worker_type,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    order.plan_id,
                    order.worker_type,
                    order.status.value,
                    _json(order.to_dict()),
                    order.created_at,
                    order.updated_at,
                ),
            )
            con.execute(
                """
                INSERT INTO evolution_handoffs(
                    id, candidate_id, owner_decision_id, base_body_revision,
                    candidate_hash, goal_id, plan_id, work_order_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff.id,
                    handoff.candidate_id,
                    handoff.owner_decision_id,
                    handoff.base_body_revision,
                    handoff.candidate_hash,
                    handoff.goal_id,
                    handoff.plan_id,
                    handoff.work_order_id,
                    handoff.created_at,
                ),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
