from __future__ import annotations

import sqlite3

from automation.work_bridge import AutomationWorkBridge
from core.events import EventBus
from future_intelligence.work_orchestration.durable_store import DurableWorkStore


class Engine:
    def list(self):
        return [{"id":"a1","title":"Daily brief","next_run_at":"2026-10-10T08:00:00+00:00","last_run_at":None,"created_at":"2026-10-01T00:00:00+00:00"}]


def test_simple_scheduled_automation_uses_scheduled_occurrence_identity():
    con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row;work=DurableWorkStore(connection=con);events=EventBus();bridge=AutomationWorkBridge(engine=Engine(),work_store=work,events=events)
    one=bridge.record_automation("a1",event_type="completed");two=bridge.record_automation("a1",event_type="completed")
    assert one["work_order_id"]==two["work_order_id"]
    order=work.get_order(one["work_order_id"])
    assert order.resource_scope.metadata["occurrence_identity"]=="2026-10-10T08:00:00+00:00"
