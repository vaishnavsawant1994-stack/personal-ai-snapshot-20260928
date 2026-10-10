from __future__ import annotations

import sqlite3

from future_intelligence.work_orchestration.attempt_parking import park_attempt, resume_parked_attempt
from future_intelligence.work_orchestration.attempts import WorkAttemptStatus
from future_intelligence.work_orchestration.durable_store import DurableWorkStore
from future_intelligence.work_orchestration.models import GoalSpec, ReadinessStatus, WorkOrder, WorkOrderStatus, WorkPlan, WorkPlanStatus


def test_work_contract_preserves_one_attempt_across_owner_approval_wait():
    con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row;store=DurableWorkStore(connection=con)
    goal=GoalSpec(id="g",title="g",objective="g",desired_outcome="done");order=WorkOrder(id="o",plan_id="p",title="o",objective="o",worker_type="tool",status=WorkOrderStatus.QUEUED);plan=WorkPlan(id="p",goal_id="g",version=1,summary="p",work_orders=(order,),readiness=ReadinessStatus.READY,status=WorkPlanStatus.READY)
    store.upsert_goal(goal);store.save_plan(plan);claim=store.claim_work_order("o",worker_id="worker",runtime_epoch=1,lease_seconds=60)
    park_attempt(store,claim.attempt.id,lease_token=claim.lease.lease_token,status=WorkAttemptStatus.WAITING_APPROVAL)
    resumed=resume_parked_attempt(store,claim.attempt.id,worker_id="worker",runtime_epoch=1)
    assert resumed.attempt.id==claim.attempt.id
    assert len(store.list_attempts("o"))==1
