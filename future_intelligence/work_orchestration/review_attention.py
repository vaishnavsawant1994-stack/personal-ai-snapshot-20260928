from __future__ import annotations

import json
from typing import Any

from evidence.models import Claim, ClaimState, VerificationState
from security.projection_redaction import sanitize_sensitive_text

from .attention import AttentionItem, _KIND_PRIORITY, _SEVERITY_PRIORITY, _stable_id
from .recovery_attention import RecoveryAwareWorkAttentionService
from .reviewer import PlanReviewStore


class ReviewAwareWorkAttentionService(RecoveryAwareWorkAttentionService):
    """Read-only projection of evidence, claim, and deterministic review attention.

    EvidenceStore/ClaimGate and the deterministic reviewer remain authoritative.
    This layer never changes evidence, claims, reviews, or Work completion state.
    """

    def _bridge(self):
        autonomy = self.work_service._autonomy()
        return getattr(autonomy, "_work_bridge", None)

    @staticmethod
    def _safe_reason(value: Any) -> str:
        return sanitize_sensitive_text(str(value or ""))[:500]

    def _work_map(self) -> dict[str, dict[str, Any]]:
        work = self.work_service.summary(work_order_limit=500)
        rows = self._enrich_work_orders(work)
        return {
            str(row.get("work_order_id")): row
            for row in rows
            if row.get("work_order_id")
        }

    def _claim_rows(self, bridge) -> list[Claim]:
        if bridge is None:
            return []
        with bridge.lock:
            rows = bridge.evidence.connection.execute(
                "SELECT payload_json FROM claims ORDER BY updated_at,id"
            ).fetchall()
        result: list[Claim] = []
        for row in rows:
            try:
                result.append(Claim.from_dict(json.loads(row[0])))
            except Exception:
                continue
        return result

    def _claim_items(self, bridge, work_map: dict[str, dict[str, Any]]) -> list[AttentionItem]:
        result: list[AttentionItem] = []
        for claim in self._claim_rows(bridge):
            work = work_map.get(str(claim.work_order_id or ""), {})
            state = claim.state
            work_status = str(work.get("status") or "").upper()
            terminal_claim_gap = state in {ClaimState.PROPOSED, ClaimState.SUPPORTED} and work_status == "COMPLETED"
            if state not in {ClaimState.REJECTED, ClaimState.DISPUTED} and not terminal_claim_gap:
                continue
            severity = "urgent" if state in {ClaimState.REJECTED, ClaimState.DISPUTED} else "review"
            if state is ClaimState.REJECTED:
                reason = "A completion claim was rejected by the canonical Claim Gate."
            elif state is ClaimState.DISPUTED:
                reason = "A completion claim is disputed and cannot support completion."
            else:
                reason = "The WorkOrder is terminal but its completion claim is not verified."
            result.append(
                AttentionItem(
                    id=_stable_id("claim_unsupported", claim.id, claim.work_order_id),
                    kind="claim_unsupported",
                    severity=severity,
                    status=state.value,
                    title="Completion claim is not verified",
                    summary=self._safe_reason(work.get("title") or "WorkOrder requires evidence review"),
                    reason=reason,
                    authority="claim_gate",
                    action_type="inspect_evidence",
                    deep_link=self._work_link(work, section="work-plan"),
                    project_id=work.get("project_id") or claim.project_id,
                    project_name=work.get("project_name"),
                    goal_id=work.get("goal_id"),
                    plan_id=work.get("plan_id"),
                    plan_version=work.get("plan_version"),
                    work_order_id=claim.work_order_id,
                    work_order_title=work.get("title"),
                    worker_type=work.get("worker_type"),
                    execution_id=work.get("execution_id"),
                    claim_id=claim.id,
                    created_at=claim.created_at,
                    updated_at=claim.updated_at,
                    requires_owner_action=True,
                )
            )
        return result

    def _evidence_items(self, bridge, work_map: dict[str, dict[str, Any]]) -> list[AttentionItem]:
        if bridge is None:
            return []
        evidence = []
        for state in (VerificationState.REJECTED, VerificationState.DISPUTED):
            try:
                evidence.extend(bridge.evidence.list_evidence(verification_state=state))
            except Exception:
                continue
        result: list[AttentionItem] = []
        for item in evidence:
            work = work_map.get(str(item.work_order_id or ""), {})
            disputed = item.verification_state is VerificationState.DISPUTED
            result.append(
                AttentionItem(
                    id=_stable_id("verification_failed", item.id, item.work_order_id),
                    kind="verification_failed",
                    severity="urgent" if disputed else "attention",
                    status=item.verification_state.value,
                    title="Evidence verification did not pass",
                    summary=self._safe_reason(work.get("title") or item.subject or "Evidence requires review"),
                    reason=(
                        "Evidence is disputed and cannot support a completion claim."
                        if disputed
                        else "Evidence was rejected and cannot support a completion claim."
                    ),
                    authority="evidence_store",
                    action_type="inspect_evidence",
                    deep_link=self._work_link(work, section="work-plan"),
                    project_id=work.get("project_id") or item.project_id,
                    project_name=work.get("project_name"),
                    goal_id=work.get("goal_id") or item.goal_id,
                    plan_id=work.get("plan_id") or item.plan_id,
                    plan_version=work.get("plan_version"),
                    work_order_id=item.work_order_id,
                    work_order_title=work.get("title"),
                    worker_type=work.get("worker_type"),
                    execution_id=work.get("execution_id"),
                    evidence_id=item.id,
                    created_at=item.created_at,
                    updated_at=item.created_at,
                    requires_owner_action=True,
                )
            )
        return result

    def _plan_review_items(self, bridge) -> list[AttentionItem]:
        if bridge is None:
            return []
        work = self.work_service.summary(work_order_limit=1)
        result: list[AttentionItem] = []
        for project in work.get("projects") or []:
            plan_id = str(project.get("plan_id") or "")
            if not plan_id:
                continue
            projected = bridge.work.latest_plan_for_source(plan_id)
            if projected is None:
                continue
            with bridge.lock:
                review = PlanReviewStore(bridge.connection).latest(projected.id)
            if review is None or review.status.value != "hold":
                continue
            reason = self._safe_reason(review.blockers[0] if review.blockers else "Plan review is on hold")
            result.append(
                AttentionItem(
                    id=_stable_id("review_failed", projected.id, review.id),
                    kind="review_failed",
                    severity="attention",
                    status="hold",
                    title="Plan review requires attention",
                    summary=self._safe_reason(project.get("project_name") or "Project plan is on hold"),
                    reason=reason,
                    authority="deterministic_reviewer",
                    action_type="inspect_plan",
                    deep_link=(
                        f"/iphone/?project={project.get('project_id')}&section=work-plan"
                        if project.get("project_id")
                        else "/iphone/"
                    ),
                    project_id=project.get("project_id"),
                    project_name=project.get("project_name"),
                    goal_id=projected.goal_id,
                    plan_id=plan_id,
                    plan_version=projected.version,
                    created_at=review.created_at,
                    updated_at=review.created_at,
                    requires_owner_action=True,
                )
            )
        return result

    @staticmethod
    def _dict_sort_key(item: dict[str, Any]) -> tuple:
        return (
            _KIND_PRIORITY.get(str(item.get("kind") or ""), 99),
            _SEVERITY_PRIORITY.get(str(item.get("severity") or ""), 99),
            str(item.get("project_name") or "").lower(),
            str(item.get("work_order_title") or item.get("title") or "").lower(),
            str(item.get("id") or ""),
        )

    def summary(self, **kwargs) -> dict[str, Any]:
        snapshot = super().summary(**kwargs)
        bridge = self._bridge()
        work_map = self._work_map()
        extras = (
            self._claim_items(bridge, work_map)
            + self._evidence_items(bridge, work_map)
            + self._plan_review_items(bridge)
        )
        by_id = {str(item.get("id")): item for item in snapshot.get("items") or []}
        for item in extras:
            by_id.setdefault(item.id, item.to_dict())
        items = sorted(by_id.values(), key=self._dict_sort_key)
        limit = max(1, min(int(kwargs.get("limit", 100)), 200))
        items = items[:limit]
        snapshot["items"] = items
        snapshot["counts"] = {
            "total": len(items),
            "approval": sum(item.get("kind") == "approval_required" for item in items),
            "recovery": sum(item.get("kind") in {"recovery_required", "uncertain_effect"} for item in items),
            "review": sum(item.get("kind") in {"verification_failed", "review_failed", "claim_unsupported"} for item in items),
            "blocked": sum(item.get("kind") == "blocked" for item in items),
            "urgent": sum(item.get("severity") in {"critical", "urgent"} for item in items),
        }
        snapshot["decision_authorities"].update(
            {
                "evidence": "evidence_store",
                "claims": "claim_gate",
                "review": "deterministic_reviewer",
            }
        )
        return snapshot
