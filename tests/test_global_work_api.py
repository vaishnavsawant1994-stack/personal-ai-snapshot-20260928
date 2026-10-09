from __future__ import annotations

from server.global_work_api import GlobalWorkService


class _Store:
    def list(self, query="", status="all", sort="recent"):
        assert query == ""
        assert status == "all"
        assert sort == "recent"
        return [
            {"id": "p1", "name": "Launch Project", "status": "active"},
            {"id": "p2", "name": "Research Project", "status": "active"},
            {"id": "p3", "name": "No Work Yet", "status": "active"},
        ]


class _WorkStore:
    def project_plan_records(self, project_id):
        if project_id == "p1":
            return [{"source_p10_plan_id": "plan-1"}]
        if project_id == "p2":
            return [{"source_p10_plan_id": "plan-2"}]
        return []


class _Bridge:
    def __init__(self):
        self.work = _WorkStore()


class _Autonomy:
    def __init__(self):
        self._work_bridge = _Bridge()
        self.plans = {
            "plan-1": {
                "id": "plan-1",
                "state": "RUNNING",
                "replan_count": 1,
                "updated_at": "2026-10-09T09:00:00+00:00",
                "tasks": [
                    {"id": "research", "status": "RUNNING", "dependencies": []},
                    {"id": "verify", "status": "VERIFYING", "dependencies": ["research"]},
                    {"id": "publish", "status": "WAITING_APPROVAL", "dependencies": ["verify"]},
                ],
            },
            "plan-2": {
                "id": "plan-2",
                "state": "READY",
                "replan_count": 0,
                "updated_at": "2026-10-09T09:05:00+00:00",
                "tasks": [
                    {"id": "collect", "status": "COMPLETED", "dependencies": []},
                    {"id": "synthesize", "status": "WAITING", "dependencies": ["collect"]},
                    {"id": "recover", "status": "RECOVERY_REQUIRED", "dependencies": []},
                ],
            },
        }
        self.work_plans = {
            "plan-1": {
                "id": "work-1",
                "version": 2,
                "readiness": "ready",
                "work_orders": [
                    {"id": "wo-research", "title": "Research launch evidence", "worker_type": "research", "resource_scope": {"metadata": {"p10_task_id": "research"}}},
                    {"id": "wo-verify", "title": "Verify launch claims", "worker_type": "reviewer", "resource_scope": {"metadata": {"p10_task_id": "verify"}}},
                    {"id": "wo-publish", "title": "Publish approved launch", "worker_type": "communications", "resource_scope": {"metadata": {"p10_task_id": "publish", "requested_tool": "publish_content"}}},
                ],
            },
            "plan-2": {
                "id": "work-2",
                "version": 1,
                "readiness": "ready",
                "work_orders": [
                    {"id": "wo-collect", "title": "Collect sources", "worker_type": "research", "resource_scope": {"metadata": {"p10_task_id": "collect"}}},
                    {"id": "wo-synthesize", "title": "Synthesize findings", "worker_type": "data", "resource_scope": {"metadata": {"p10_task_id": "synthesize"}}},
                    {"id": "wo-recover", "title": "Recover browser step", "worker_type": "browser", "resource_scope": {"metadata": {"p10_task_id": "recover"}}},
                ],
            },
        }

    def plan(self, plan_id, *, owner_id):
        assert owner_id == "owner"
        return self.plans[plan_id]

    def work_plan(self, plan_id, *, owner_id):
        assert owner_id == "owner"
        return self.work_plans[plan_id]


def test_global_work_summary_aggregates_only_existing_canonical_runtime_state():
    autonomy = _Autonomy()
    service = GlobalWorkService({"advanced_autonomy": autonomy}, _Store())

    summary = service.summary()

    assert summary["authority"] == "read_only_projection"
    assert summary["execution_authority"] == "existing_p10_p6_runtime"
    assert summary["projects_total"] == 3
    assert summary["projects_with_work"] == 2
    assert summary["active_projects"] == 2
    assert summary["counts"]["active"] == 2
    assert summary["counts"]["verifying"] == 1
    assert summary["counts"]["waiting_approval"] == 1
    assert summary["counts"]["blocked"] == 1
    assert summary["counts"]["recovering"] == 1
    assert summary["counts"]["ready"] == 1
    assert summary["counts"]["completed"] == 1
    assert summary["counts"]["work_orders"] == 6
    assert summary["living"]["state"] == "approval"
    assert "waiting for your approval" in summary["living"]["detail"]

    # Priority order is actionable truth: approval first, then recovery/blockers,
    # then active/verifying work, then ready work, then completed history.
    assert summary["work_orders"][0]["task_id"] == "publish"
    assert summary["work_orders"][1]["task_id"] == "recover"
    synthesize = next(item for item in summary["work_orders"] if item["task_id"] == "synthesize")
    assert synthesize["ready"] is True
    assert synthesize["project_id"] == "p2"
    assert synthesize["work_order_id"] == "wo-synthesize"


def test_global_work_summary_has_no_execution_mutation_surface():
    service = GlobalWorkService({"advanced_autonomy": _Autonomy()}, _Store())

    for forbidden in ("execute", "approve", "pause", "resume", "cancel", "retry", "recover"):
        assert not hasattr(service, forbidden)
