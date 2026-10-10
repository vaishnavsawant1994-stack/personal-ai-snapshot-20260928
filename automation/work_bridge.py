from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from future_intelligence.work_orchestration.models import EvidenceContract, ExecutionBudget, GoalSpec, ReadinessStatus, ResourceScope, WorkOrder, WorkOrderStatus, WorkPlan, WorkPlanStatus


def _now() -> str:return datetime.now(timezone.utc).isoformat()
def _slug(*parts: str) -> str:return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:24]
_STATUS={"started":WorkOrderStatus.RUNNING,"step.completed":WorkOrderStatus.RUNNING,"approval_required":WorkOrderStatus.WAITING_APPROVAL,"recovery_required":WorkOrderStatus.RECOVERY_REQUIRED,"failed":WorkOrderStatus.FAILED,"cancelled":WorkOrderStatus.CANCELLED,"budget_exceeded":WorkOrderStatus.BLOCKED,"completed":WorkOrderStatus.COMPLETED,"skipped":WorkOrderStatus.CANCELLED}


class AutomationWorkBridge:
    """Stable legacy automation/workflow occurrence -> canonical Work projection."""
    mode="canonical_occurrence_projection"
    def __init__(self,*,engine,work_store,events)->None:
        self.engine=engine;self.work=work_store;self.events=events;self._subscriptions=[]
        for suffix in ("started","step.completed","approval_required","recovery_required","failed","cancelled","budget_exceeded","completed"):
            self._subscriptions.append(events.subscribe(f"workflow.{suffix}",self._on_workflow_event))
        for suffix in ("completed","approval_required","failed","skipped"):
            self._subscriptions.append(events.subscribe(f"automation.{suffix}",self._on_automation_event))
    def close(self)->None:
        for unsubscribe in self._subscriptions:
            try:unsubscribe()
            except Exception:pass
        self._subscriptions.clear()
    def _run(self,run_id):
        try:return dict(self.engine._run(run_id))
        except Exception:return {"id":run_id}
    def _workflow(self,workflow_id):
        try:return dict(self.engine.workflow(workflow_id))
        except Exception:return {"id":workflow_id,"title":"Automation workflow","trigger":{},"steps":[]}
    def _automation(self,automation_id):
        try:return next((dict(item) for item in self.engine.list() if str(item.get("id"))==str(automation_id)),{"id":automation_id})
        except Exception:return {"id":automation_id}
    @staticmethod
    def _suffix(event_name,prefix):return str(event_name).removeprefix(prefix)
    def _on_workflow_event(self,event):
        run_id=str(event.get("run_id") or "").strip();workflow_id=str(event.get("workflow_id") or "").strip()
        if not run_id or not workflow_id:return
        try:self.record_workflow(run_id,workflow_id,event_type=self._suffix(event.get("event"),"workflow."))
        except Exception as exc:self.events.emit("automation.work_projection_failed",run_id=run_id,workflow_id=workflow_id,error_type=type(exc).__name__)
    def _on_automation_event(self,event):
        automation_id=str(event.get("automation_id") or "").strip()
        if not automation_id:return
        try:self.record_automation(automation_id,event_type=self._suffix(event.get("event"),"automation."))
        except Exception as exc:self.events.emit("automation.work_projection_failed",automation_id=automation_id,error_type=type(exc).__name__)
    def _save(self,*,namespace,definition_id,run_id,occurrence,title,trigger_type,event_type,stamp):
        suffix=_slug(namespace,definition_id,occurrence);goal_id=f"goal-auto-{suffix}";plan_id=f"plan-auto-{suffix}";order_id=f"work-auto-{suffix}";status=_STATUS.get(event_type,WorkOrderStatus.RUNNING);objective=f"Run automation: {title}"
        scope=ResourceScope(metadata={"automation_kind":namespace,"automation_definition_id":definition_id,"automation_run_id":run_id,"occurrence_identity":occurrence,"trigger_type":trigger_type,"authority":"automation_engine"})
        goal=GoalSpec(id=goal_id,title=title,objective=objective,desired_outcome=f"Complete governed automation occurrence {occurrence}",success_criteria=("automation occurrence reaches its governed terminal state",),resource_scope=scope,budget=ExecutionBudget(max_attempts=1),approval_policy={"authority":"existing_automation_governance"},created_from="automation_occurrence",created_at=stamp,updated_at=_now())
        order=WorkOrder(id=order_id,plan_id=plan_id,title=title,objective=objective,worker_type="automation",status=status,resource_scope=scope,expected_output="governed automation result",evidence_contract=EvidenceContract(require_review=False),verification_strategy={"authority":"automation_engine","terminal_event":event_type},approval_policy={"authority":"automation_engine"},retry_policy={"authority":"automation_budget_manager"},workflow_id=definition_id,workflow_run_id=run_id,created_at=stamp,updated_at=_now())
        failed=status in {WorkOrderStatus.FAILED,WorkOrderStatus.BLOCKED,WorkOrderStatus.RECOVERY_REQUIRED}
        plan=WorkPlan(id=plan_id,goal_id=goal_id,version=1,summary=objective,work_orders=(order,),critic={"projection":"automation_occurrence","execution_authority":"automation_engine","canonical_work_identity":True},readiness=ReadinessStatus.HOLD if failed else ReadinessStatus.READY,status=WorkPlanStatus.COMPLETED if status is WorkOrderStatus.COMPLETED else WorkPlanStatus.CANCELLED if status is WorkOrderStatus.CANCELLED else WorkPlanStatus.HOLD if failed else WorkPlanStatus.RUNNING,created_at=stamp)
        self.work.upsert_goal(goal);self.work.save_plan(plan)
        try:self.work.append_work_event(order_id,f"automation.{event_type}",{"definition_id":definition_id,"run_id":run_id,"occurrence_identity":occurrence,"kind":namespace})
        except Exception:pass
        self.events.emit("automation.work_projected",automation_id=definition_id,run_id=run_id,work_order_id=order_id,status=status.value,kind=namespace)
        return {"goal_id":goal_id,"plan_id":plan_id,"work_order_id":order_id}
    def record_workflow(self,run_id,workflow_id,*,event_type):
        run=self._run(run_id);workflow=self._workflow(workflow_id);occurrence=str(run.get("idempotency_key") or run.get("id") or "unknown")[:160];stamp=str(run.get("started_at") or _now())
        return self._save(namespace="workflow",definition_id=workflow_id,run_id=run_id,occurrence=occurrence,title=str(workflow.get("title") or "Automation workflow")[:160],trigger_type=str((workflow.get("trigger") or {}).get("type") or "unknown"),event_type=event_type,stamp=stamp)
    def record_automation(self,automation_id,*,event_type):
        item=self._automation(automation_id);occurrence=str(item.get("next_run_at") or item.get("last_run_at") or item.get("created_at") or automation_id)[:160];stamp=str(item.get("last_run_at") or item.get("next_run_at") or _now())
        return self._save(namespace="scheduled",definition_id=automation_id,run_id=f"automation:{automation_id}:{occurrence}",occurrence=occurrence,title=str(item.get("title") or "Scheduled automation")[:160],trigger_type="schedule",event_type=event_type,stamp=stamp)
    # Backward-compatible test/helper alias.
    def record(self,run_id,workflow_id,*,event_type):return self.record_workflow(run_id,workflow_id,event_type=event_type)
