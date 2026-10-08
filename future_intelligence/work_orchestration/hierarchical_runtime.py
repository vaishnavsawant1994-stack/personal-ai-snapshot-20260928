from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from models.hybrid import HybridRequest, PrivacyMode, SafeContext
from future_intelligence.workers import WorkerRegistry

from .capabilities import CapabilityRegistry
from .context_pack import ContextPackBuilder
from .lowering import bind_to_projection, lower_to_p10_tasks
from .models import ReadinessStatus, WorkPlan, WorkPlanStatus
from .planner import StrategicWorkPlanner
from .reviewer import PlanReviewStore


def install(cls) -> None:
    """Install strategic planning above P10 without creating execution authority."""
    if getattr(cls, "_hierarchical_work_planning_installed", False):
        return

    original_init = cls.__init__
    original_status = cls.status
    original_work_plan = cls.work_plan

    def _tool_registry(self):
        executor = getattr(getattr(self, "operations", None), "executor", None)
        return getattr(executor, "tools", None)

    def _capabilities(self) -> CapabilityRegistry:
        return CapabilityRegistry.from_tool_registry(_tool_registry(self))

    def _available_tools(self) -> tuple[str, ...] | None:
        capabilities = _capabilities(self)
        return capabilities.available_tool_names() if capabilities.source_available else None

    def _patch_bridge(self) -> None:
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None or getattr(bridge, "_hierarchical_preservation_installed", False):
            return
        original_project_goal = bridge.project_goal
        original_project_plan = bridge.project_plan

        def project_goal_preserving(p10_goal):
            with bridge.lock:
                incoming = dict(p10_goal)
                if not incoming.get("project_id"):
                    existing_goal = bridge.work.get_goal(str(incoming.get("id") or ""))
                    if existing_goal is not None and existing_goal.project_id:
                        incoming["project_id"] = existing_goal.project_id
                return original_project_goal(incoming)

        bridge.project_goal = project_goal_preserving

        def project_plan_preserving(p10_plan, p10_goal, *, force_new_version=False):
            with bridge.lock:
                existing = bridge.work.latest_plan_for_source(str(p10_plan["id"]))
                result = original_project_plan(p10_plan, p10_goal, force_new_version=force_new_version)
                if (
                    existing is None
                    or force_new_version
                    or not bool(existing.critic.get("hierarchical_planning"))
                    or existing.id != result.id
                    or existing.version != result.version
                ):
                    return result

                old_orders = {order.id: order for order in existing.work_orders}
                merged_orders = []
                for base in result.work_orders:
                    prior = old_orders.get(base.id)
                    if prior is None:
                        merged_orders.append(base)
                        continue
                    merged_orders.append(
                        replace(
                            prior,
                            status=base.status,
                            workflow_id=base.workflow_id,
                            workflow_run_id=base.workflow_run_id,
                            updated_at=base.updated_at,
                        )
                    )
                enriched = WorkPlan(
                    id=result.id,
                    goal_id=result.goal_id,
                    project_id=existing.project_id or result.project_id,
                    version=result.version,
                    summary=existing.summary,
                    milestones=existing.milestones,
                    work_orders=tuple(merged_orders),
                    assumptions=existing.assumptions,
                    evidence_contract=existing.evidence_contract,
                    critic={
                        **dict(existing.critic),
                        "source_p10_state": result.critic.get("source_p10_state"),
                        "observe_only": True,
                    },
                    readiness=existing.readiness,
                    status=result.status,
                    supersedes_plan_id=result.supersedes_plan_id,
                    created_at=result.created_at,
                )
                return bridge.work.save_plan(enriched, source_p10_plan_id=str(p10_plan["id"]))

        bridge.project_goal = project_goal_preserving
        bridge.project_plan = project_plan_preserving
        bridge._hierarchical_preservation_installed = True

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _patch_bridge(self)
        self._hierarchical_last_review = None
        self._worker_registry = WorkerRegistry.default()

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
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid strategic model response") from exc
        return parsed

    def _apply_worker_review(self, candidate, review, capabilities):
        assessment = self._worker_registry.assess_plan(candidate, capabilities)
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
            },
        )
        return candidate, review, assessment

    def propose_hierarchical_plan(
        self,
        goal_id,
        *,
        owner_id="owner",
        project_id=None,
        query=None,
    ):
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        p10_goal = self.goal(goal_id, owner_id=owner_id)
        projection_input = dict(p10_goal)
        if project_id is not None:
            projection_input["project_id"] = str(project_id)
        goal_spec = bridge.project_goal(projection_input)

        capabilities = _capabilities(self)
        tools = capabilities.available_tool_names() if capabilities.source_available else None
        recent = list(getattr(self, "_outcomes", [])[-10:])
        context = ContextPackBuilder(
            memory=getattr(self, "memory", None),
            knowledge=getattr(self, "knowledge", None),
            project_store=_project_store(self),
            evidence_store=bridge.evidence,
        ).build(
            goal_id=goal_spec.id,
            query=str(query or p10_goal.get("description") or "")[:2000],
            project_id=goal_spec.project_id,
            available_tools=tools or (),
            recent_results=recent,
        )
        strategic = StrategicWorkPlanner(
            lambda prompt, system: _generate_json(self, p10_goal, context, prompt, system)
        )
        candidate, review = strategic.propose(goal_spec, context, available_tools=tools)
        candidate, review, worker_assessment = _apply_worker_review(self, candidate, review, capabilities)
        self._hierarchical_last_review = review.to_dict()

        if review.status is ReadinessStatus.HOLD:
            self._event(
                "hierarchical_plan_hold",
                goal_id=goal_id,
                blockers=list(review.blockers),
                warnings=list(review.warnings),
                context_fingerprint=context.fingerprint,
                worker_assessment=worker_assessment.to_dict(),
                model_output_authority=False,
            )
            return {
                "created": False,
                "work_plan": candidate.to_dict(),
                "review": review.to_dict(),
                "context": {
                    "fingerprint": context.fingerprint,
                    "memory_items": len(context.memory),
                    "knowledge_items": len(context.knowledge),
                    "evidence_items": len(context.evidence),
                },
                "workers": worker_assessment.to_dict(),
                "capabilities": capabilities.status(),
                "authority": "planning_only",
            }

        p10_tasks = lower_to_p10_tasks(candidate, goal_spec)
        p10_plan = self.create_plan(goal_id, p10_tasks, owner_id=owner_id)
        projected = bridge.work_plan_for_p10(p10_plan["id"])
        if projected is None:
            raise RuntimeError("P10 plan was created but WorkPlan projection is unavailable")
        bound = bind_to_projection(candidate, projected)
        review = replace(review, plan_id=bound.id, plan_version=bound.version)
        with bridge.lock:
            bridge.work.save_plan(bound, source_p10_plan_id=p10_plan["id"])
            PlanReviewStore(bridge.connection).record(review)
        self._hierarchical_last_review = review.to_dict()
        self._event(
            "hierarchical_plan_ready",
            goal_id=goal_id,
            plan_id=p10_plan["id"],
            work_plan_id=bound.id,
            readiness=bound.readiness.value,
            readiness_score=review.score,
            warnings=list(review.warnings),
            context_fingerprint=context.fingerprint,
            worker_count=len(worker_assessment.assignments),
            model_output_authority=False,
            execution_authority="existing_p10_p6_runtime",
        )
        return {
            "created": True,
            "p10_plan": p10_plan,
            "work_plan": bound.to_dict(),
            "review": review.to_dict(),
            "context": {
                "fingerprint": context.fingerprint,
                "memory_items": len(context.memory),
                "knowledge_items": len(context.knowledge),
                "evidence_items": len(context.evidence),
            },
            "workers": worker_assessment.to_dict(),
            "capabilities": capabilities.status(),
            "authority": "existing_p10_p6_runtime",
        }

    def work_plan(self, plan_id, *, owner_id="owner"):
        result = original_work_plan(self, plan_id, owner_id=owner_id)
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            return result
        with bridge.lock:
            review = PlanReviewStore(bridge.connection).latest(result["id"])
        if review is not None:
            result = dict(result)
            result["latest_review"] = review.to_dict()
        return result

    def status(self):
        result = original_status(self)
        capabilities = _capabilities(self)
        result["hierarchical_planning"] = {
            "installed": True,
            "authority": "planning_only",
            "execution_authority": "existing_p10_p6_runtime",
            "last_review": self._hierarchical_last_review,
            "workers": self._worker_registry.status(),
            "capabilities": capabilities.status(),
        }
        return result

    cls.__init__ = __init__
    cls.propose_hierarchical_plan = propose_hierarchical_plan
    cls.work_plan = work_plan
    cls.status = status
    cls._hierarchical_work_planning_installed = True
