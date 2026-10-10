from __future__ import annotations

from types import SimpleNamespace

from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore
from future_intelligence.work_orchestration.models import WorkOrderStatus


class Work:
    def __init__(self, project_id, orders):
        self.project_id = project_id
        self.orders = {order.id: order for order in orders}
        self.plan = SimpleNamespace(work_orders=tuple(orders))

    def latest_project_plan_record(self, project_id):
        if project_id != self.project_id:
            return None
        return {"plan": self.plan, "source_p10_plan_id": "p10-plan"}

    def get_order(self, order_id):
        return self.orders.get(order_id)


def order(order_id, project_id, worker_type, status=WorkOrderStatus.QUEUED, capabilities=()):
    return SimpleNamespace(
        id=order_id,
        project_id=project_id,
        worker_type=worker_type,
        status=status,
        allowed_capabilities=tuple(capabilities),
    )


def workforce(tmp_path, work):
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    return AgentWorkforceService(store, work_store=work)


def test_canonical_coding_and_research_orders_get_project_bound_specialists(tmp_path):
    work = Work(
        "project-a",
        [
            order("code-1", "project-a", "coding", WorkOrderStatus.RUNNING),
            order("research-1", "project-a", "research", WorkOrderStatus.QUEUED),
        ],
    )
    service = workforce(tmp_path, work)
    result = service.reconcile_project_work("project-a")
    team = service.project_team("project-a")
    roles = [row["role"] for row in team]
    assert roles.count("project_manager") == 1
    assert roles.count("coding") == 1
    assert roles.count("research") == 1
    assert len(result["assignments"]) == 2
    assert result["execution_authority"] is False
    code = next(row for row in team if row["role"] == "coding")
    research = next(row for row in team if row["role"] == "research")
    assert code["current_work_order_id"] == "code-1"
    assert code["state"] == "working"
    assert research["current_work_order_id"] == "research-1"
    assert research["state"] == "assigned"


def test_reconciliation_is_idempotent_and_does_not_duplicate_workers_or_assignments(tmp_path):
    work = Work("project-a", [order("code-1", "project-a", "coding")])
    service = workforce(tmp_path, work)
    first = service.reconcile_project_work("project-a")
    second = service.reconcile_project_work("project-a")
    assert first["assignments"][0]["id"] == second["assignments"][0]["id"]
    coding = service.store.get_template_by_slug("coding")
    assert len(service.store.list_instances(template_id=coding["id"], project_id="project-a")) == 1
    count = service.store.connection.execute(
        "SELECT COUNT(*) FROM agent_assignments WHERE work_order_id='code-1'"
    ).fetchone()[0]
    assert count == 1


def test_tool_order_maps_only_when_capabilities_are_unambiguous(tmp_path):
    work = Work(
        "project-a",
        [
            order("browse-1", "project-a", "tool", capabilities=("browser", "web")),
            order("unknown-1", "project-a", "tool", capabilities=("unclassified_capability",)),
        ],
    )
    service = workforce(tmp_path, work)
    result = service.reconcile_project_work("project-a")
    assert [row["work_order_id"] for row in result["assignments"]] == ["browse-1"]
    assert result["unmapped"] == ["unknown-1"]
    browser = service.store.get_template_by_slug("browser")
    assert len(service.store.list_instances(template_id=browser["id"], project_id="project-a")) == 1


def test_terminal_canonical_work_releases_instance_without_granting_completion_authority(tmp_path):
    running = order("code-1", "project-a", "coding", WorkOrderStatus.RUNNING)
    work = Work("project-a", [running])
    service = workforce(tmp_path, work)
    first = service.reconcile_project_work("project-a")
    assignment_id = first["assignments"][0]["id"]
    instance_id = first["assignments"][0]["instance_id"]

    running.status = WorkOrderStatus.COMPLETED
    second = service.reconcile_project_work("project-a")
    assignment = service.store.get_assignment(assignment_id)
    instance = service.store.get_instance(instance_id)
    assert assignment["status"] == "completed"
    assert assignment["completed_at"]
    assert instance["state"] == "idle"
    assert instance["current_work_order_id"] is None
    assert second["execution_authority"] is False


def test_manual_assign_uses_canonical_get_order_and_rejects_cross_project_order(tmp_path):
    work = Work("project-a", [order("code-1", "project-a", "coding")])
    service = workforce(tmp_path, work)
    coding = service.store.get_template_by_slug("coding")
    worker = service.create_instance(coding["id"], project_id="project-a")
    assignment = service.assign(worker["id"], project_id="project-a", work_order_id="code-1")
    assert assignment["work_order_id"] == "code-1"

    other = service.create_instance(coding["id"], project_id="project-b")
    try:
        service.assign(other["id"], project_id="project-b", work_order_id="code-1")
        raise AssertionError("cross-project WorkOrder assignment should fail")
    except PermissionError:
        pass
