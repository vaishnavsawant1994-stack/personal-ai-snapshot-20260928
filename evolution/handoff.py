from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from future_intelligence.work_orchestration import (
    DurableWorkStore,
    EvidenceContract,
    EvidenceRequirement,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)

from .models import CandidateStatus, EvolutionCandidate
from .protected_scope import evaluate_protected_scope
from .store import EvolutionStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvolutionHandoff:
    id: str
    candidate_id: str
    work_order_id: str
    goal_id: str
    plan_id: str
    base_body_revision: str
    approved_decision_id: str
    handoff_hash: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "work_order_id": self.work_order_id,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "base_body_revision": self.base_body_revision,
            "approved_decision_id": self.approved_decision_id,
            "handoff_hash": self.handoff_hash,
            "created_at": self.created_at,
        }


class EvolutionHandoffService:
    """Owner-approved Candidate -> immutable canonical Work transaction.

    This service has no repository, merge, deployment, or Body-activation API.
    It only materializes approved implementation work.
    """

    def __init__(self, evolution_store: EvolutionStore, work_store: DurableWorkStore) -> None:
        if evolution_store.connection is not work_store.connection:
            raise ValueError(
                "atomic evolution handoff requires EvolutionStore and DurableWorkStore to share one SQLite connection"
            )
        self.evolution_store = evolution_store
        self.work_store = work_store
        self.connection = evolution_store.connection

    def get_handoff(self, candidate_id: str) -> EvolutionHandoff | None:
        row = self.connection.execute(
            "SELECT * FROM evolution_handoffs WHERE candidate_id = ?",
            (str(candidate_id),),
        ).fetchone()
        if row is None:
            return None
        return EvolutionHandoff(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            work_order_id=str(row["work_order_id"]),
            goal_id=str(row["goal_id"]),
            plan_id=str(row["plan_id"]),
            base_body_revision=str(row["base_body_revision"]),
            approved_decision_id=str(row["approved_decision_id"]),
            handoff_hash=str(row["handoff_hash"]),
            created_at=str(row["created_at"]),
        )

    def approve_and_handoff(
        self,
        candidate_id: str,
        *,
        actor_id: str,
        reason: str,
        base_body_revision: str,
    ) -> EvolutionHandoff:
        actor = str(actor_id or "").strip()
        reason = str(reason or "").strip()
        base_revision = str(base_body_revision or "").strip()
        if not actor or not reason or not base_revision:
            raise ValueError("actor_id, reason, and base_body_revision are required")

        existing = self.get_handoff(candidate_id)
        if existing is not None:
            return existing

        now = _now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT payload_json FROM evolution_candidates WHERE id = ?",
                (str(candidate_id),),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            candidate = EvolutionCandidate.from_dict(json.loads(row[0]))
            if candidate.status is not CandidateStatus.RECOMMENDED:
                raise ValueError("only recommended candidates may be owner-approved for handoff")

            protected = evaluate_protected_scope(candidate.affected_scope, candidate.proposed_change)
            if protected.restricted:
                raise PermissionError("protected-scope candidate cannot enter ordinary handoff")

            decision_id = f"edec_{uuid4().hex}"
            self.connection.execute(
                """
                INSERT INTO evolution_decisions(
                    id, candidate_id, decision, actor_id, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    candidate.id,
                    CandidateStatus.APPROVED.value,
                    actor,
                    reason,
                    now,
                ),
            )

            project_id = candidate.metadata.get("project_id")
            goal_id = f"evo-goal:{candidate.id}"
            plan_id = f"evo-plan:{candidate.id}"
            work_order_id = f"evo-work:{candidate.id}"
            allowed_repositories = tuple(
                str(item)
                for item in candidate.metadata.get("allowed_repositories", ())
                if str(item).strip()
            )
            goal = GoalSpec(
                id=goal_id,
                project_id=None if project_id is None else str(project_id),
                title=f"Implement approved evolution: {candidate.title}",
                objective=candidate.proposed_change,
                desired_outcome=candidate.expected_benefit,
                deliverables=(candidate.proposed_change,),
                success_criteria=(candidate.expected_benefit,),
                constraints=(
                    "implementation authority does not include merge, deploy, or Body activation",
                    "protected authority boundaries must remain unchanged",
                ),
                resource_scope=ResourceScope(
                    allowed_repositories=allowed_repositories,
                    allowed_paths=tuple(candidate.affected_scope),
                    metadata={
                        "evolution_candidate_id": candidate.id,
                        "base_body_revision": base_revision,
                    },
                ),
                approval_policy={
                    "source": "evolution_handoff",
                    "approved_decision_id": decision_id,
                    "merge_requires_separate_owner_approval": True,
                    "deploy_requires_separate_owner_approval": True,
                    "body_activation_requires_separate_owner_approval": True,
                },
                created_from="evolution_owner_approval",
                created_at=now,
                updated_at=now,
            )
            order = WorkOrder(
                id=work_order_id,
                plan_id=plan_id,
                project_id=goal.project_id,
                title=candidate.title,
                objective=candidate.proposed_change,
                worker_type="software_engineering",
                status=WorkOrderStatus.QUEUED,
                resource_scope=goal.resource_scope,
                expected_output=candidate.expected_benefit,
                success_criteria=(candidate.expected_benefit,),
                evidence_contract=EvidenceContract(
                    requirements=(
                        EvidenceRequirement(
                            kind="implementation_verification",
                            required=True,
                            min_count=1,
                        ),
                    ),
                    require_review=True,
                    require_retest=True,
                ),
                verification_strategy={
                    "test_plan": list(candidate.test_plan),
                    "supporting_evidence_ids": list(candidate.evidence_ids),
                    "base_body_revision": base_revision,
                },
                approval_policy=goal.approval_policy,
                retry_policy={
                    "max_attempts": 3,
                    "unknown_effect": "recovery_required",
                    "permission_policy_validation": "explicit_retry_only",
                },
                created_at=now,
                updated_at=now,
            )
            plan = WorkPlan(
                id=plan_id,
                goal_id=goal_id,
                project_id=goal.project_id,
                version=1,
                summary=f"Owner-approved implementation work for evolution candidate {candidate.id}",
                work_orders=(order,),
                evidence_contract=order.evidence_contract,
                critic={
                    "source": "evolution_handoff",
                    "candidate_id": candidate.id,
                    "approved_decision_id": decision_id,
                    "base_body_revision": base_revision,
                    "owner_adoption_separate": True,
                },
                readiness=ReadinessStatus.READY,
                status=WorkPlanStatus.READY,
                created_at=now,
            )

            # Direct SQL mirrors WorkStore persistence so all records participate
            # in this same transaction instead of nested context-manager commits.
            self.connection.execute(
                """
                INSERT INTO work_goals(
                    id, project_id, source_p10_goal_id, payload_json, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (goal.id, goal.project_id, _json(goal.to_dict()), goal.created_at, goal.updated_at),
            )
            self.connection.execute(
                """
                INSERT INTO work_plans(
                    id, goal_id, project_id, source_p10_plan_id,
                    version, status, payload_json, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.goal_id,
                    plan.project_id,
                    plan.version,
                    plan.status.value,
                    _json(plan.to_dict()),
                    plan.created_at,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO work_orders(
                    id, plan_id, project_id, project_task_id, worker_type,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    order.id,
                    order.plan_id,
                    order.project_id,
                    order.worker_type,
                    order.status.value,
                    _json(order.to_dict()),
                    order.created_at,
                    order.updated_at,
                ),
            )

            handoff_id = f"ehand_{uuid4().hex}"
            handoff_hash = _hash(
                {
                    "candidate_id": candidate.id,
                    "decision_id": decision_id,
                    "work_order_id": order.id,
                    "base_body_revision": base_revision,
                    "candidate_hash": candidate.candidate_hash,
                }
            )
            handoff = EvolutionHandoff(
                id=handoff_id,
                candidate_id=candidate.id,
                work_order_id=order.id,
                goal_id=goal.id,
                plan_id=plan.id,
                base_body_revision=base_revision,
                approved_decision_id=decision_id,
                handoff_hash=handoff_hash,
                created_at=now,
            )
            self.connection.execute(
                """
                INSERT INTO evolution_handoffs(
                    id, candidate_id, work_order_id, goal_id, plan_id,
                    base_body_revision, approved_decision_id, handoff_hash,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff.id,
                    handoff.candidate_id,
                    handoff.work_order_id,
                    handoff.goal_id,
                    handoff.plan_id,
                    handoff.base_body_revision,
                    handoff.approved_decision_id,
                    handoff.handoff_hash,
                    _json(handoff.to_dict()),
                    handoff.created_at,
                ),
            )

            handed_off_candidate = EvolutionCandidate(
                id=candidate.id,
                status=CandidateStatus.HANDED_OFF,
                title=candidate.title,
                rationale=candidate.rationale,
                proposed_change=candidate.proposed_change,
                expected_benefit=candidate.expected_benefit,
                risk_level=candidate.risk_level,
                affected_scope=candidate.affected_scope,
                test_plan=candidate.test_plan,
                evidence_ids=candidate.evidence_ids,
                candidate_hash=candidate.candidate_hash,
                metadata=candidate.metadata,
                created_at=candidate.created_at,
                updated_at=now,
            )
            self.connection.execute(
                """
                UPDATE evolution_candidates
                SET status = ?, payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    CandidateStatus.HANDED_OFF.value,
                    _json(handed_off_candidate.to_dict()),
                    now,
                    candidate.id,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO work_events(
                    id, work_order_id, attempt_id, event_type, payload_json, created_at
                ) VALUES (?, ?, NULL, 'evolution.handoff.created', ?, ?)
                """,
                (
                    f"wev_{uuid4().hex}",
                    order.id,
                    _json(
                        {
                            "candidate_id": candidate.id,
                            "handoff_id": handoff.id,
                            "approved_decision_id": decision_id,
                            "base_body_revision": base_revision,
                        }
                    ),
                    now,
                ),
            )
            self.connection.commit()
            return handoff
        except Exception:
            self.connection.rollback()
            raise
