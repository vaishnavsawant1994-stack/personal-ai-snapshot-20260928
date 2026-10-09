from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from evidence import ClaimState, EvidenceProvenance, VerificationState
from memory.second_brain import MemoryCandidate


_SECRET = re.compile(
    r"\b(password|passwd|secret|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|"
    r"authorization|bearer|cookie|private[ _-]?key|credential)\b",
    re.IGNORECASE,
)
_FORBIDDEN_CONTEXT = re.compile(
    r"\b(system prompt|developer prompt|raw prompt|tool parameters?|tool arguments?|"
    r"authorization header|request headers?)\b",
    re.IGNORECASE,
)
_TRANSIENT = re.compile(
    r"\b(completed|succeeded|finished|passed|sent|published|deployed|created|uploaded|"
    r"downloaded|installed|started|stopped|running)\b",
    re.IGNORECASE,
)
_REUSABLE = re.compile(
    r"\b(prefers?|preference|requires?|must|should|uses?|api|endpoint|route|domain|url|"
    r"repository|branch|provider|environment|format|language|timezone|policy|constraint|"
    r"architecture|convention|workflow|approval|legal|compliance|version|path|customer|"
    r"product|project|decision|integration|database|schema)\b",
    re.IGNORECASE,
)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)
_SENSITIVE_CLASSIFICATIONS = {"sensitive", "secret", "restricted", "confidential", "credential"}


@dataclass(frozen=True)
class PromotionAssessment:
    useful: bool
    reason: str


def assess_usefulness(text: str) -> PromotionAssessment:
    """Conservative deterministic filter for durable, reusable Work knowledge."""
    value = " ".join(str(text or "").split()).strip()
    if len(value) < 20:
        return PromotionAssessment(False, "too_short_for_durable_knowledge")
    if _SECRET.search(value):
        return PromotionAssessment(False, "secret_shaped_content")
    if _FORBIDDEN_CONTEXT.search(value):
        return PromotionAssessment(False, "raw_prompt_or_tool_context")
    if len(_UUID.findall(value)) >= 2:
        return PromotionAssessment(False, "execution_identifier_heavy")
    reusable = bool(_REUSABLE.search(value))
    if _TRANSIENT.search(value) and not reusable:
        return PromotionAssessment(False, "transient_execution_status")
    if reusable:
        return PromotionAssessment(True, "stable_reusable_fact")
    if len(value) >= 64 and any(token in value.lower() for token in (" is ", " are ", " has ", " maps to ", " belongs to ")):
        return PromotionAssessment(True, "verified_declarative_fact")
    return PromotionAssessment(False, "insufficient_reuse_signal")


def _safe_classification(value: Any) -> bool:
    return str(value or "internal").strip().lower() not in _SENSITIVE_CLASSIFICATIONS


def _verified_evidence(items: Iterable[Any]) -> list[Any]:
    result = []
    for item in items:
        if getattr(item, "verification_state", None) is not VerificationState.VERIFIED:
            continue
        provenance = getattr(item, "provenance", EvidenceProvenance.MODEL_ONLY)
        if provenance.rank < EvidenceProvenance.OBSERVED.rank:
            continue
        if not _safe_classification(getattr(item, "data_classification", "internal")):
            continue
        observation = str(getattr(item, "observation", ""))
        if _SECRET.search(observation) or _FORBIDDEN_CONTEXT.search(observation):
            continue
        result.append(item)
    return result


