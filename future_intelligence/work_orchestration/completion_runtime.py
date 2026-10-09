from __future__ import annotations

from typing import Any

from .completion import CompletionJudge, CompletionState
from .reviewer import PlanReviewStore


def install(cls) -> None:
    """Install canonical completion projection without changing P10 execution authority."""
    if getattr(cls, "_completion_judge_runtime_installed", False):
        return

    original_work_plan = cls.work_plan
    original_status = cls.status

    def _completion_report(self, plan_id: str, *, owner_id: str = "owner"):
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            raise RuntimeError("work orchestration projection unavailable")
        p10_plan = self.plan(plan_id, owner_id=owner_id)
        plan = bridge.work_plan_for_p10(plan_id)
        if plan is None:
            raise KeyError("work plan projection not found")
        goal = bridge.work.get_goal(plan.goal_id)
        if goal is None:
            raise KeyError("work goal projection not found")
        with bridge.lock:
            review = PlanReviewStore(bridge.connection).latest(plan.id)
            return CompletionJudge(bridge.evidence).evaluate(
                plan,
                goal,
                p10_plan,
                plan_review=review,
            )

    def work_plan(self, plan_id, *, owner_id="owner"):
        result = original_work_plan(self, plan_id, owner_id=owner_id)
        report = _completion_report(self, plan_id, owner_id=owner_id)
        projected = dict(result)
        projected["completion"] = report.to_dict()

        order_decisions = {item.work_order_id: item for item in report.work_orders}
        orders = []
        for item in projected.get("work_orders", []):
            order = dict(item)
            decision = order_decisions.get(str(order.get("id") or ""))
            if decision is not None:
                order["completion"] = decision.to_dict()
                if str(order.get("status") or "").lower() == "completed" and not decision.passed:
                    order["execution_status"] = "completed"
                    order["status"] = (
                        "verifying"
                        if decision.state is CompletionState.VERIFYING
                        else "reviewing"
                        if decision.state is CompletionState.REVIEWING
                        else "blocked"
                    )
            orders.append(order)
        projected["work_orders"] = orders

        if str(projected.get("status") or "").lower() == "completed" and not report.complete:
            projected["execution_status"] = "completed"
            projected["status"] = (
                "reviewing"
                if report.state in {CompletionState.VERIFYING, CompletionState.REVIEWING}
                else "hold"
            )
        elif report.complete:
            projected["status"] = "completed"
        return projected

    def work_completion(self, plan_id, *, owner_id="owner"):
        # owner_id is authenticated by the underlying plan read.
        self.plan(plan_id, owner_id=owner_id)
        return _completion_report(self, plan_id, owner_id=owner_id).to_dict()

    def work_order_completion(self, plan_id, task_id, *, owner_id="owner"):
        report = _completion_report(self, plan_id, owner_id=owner_id)
        bridge = self._work_bridge
        plan = bridge.work_plan_for_p10(plan_id)
        if plan is None:
            raise KeyError("work plan projection not found")
        canonical_id = next(
            (
                order.id
                for order in plan.work_orders
                if str(order.resource_scope.metadata.get("p10_task_id") or "") == str(task_id)
            ),
            None,
        )
        if canonical_id is None:
            raise KeyError("task not found")
        decision = next((item for item in report.work_orders if item.work_order_id == canonical_id), None)
        if decision is None:
            raise KeyError("completion decision not found")
        return decision.to_dict()

    def status(self):
        result = original_status(self)
        result["completion_judge"] = {
            "installed": True,
            "authority": "deterministic_completion_judge",
            "execution_authority": "existing_p10_p6_runtime",
            "client_completion_flags_authoritative": False,
        }
        return result

    cls.work_plan = work_plan
    cls.work_completion = work_completion
    cls.work_order_completion = work_order_completion
    cls.status = status
    cls._completion_judge_runtime_installed = True
