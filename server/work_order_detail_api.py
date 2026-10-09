from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, HTTPException

from evidence import ClaimGate
from future_intelligence.work_orchestration.review_attention import ReviewAwareWorkAttentionService


class WorkOrderDetailService:
    """Read-only WorkOrder inspection aggregate over existing authorities.

    This service does not execute, approve, verify, recover, review, or complete
    Work. It only joins canonical projections/stores into one owner-facing payload.
    """

    def __init__(self, runtime: dict, store) -> None:
        self.runtime = runtime
        self.store = store

    def _autonomy(self):
        autonomy = self.runtime.get("advanced_autonomy")
        if autonomy is None or getattr(autonomy, "_work_bridge", None) is None:
            raise RuntimeError("work orchestration runtime unavailable")
        if getattr(autonomy, "project_store", None) is not self.store:
            autonomy.project_store = self.store
        return autonomy

    def _project(self, project_id: str) -> dict:
        project = self.store.get(str(project_id))
        if not project or project.get("status") == "archived":
            raise KeyError("project not found")
        return project

    def _assert_project_plan(self, project_id: str, plan_id: str) -> None:
        self._project(project_id)
        records = self._autonomy()._work_bridge.work.project_plan_records(str(project_id))
        if not any(str(item.get("source_p10_plan_id") or "") == str(plan_id) for item in records):
            raise KeyError("project work plan not found")

    @staticmethod
    def _task_for(plan: dict, task_id: str) -> dict:
        task = next((dict(item) for item in plan.get("tasks") or [] if str(item.get("id") or "") == str(task_id)), None)
        if task is None:
            raise KeyError("work task not found")
        return task

    @staticmethod
    def _order_for(work_plan: dict, task_id: str) -> dict:
        for raw in work_plan.get("work_orders") or []:
            order = dict(raw)
            meta = ((order.get("resource_scope") or {}).get("metadata") or {})
            if str(meta.get("p10_task_id") or "") == str(task_id):
                return order
        raise KeyError("canonical WorkOrder not found")

    @staticmethod
    def _milestone_for(work_plan: dict, work_order_id: str) -> dict | None:
        for raw in work_plan.get("milestones") or []:
            if str(work_order_id) in {str(item) for item in raw.get("work_order_ids") or []}:
                return dict(raw)
        return None

    @staticmethod
    def _claim_gate(claim, evidence) -> dict[str, Any]:
        decision = ClaimGate.evaluate(claim, evidence)
        return {
            "claim_id": claim.id,
            "passed": bool(decision.passed),
            "state": decision.state.value,
            "reasons": list(decision.reasons),
            "qualifying_evidence_ids": list(decision.qualifying_evidence_ids),
            "authority": "claim_gate",
        }

    @staticmethod
    def _safe_next_action(task: dict, completion: dict, attention: list[dict]) -> dict:
        if attention:
            first = attention[0]
            return {
                "type": first.get("action_type") or "inspect_attention",
                "label": first.get("title") or "Review attention",
                "reason": first.get("reason"),
                "deep_link": first.get("deep_link"),
                "authority": first.get("authority"),
            }
        state = str(task.get("status") or "").upper()
        if bool(completion.get("passed")):
            return {"type": "none", "label": "WorkOrder complete", "reason": "Completion Judge passed.", "authority": "deterministic_completion_judge"}
        if state in {"WAITING", "READY"}:
            return {"type": "governed_execute", "label": "Start governed work", "reason": "Execution remains subject to Project mode, permissions, approvals, policy and recovery gates.", "authority": "existing_p10_p6_runtime"}
        if state in {"RECOVERY_REQUIRED", "UNCERTAIN", "RECOVERING"}:
            return {"type": "reconcile_recovery", "label": "Reconcile remote state", "reason": "Do not replay an uncertain external effect.", "authority": "recovery_authority"}
        return {"type": "inspect_proof", "label": "Inspect completion proof", "reason": "Canonical completion has not passed yet.", "authority": "deterministic_completion_judge"}

    def detail(
        self,
        project_id: str,
        plan_id: str,
        task_id: str,
        *,
        device_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_project_plan(project_id, plan_id)
        autonomy = self._autonomy()
        p10_plan = autonomy.plan(plan_id, owner_id="owner")
        work_plan = autonomy.work_plan(plan_id, owner_id="owner")
        task = self._task_for(p10_plan, task_id)
        order = self._order_for(work_plan, task_id)
        work_order_id = str(order["id"])
        milestone = self._milestone_for(work_plan, work_order_id)
        completion = autonomy.work_order_completion(plan_id, task_id, owner_id="owner")

        bridge = autonomy._work_bridge
        evidence_store = bridge.evidence
        stored_evidence = evidence_store.list_evidence(work_order_id=work_order_id)
        public_evidence = autonomy.work_evidence(plan_id, task_id, owner_id="owner")
        claims = evidence_store.list_claims(work_order_id=work_order_id)
        claim_rows = []
        for claim in claims:
            linked = evidence_store.evidence_for_claim(claim.id)
            claim_rows.append({
                **claim.to_dict(),
                "evidence_ids": [item.id for item in linked],
                "gate": self._claim_gate(claim, linked),
            })

        execution_id = str(task.get("operation_id") or task.get("execution_id") or task.get("result_ref") or "")
        receipts = evidence_store.list_receipts(execution_id=execution_id) if execution_id else []

        try:
            attention_snapshot = ReviewAwareWorkAttentionService(self.runtime, self.store).summary(
                owner_id="owner",
                device_id=device_id,
                session_id=session_id,
                limit=200,
            )
            attention = [
                dict(item)
                for item in attention_snapshot.get("items") or []
                if str(item.get("work_order_id") or "") == work_order_id
                or (str(item.get("plan_id") or "") == str(plan_id) and str(item.get("execution_id") or "") == execution_id and execution_id)
            ]
        except RuntimeError:
            attention = []

        try:
            versions = autonomy.work_plan_versions(plan_id, owner_id="owner") if hasattr(autonomy, "work_plan_versions") else []
            deltas = autonomy.work_plan_deltas(plan_id, owner_id="owner") if hasattr(autonomy, "work_plan_deltas") else []
        except (KeyError, RuntimeError):
            versions, deltas = [], []

        requested_tool = str(((order.get("resource_scope") or {}).get("metadata") or {}).get("requested_tool") or "") or None
        recovery_attention = [item for item in attention if item.get("kind") in {"recovery_required", "uncertain_effect"}]
        approval_attention = [item for item in attention if item.get("kind") in {"approval_required", "owner_decision_required", "reauthentication_required"}]
        review = work_plan.get("latest_review")

        return {
            "project_id": str(project_id),
            "plan_id": str(plan_id),
            "task_id": str(task_id),
            "work_order_id": work_order_id,
            "title": order.get("title"),
            "objective": order.get("objective"),
            "milestone": milestone,
            "worker": order.get("worker_type"),
            "execution_status": task.get("status") or order.get("execution_status") or order.get("status"),
            "canonical_status": order.get("status"),
            "dependencies": list(order.get("dependencies") or []),
            "required_capabilities": list(order.get("allowed_capabilities") or []),
            "requested_tool": requested_tool,
            "resource_scope": order.get("resource_scope") or {},
            "expected_output": order.get("expected_output"),
            "success_criteria": list(order.get("success_criteria") or []),
            "evidence_contract": order.get("evidence_contract") or {},
            "verification_strategy": order.get("verification_strategy") or {},
            "falsifier": order.get("falsifier"),
            "retest_strategy": order.get("retest_strategy") or {},
            "approval_requirement": order.get("approval_policy") or {},
            "reauthentication": {
                "required": bool((order.get("approval_policy") or {}).get("requires_reauthentication") or task.get("reauthentication_required")),
                "attention": approval_attention,
            },
            "budget": {
                "time_budget_seconds": order.get("time_budget_seconds"),
                "cost_budget": order.get("cost_budget"),
            },
            "current_execution": task,
            "evidence": public_evidence,
            "evidence_count": len(stored_evidence),
            "receipts": [item.to_dict() for item in receipts],
            "claims": claim_rows,
            "domain_claim_type": completion.get("domain_claim_type"),
            "claim_gate": {
                "authority": "claim_gate",
                "decisions": [item["gate"] for item in claim_rows],
            },
            "reviewer_decision": review,
            "completion_judge": completion,
            "attention": attention,
            "recovery": {
                "state": task.get("status") if str(task.get("status") or "").upper() in {"RECOVERY_REQUIRED", "UNCERTAIN", "RECOVERING"} else "none",
                "recovery_id": task.get("recovery_id") or task.get("operation_id"),
                "attention": recovery_attention,
            },
            "plan_version": int(work_plan.get("version") or 1),
            "replan_history": {"versions": versions, "deltas": deltas},
            "safe_next_action": self._safe_next_action(task, completion, attention),
            "authorities": {
                "execution": "existing_p10_p6_runtime",
                "approval": "approval_manager",
                "evidence": "evidence_store",
                "claims": "claim_gate",
                "review": "deterministic_reviewer",
                "completion": "deterministic_completion_judge",
                "recovery": "recovery_authority",
            },
            "read_only": True,
        }


def work_order_detail_router(runtime: dict, store) -> APIRouter:
    router = APIRouter(prefix="/iphone/api/projects", tags=["work-order-detail"])
    service = WorkOrderDetailService(runtime, store)
    registry = runtime["device_registry"]

    def authenticate(device_id: str | None, token: str | None):
        if not device_id or not token:
            raise HTTPException(401, "Owner device sign-in required")
        try:
            registry.authenticate(device_id, token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc

    @router.get("/{project_id}/work/{plan_id}/orders/{task_id}")
    def work_order_detail(
        project_id: str,
        plan_id: str,
        task_id: str,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token)
        try:
            return service.detail(project_id, plan_id, task_id, device_id=pa_device)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