class WorkMemoryPromotionBridge:
    """Propose evidence-backed Work knowledge to existing GovernedMemory.

    This bridge has no memory-approval authority. Every Work candidate is submitted
    with force_review=True, so GovernedMemory remains the sole candidate lifecycle
    and SecondBrain promotion authority.
    """

    _TRIGGERS = (
        "work_completion_observed",
        "work.review.passed",
        "work.claim.verified",
        "work.evidence.recorded",
    )

    def __init__(self, events: Any, autonomy: Any, memory: Any, *, max_candidates_per_order: int = 3) -> None:
        self.events = events
        self.autonomy = autonomy
        self.memory = memory
        self.max_candidates_per_order = max(1, min(int(max_candidates_per_order), 5))
        self._unsubscribers = [events.subscribe(name, self.consider) for name in self._TRIGGERS]

    def close(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                unsubscribe()
            except Exception:
                pass
        self._unsubscribers = []

    @staticmethod
    def _order_for_task(work_plan: Mapping[str, Any], task_id: str) -> dict[str, Any] | None:
        for raw in work_plan.get("work_orders") or []:
            if not isinstance(raw, Mapping):
                continue
            order = dict(raw)
            metadata = ((order.get("resource_scope") or {}).get("metadata") or {})
            if str(metadata.get("p10_task_id") or "") == str(task_id):
                return order
        return None

    def _candidate(
        self,
        *,
        text: str,
        subject: str,
        source_id: str,
        source_type: str,
        source_created_at: str | None,
        project_id: str | None,
        goal_id: str | None,
        plan_id: str,
        plan_version: int,
        work_order_id: str,
        evidence_ids: list[str],
        claim_ids: list[str],
        review_state: str,
        confidence: float,
        worker_type: str,
    ) -> str | None:
        assessment = assess_usefulness(text)
        if not assessment.useful:
            return None
        bounded_text = " ".join(str(text).split())[:1800]
        candidate = MemoryCandidate(
            type="fact",
            subject=(str(subject).strip() or "Verified Project knowledge")[:240],
            content=bounded_text,
            confidence=max(0.0, min(float(confidence), 1.0)),
            source="verified-work",
            verified=True,
            tags=list(dict.fromkeys(["work", "verified", "project", str(worker_type or "worker")]))[:12],
            importance=0.72,
            sensitivity="normal",
            occurred_at=source_created_at,
            evidence=list(evidence_ids)[:20],
            metadata={
                "scope": "project" if project_id else "work",
                "project_id": project_id,
                "goal_id": goal_id,
                "plan_id": plan_id,
                "plan_version": int(plan_version),
                "work_order_id": work_order_id,
                "evidence_ids": list(evidence_ids)[:20],
                "claim_ids": list(claim_ids)[:20],
                "verification_state": "verified",
                "review_state": str(review_state or "passed"),
                "source_type": source_type,
                "source_id": source_id,
                "created_at": source_created_at,
                "usefulness_reason": assessment.reason,
                "promotion_mode": "governed_candidate_only",
            },
        )
        request_id = f"work-memory:{plan_id}:{plan_version}:{work_order_id}:{source_type}:{source_id}"
        return self.memory.remember(candidate, owner_id="owner", request_id=request_id, force_review=True)

    def consider(self, event: Mapping[str, Any]) -> list[str]:
        plan_id = str(event.get("plan_id") or "")
        task_id = str(event.get("task_id") or "")
        if not plan_id or not task_id:
            return []
        try:
            decision = self.autonomy.work_order_completion(plan_id, task_id, owner_id="owner")
        except (KeyError, RuntimeError, PermissionError):
            return []
        if not bool(decision.get("passed")):
            return []
        if str(decision.get("review_state") or "").lower() in {"failed", "rejected", "hold"}:
            return []

        try:
            work_plan = self.autonomy.work_plan(plan_id, owner_id="owner")
        except (KeyError, RuntimeError, PermissionError):
            return []
        order = self._order_for_task(work_plan, task_id)
        if order is None:
            return []
        work_order_id = str(order.get("id") or "")
        if not work_order_id:
            return []

        bridge = getattr(self.autonomy, "_work_bridge", None)
        store = getattr(bridge, "evidence", None) if bridge is not None else None
        if store is None:
            return []

        evidence = _verified_evidence(store.list_evidence(work_order_id=work_order_id))
        if not evidence:
            return []
        evidence_by_id = {str(item.id): item for item in evidence}
        verified_claims = list(store.list_claims(work_order_id=work_order_id, state=ClaimState.VERIFIED))
        project_id = order.get("project_id") or work_plan.get("project_id")
        goal_id = work_plan.get("goal_id")
        plan_version = int(work_plan.get("version") or 1)
        review_state = str(decision.get("review_state") or "passed")
        worker_type = str(order.get("worker_type") or "worker")

        proposed: list[str] = []
        used_text: set[str] = set()

        for claim in verified_claims:
            linked = [item for item in _verified_evidence(store.evidence_for_claim(claim.id)) if str(item.id) in evidence_by_id]
            if not linked:
                continue
            text = " ".join(str(claim.text).split()).strip()
            key = text.lower()
            if not text or key in used_text:
                continue
            candidate_id = self._candidate(
                text=text,
                subject=str(order.get("title") or "Verified Project knowledge"),
                source_id=str(claim.id),
                source_type="verified_claim",
                source_created_at=str(getattr(claim, "created_at", "") or "") or None,
                project_id=str(project_id) if project_id else None,
                goal_id=str(goal_id) if goal_id else None,
                plan_id=plan_id,
                plan_version=plan_version,
                work_order_id=work_order_id,
                evidence_ids=[str(item.id) for item in linked],
                claim_ids=[str(claim.id)],
                review_state=review_state,
                confidence=float(getattr(claim, "confidence", 0.8) or 0.8),
                worker_type=worker_type,
            )
            if candidate_id:
                proposed.append(str(candidate_id)); used_text.add(key)
            if len(proposed) >= self.max_candidates_per_order:
                return proposed

        for item in evidence:
            text = " ".join(str(item.observation).split()).strip()
            key = text.lower()
            if not text or key in used_text:
                continue
            candidate_id = self._candidate(
                text=text,
                subject=str(item.subject or order.get("title") or "Verified Project knowledge"),
                source_id=str(item.id),
                source_type="verified_evidence",
                source_created_at=str(getattr(item, "created_at", "") or "") or None,
                project_id=str(project_id) if project_id else None,
                goal_id=str(goal_id) if goal_id else None,
                plan_id=plan_id,
                plan_version=plan_version,
                work_order_id=work_order_id,
                evidence_ids=[str(item.id)],
                claim_ids=[],
                review_state=review_state,
                confidence=float(getattr(item, "confidence", 0.8) or 0.8),
                worker_type=worker_type,
            )
            if candidate_id:
                proposed.append(str(candidate_id)); used_text.add(key)
            if len(proposed) >= self.max_candidates_per_order:
                break
        return proposed
