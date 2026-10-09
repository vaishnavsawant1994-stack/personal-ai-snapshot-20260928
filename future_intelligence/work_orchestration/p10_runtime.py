from __future__ import annotations

from typing import Any

from .p10_bridge import P10WorkBridge


def install(cls) -> None:
    """Install an observe-only Work/Evidence projection under the existing P10 authority."""
    if getattr(cls, "_work_orchestration_runtime_installed", False):
        return

    original_init = cls.__init__
    original_create_goal = cls.create_goal
    original_create_plan = cls.create_plan
    original_replan = cls.replan
    original_mark_task = cls.mark_task
    original_pause = cls.pause
    original_resume = cls.resume
    original_cancel = cls.cancel
    original_status = cls.status
    original_execute_task = cls.execute_task
    original_approve_task = cls.approve_task
    original_deny_task = cls.deny_task
    original_cancel_governed = cls.cancel_governed

    def _bridge(self) -> P10WorkBridge | None:
        return getattr(self, "_work_bridge", None)

    def _safe_event(self, kind: str, **payload: Any) -> None:
        try:
            self._event(kind, **payload)
        except Exception:
            pass

    def _project_goal(self, goal: dict[str, Any]) -> None:
        bridge = _bridge(self)
        if bridge is None:
            return
        try:
            bridge.project_goal(goal)
        except Exception as exc:
            _safe_event(
                self,
                "work_projection_error",
                goal_id=goal.get("id"),
                phase="goal",
                error_type=type(exc).__name__,
            )

    def _project_plan(self, plan: dict[str, Any], *, force_new_version: bool = False) -> None:
        bridge = _bridge(self)
        if bridge is None:
            return
        try:
            goal = self.goal(plan["goal_id"], owner_id=plan.get("owner_id"))
            bridge.project_plan(plan, goal, force_new_version=force_new_version)
        except Exception as exc:
            _safe_event(
                self,
                "work_projection_error",
                goal_id=plan.get("goal_id"),
                plan_id=plan.get("id"),
                phase="plan",
                error_type=type(exc).__name__,
            )

    def _observe_completion(self, plan: dict[str, Any], task_id: str) -> None:
        bridge = _bridge(self)
        if bridge is None:
            return
        task = next((item for item in plan.get("tasks", []) if item.get("id") == task_id), None)
        if task is None:
            return
        try:
            goal = self.goal(plan["goal_id"], owner_id=plan.get("owner_id"))
            assessment = bridge.observe_governed_completion(plan, goal, task)
            if assessment is not None:
                _safe_event(
                    self,
                    "work_completion_observed",
                    goal_id=plan.get("goal_id"),
                    plan_id=plan.get("id"),
                    task_id=task_id,
                    work_order_id=assessment["work_order_id"],
                    evidence_id=assessment.get("evidence_id"),
                    claim_id=assessment.get("claim_id"),
                    claim_state=assessment["claim_state"],
                    evidence_gate_passed=assessment["passed"],
                    projection_mode=assessment["mode"],
                )
        except Exception as exc:
            _safe_event(
                self,
                "work_evidence_error",
                goal_id=plan.get("goal_id"),
                plan_id=plan.get("id"),
                task_id=task_id,
                error_type=type(exc).__name__,
            )

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._work_bridge = None
        if getattr(self, "_db", None) is not None:
            try:
                self._work_bridge = P10WorkBridge(self._db, lock=getattr(self, "_lock", None))
                summary = self._work_bridge.backfill()
                _safe_event(
                    self,
                    "work_projection_ready",
                    projected_goals=summary["goals"],
                    projected_plans=summary["plans"],
                    projection_mode=self._work_bridge.mode,
                )
            except Exception as exc:
                self._work_bridge = None
                _safe_event(
                    self,
                    "work_projection_unavailable",
                    error_type=type(exc).__name__,
                    projection_mode="disabled",
                )

    def create_goal(self, *args, **kwargs):
        goal = original_create_goal(self, *args, **kwargs)
        _project_goal(self, goal)
        return goal

    def create_plan(self, *args, **kwargs):
        plan = original_create_plan(self, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def replan(self, *args, **kwargs):
        plan = original_replan(self, *args, **kwargs)
        _project_plan(self, plan, force_new_version=True)
        return plan

    def mark_task(self, *args, **kwargs):
        plan = original_mark_task(self, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def pause(self, *args, **kwargs):
        plan = original_pause(self, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def resume(self, *args, **kwargs):
        plan = original_resume(self, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def cancel(self, *args, **kwargs):
        plan = original_cancel(self, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def execute_task(self, plan_id, task_id, *args, **kwargs):
        plan = original_execute_task(self, plan_id, task_id, *args, **kwargs)
        _project_plan(self, plan)
        _observe_completion(self, plan, task_id)
        return plan

    def approve_task(self, plan_id, task_id, *args, **kwargs):
        plan = original_approve_task(self, plan_id, task_id, *args, **kwargs)
        _project_plan(self, plan)
        _observe_completion(self, plan, task_id)
        return plan

    def deny_task(self, plan_id, task_id, *args, **kwargs):
        plan = original_deny_task(self, plan_id, task_id, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def cancel_governed(self, plan_id, *args, **kwargs):
        plan = original_cancel_governed(self, plan_id, *args, **kwargs)
        _project_plan(self, plan)
        return plan

    def status(self):
        result = original_status(self)
        bridge = _bridge(self)
        result["work_orchestration"] = (
            bridge.status()
            if bridge is not None
            else {"mode": "disabled", "goals": 0, "plans": 0, "orders": 0, "evidence": 0, "claims": 0}
        )
        return result

    def work_plan(self, plan_id, *, owner_id="owner"):
        self.plan(plan_id, owner_id=owner_id)
        bridge = _bridge(self)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        projected = bridge.work_plan_for_p10(plan_id)
        if projected is None:
            raise KeyError("work plan projection not found")
        return projected.to_dict()

    def work_evidence(self, plan_id, task_id, *, owner_id="owner"):
        plan = self.plan(plan_id, owner_id=owner_id)
        if not any(item.get("id") == task_id for item in plan.get("tasks", [])):
            raise KeyError("task not found")
        bridge = _bridge(self)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        return [item.to_dict() for item in bridge.evidence_for_task(plan_id, task_id)]

    cls.__init__ = __init__
    cls.create_goal = create_goal
    cls.create_plan = create_plan
    cls.replan = replan
    cls.mark_task = mark_task
    cls.pause = pause
    cls.resume = resume
    cls.cancel = cancel
    cls.execute_task = execute_task
    cls.approve_task = approve_task
    cls.deny_task = deny_task
    cls.cancel_governed = cancel_governed
    cls.status = status
    cls.work_plan = work_plan
    cls.work_evidence = work_evidence
    cls._work_orchestration_runtime_installed = True