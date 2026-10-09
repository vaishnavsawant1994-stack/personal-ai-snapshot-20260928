from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from models.hybrid import HybridRequest, PrivacyMode, SafeContext

from .capabilities import CapabilityRegistry
from .context_pack import ContextPackBuilder
from .lowering import bind_to_projection, lower_to_p10_tasks
from .models import ReadinessStatus, WorkPlan, WorkPlanStatus
from .planner import StrategicWorkPlanner
from .replanner import PlanDeltaStore, ReplanSafetyError, compute_task_delta, prepare_safe_replacement
from .reviewer import PlanReviewStore


_EXECUTION_FIELDS = (
    "status",
    "result_ref",
    "operation_plan_id",
    "operation_id",
    "approval_ref",
)


def install(cls) -> None:
    """Install safe versioned replanning above the existing P10 execution authority."""
    if getattr(cls, "_versioned_replanning_installed", False):
        return

    original_init = cls.__init__
    original_status = cls.status

    def _tool_registry(self):
        executor = getattr(getattr(self, "operations", None), "executor", None)
        return getattr(executor, "tools", None)

    def _capabilities(self) -> CapabilityRegistry:
        return CapabilityRegistry.from_tool_registry(_tool_registry(self))

    def _project_store(self):
        return getattr(self, "project_store", None)

    def _generate_json(self, goal, context, prompt: str, system: str):
        if self.models is None:
            raise RuntimeError("canonical model router unavailable")
        if not hasattr(self.models, "hybrid_chat"):
            if hasattr(self.models, "json"):
                return self.models.json(
                    prompt,
                    system=system,
                    sensitivity=str(goal.get("risk", "low")),
                    private_context=context.prompt_text(),
                )
            raise RuntimeError("canonical P9 hybrid model router unavailable")

        raw_privacy = str(goal.get("privacy", "local_preferred")).lower()
        aliases = {
            "local_only": PrivacyMode.LOCAL_ONLY,
            "local_preferred": PrivacyMode.LOCAL_PREFERRED,
            "external_allowed": PrivacyMode.EXTERNAL_ALLOWED,
        }
        request = HybridRequest(
            capability="chat",
            sensitivity=str(goal.get("risk", "low")),
            privacy=aliases.get(raw_privacy, PrivacyMode.LOCAL_PREFERRED),
            owner_id=str(goal.get("owner_id", "owner")),
            device_trusted=True,
            session_fresh=True,
            emergency_stop=self._canonical_stop_active(),
            consequential=False,
        )
        safe_context = SafeContext.bounded(
            memory=[item.text for item in context.memory],
            knowledge=[item.text for item in context.knowledge],
            world=[],
            references=[item.text for item in context.evidence],
            per_source_limit=8,
            item_limit=1000,
        )
        text = self.models.hybrid_chat(prompt, request=request, context=safe_context, system=system)
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid strategic replan model response") from exc

    def _apply_worker_review(self, candidate, review, capabilities):
        registry = getattr(self, "_worker_registry", None)
        if registry is None:
            return candidate, review, None
        assessment = registry.assess_plan(candidate, capabilities)
        blockers = tuple(dict.fromkeys((*review.blockers, *assessment.blockers)))
        warnings = tuple(dict.fromkeys((*review.warnings, *assessment.warnings)))
        status = ReadinessStatus.HOLD if blockers else ReadinessStatus.DEGRADED if warnings else ReadinessStatus.READY
        score = max(0.0, min(review.score, assessment.score, 100.0 - 25.0 * len(blockers) - 5.0 * len(warnings)))
        review = replace(
            review,
            status=status,
            score=score,
            blockers=blockers,
            warnings=warnings,
            checks={**dict(review.checks), "worker_assessment": assessment.to_dict()},
        )
        plan_status = WorkPlanStatus.HOLD if status is ReadinessStatus.HOLD else WorkPlanStatus.DEGRADED if status is ReadinessStatus.DEGRADED else WorkPlanStatus.READY
        candidate = replace(
            candidate,
            readiness=status,
            status=plan_status,
            critic={
                **dict(candidate.critic),
                "worker_assessment": assessment.to_dict(),
                "worker_authority": "proposal_only",
                "replan_candidate": True,
            },
        )
        return candidate, review, assessment

    def _restore_completed_execution(self, replanned: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        completed = {
            str(task["id"]): task
            for task in previous.get("tasks", [])
            if str(task.get("status") or "").upper() == "COMPLETED"
        }
        for task in replanned.get("tasks", []):
            source = completed.get(str(task.get("id")))
            if source is None:
                continue
            for key in _EXECUTION_FIELDS:
                if key in source:
                    task[key] = source.get(key)
        replanned["state"] = "COMPLETED" if replanned.get("tasks") and all(
            str(task.get("status") or "").upper() == "COMPLETED" for task in replanned["tasks"]
        ) else "READY"
        return self._save_plan(replanned)

    def _preserve_completed_orders(self, bound: WorkPlan, projected: WorkPlan, previous: WorkPlan, previous_p10: dict[str, Any]) -> WorkPlan:
        completed_ids = {
            str(task["id"])
            for task in previous_p10.get("tasks", [])
            if str(task.get("status") or "").upper() == "COMPLETED"
        }
        if not completed_ids:
            return bound
        present = {
            str(order.resource_scope.metadata.get("p10_task_id") or "")
            for order in bound.work_orders
        }
        projected_by_task = {
            str(order.resource_scope.metadata.get("p10_task_id") or ""): order
            for order in projected.work_orders
        }
        previous_by_task = {
            str(order.resource_scope.metadata.get("p10_task_id") or ""): order
            for order in previous.work_orders
        }
        preserved = []
        for task_id in sorted(completed_ids - present):
            base = projected_by_task.get(task_id)
            prior = previous_by_task.get(task_id)
            if base is None or prior is None:
                continue
            preserved.append(
                replace(
                    prior,
                    id=base.id,
                    plan_id=projected.id,
                    project_id=projected.project_id or prior.project_id,
                    status=base.status,
                    dependencies=base.dependencies,
                    workflow_id=base.workflow_id,
                    workflow_run_id=base.workflow_run_id,
                    created_at=base.created_at,
                    updated_at=base.updated_at,
                )
            )
        if not preserved:
            return bound
        return replace(bound, work_orders=tuple((*bound.work_orders, *preserved)))

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._versioned_last_delta = None

    def replan_hierarchical_plan(
        self,
        plan_id,
        *,
        owner_id="owner",
        reason="changed conditions",
        query=None,
    ):
        reason = str(reason).strip()
        if not reason:
            raise ValueError("replan reason is required")
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")

        current_p10 = self.plan(plan_id, owner_id=owner_id)
        current_work = bridge.work_plan_for_p10(plan_id)
        if current_work is None:
            raise KeyError("work plan projection not found")
        if not bool(current_work.critic.get("hierarchical_planning")):
            raise ReplanSafetyError("versioned strategic replanning requires a hierarchical WorkPlan")
        if int(current_p10.get("replan_count", 0)) >= int(getattr(self, "MAX_REPLANS", 5)):
            raise RuntimeError("replan limit exceeded")

        p10_goal = self.goal(current_p10["goal_id"], owner_id=owner_id)
        goal_spec = bridge.project_goal(p10_goal)
        capabilities = _capabilities(self)
        tools = capabilities.available_tool_names() if capabilities.source_available else None
        plan_snapshot = [
            {
                "id": str(task.get("id")),
                "status": str(task.get("status")),
                "objective": str(task.get("objective") or "")[:500],
            }
            for task in current_p10.get("tasks", [])[:50]
        ]
        recent = list(getattr(self, "_outcomes", [])[-8:])
        recent.append({"kind": "replan", "reason": reason[:500], "current_plan": plan_snapshot})
        context = ContextPackBuilder(
            memory=getattr(self, "memory", None),
            knowledge=getattr(self, "knowledge", None),
            project_store=_project_store(self),
            evidence_store=bridge.evidence,
        ).build(
            goal_id=goal_spec.id,
            query=str(query or f"{p10_goal.get('description', '')} Replan reason: {reason}")[:2000],
            project_id=goal_spec.project_id,
            available_tools=tools or (),
            recent_results=recent,
            blockers=("Completed work is immutable; executed failed/cancelled work must use new task ids.",),
        )
        planner = StrategicWorkPlanner(
            lambda prompt, system: _generate_json(self, p10_goal, context, prompt, system)
        )
        candidate, review = planner.propose(goal_spec, context, available_tools=tools)
        candidate, review, worker_assessment = _apply_worker_review(self, candidate, review, capabilities)
        self._hierarchical_last_review = review.to_dict()

        if review.status is ReadinessStatus.HOLD:
            self._event(
                "hierarchical_replan_hold",
                goal_id=current_p10["goal_id"],
                plan_id=plan_id,
                reason=reason[:300],
                blockers=list(review.blockers),
                warnings=list(review.warnings),
                model_output_authority=False,
            )
            return {
                "created": False,
                "reason": "readiness_hold",
                "work_plan": candidate.to_dict(),
                "review": review.to_dict(),
                "authority": "planning_only",
            }

        lowered = lower_to_p10_tasks(candidate, goal_spec)
        safe_replacement = prepare_safe_replacement(current_p10, lowered)
        changes = compute_task_delta(current_p10.get("tasks", []), safe_replacement)
        if not changes:
            return {
                "created": False,
                "reason": "no_semantic_change",
                "work_plan": current_work.to_dict(),
                "review": review.to_dict(),
                "authority": "existing_p10_p6_runtime",
            }

        replanned = self.replan(plan_id, safe_replacement, owner_id=owner_id, reason=reason)
        replanned = _restore_completed_execution(self, replanned, current_p10)
        refreshed_goal = self.goal(replanned["goal_id"], owner_id=owner_id)
        projected = bridge.project_plan(replanned, refreshed_goal, force_new_version=False)
        bound = bind_to_projection(candidate, projected)
        bound = _preserve_completed_orders(self, bound, projected, current_work, current_p10)
        review = replace(review, plan_id=bound.id, plan_version=bound.version)
        delta_store = PlanDeltaStore(bridge.connection)
        with bridge.lock:
            bridge.work.save_plan(bound, source_p10_plan_id=plan_id)
            PlanReviewStore(bridge.connection).record(review)
            delta = delta_store.record(
                goal_id=bound.goal_id,
                from_plan_id=current_work.id,
                to_plan_id=bound.id,
                reason=reason,
                changes=changes,
                from_version=current_work.version,
                to_version=bound.version,
                metadata={
                    "source_p10_plan_id": plan_id,
                    "context_fingerprint": context.fingerprint,
                    "model_output_authority": False,
                    "execution_authority": "existing_p10_p6_runtime",
                },
            )
        self._versioned_last_delta = delta.to_dict()
        self._hierarchical_last_review = review.to_dict()
        counts = {
            "add": sum(1 for item in changes if item.kind.value == "add"),
            "modify": sum(1 for item in changes if item.kind.value == "modify"),
            "remove": sum(1 for item in changes if item.kind.value == "remove"),
        }
        self._event(
            "hierarchical_replanned",
            goal_id=bound.goal_id,
            plan_id=plan_id,
            from_work_plan_id=current_work.id,
            to_work_plan_id=bound.id,
            from_version=current_work.version,
            to_version=bound.version,
            reason=reason[:300],
            delta_counts=counts,
            model_output_authority=False,
            execution_authority="existing_p10_p6_runtime",
        )
        return {
            "created": True,
            "p10_plan": replanned,
            "work_plan": bound.to_dict(),
            "review": review.to_dict(),
            "delta": delta.to_dict(),
            "workers": worker_assessment.to_dict() if worker_assessment is not None else None,
            "authority": "existing_p10_p6_runtime",
        }

    def replan_history(self, plan_id, *, owner_id="owner"):
        p10_plan = self.plan(plan_id, owner_id=owner_id)
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        with bridge.lock:
            items = PlanDeltaStore(bridge.connection).list_for_goal(str(p10_plan["goal_id"]))
        return [item.to_dict() for item in items]

    def status(self):
        result = original_status(self)
        result["versioned_replanning"] = {
            "installed": True,
            "authority": "planning_only",
            "execution_authority": "existing_p10_p6_runtime",
            "completed_work_immutable": True,
            "active_work_replan": "blocked",
            "last_delta": self._versioned_last_delta,
        }
        return result

    cls.__init__ = __init__
    cls.replan_hierarchical_plan = replan_hierarchical_plan
    cls.replan_history = replan_history
    cls.status = status
    cls._versioned_replanning_installed = True
