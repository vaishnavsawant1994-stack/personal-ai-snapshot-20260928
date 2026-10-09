from __future__ import annotations

from approvals.projection import ApprovalsProjection
from evidence.models import Claim, ClaimState, Evidence, EvidenceProvenance, VerificationState
from evidence.store import EvidenceStore
from future_intelligence.work_orchestration.attention import WorkAttentionService
from future_intelligence.work_orchestration.context_pack import ContextPackBuilder
from future_intelligence.work_orchestration.living_projection import LivingAgentWorkProjection
from future_intelligence.work_orchestration.models import (
    ExecutionBudget,
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)
from future_intelligence.work_orchestration.store import WorkStore
from projects.autonomy_modes import ProjectAutonomyModeStore
from projects.store import ProjectStore
from security.approvals import ApprovalManager


class _ScopedProvider:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def search(self, query, *, limit=10, project_id=None):
        self.calls.append((query, project_id))
        return [row for row in self.rows if row.get("project_id") == project_id][:limit]


class _FakeAutonomy:
    def __init__(self, plan_tasks):
        self.plan_tasks = plan_tasks

    def plan(self, plan_id, *, owner_id="owner"):
        return {"id": plan_id, "tasks": [dict(item) for item in self.plan_tasks[plan_id]]}

    def work_plan(self, plan_id, *, owner_id="owner"):
        return {"id": f"work-{plan_id}", "goal_id": f"goal-{plan_id}", "version": 1}


class _FakeWorkService:
    def __init__(self, snapshot, autonomy):
        self._snapshot = snapshot
        self._resolved_autonomy = autonomy

    def summary(self, *, work_order_limit=500):
        return {
            **self._snapshot,
            "work_orders": [dict(item) for item in self._snapshot.get("work_orders", [])[:work_order_limit]],
        }

    def _autonomy(self):
        return self._resolved_autonomy


def _work_order(plan_id, project_id, suffix, *, worker, status, repo, cost):
    return WorkOrder(
        id=f"order-{suffix}",
        plan_id=plan_id,
        project_id=project_id,
        title=f"{suffix} work",
        objective=f"Keep {suffix} isolated",
        worker_type=worker,
        status=status,
        allowed_capabilities=(worker,),
        resource_scope=ResourceScope(
            allowed_repositories=(repo,),
            metadata={"p10_task_id": f"task-{suffix}", "project_marker": suffix},
        ),
        cost_budget=cost,
    )


def _save_project_work(store, project_id, suffix, *, worker, status, repo, cost):
    goal = GoalSpec(
        id=f"goal-{suffix}",
        title=f"{suffix} goal",
        objective=f"Run {suffix}",
        desired_outcome=f"Complete {suffix} independently",
        project_id=project_id,
        budget=ExecutionBudget(max_cost=cost),
    )
    order = _work_order(
        f"plan-{suffix}", project_id, suffix, worker=worker, status=status, repo=repo, cost=cost
    )
    plan = WorkPlan(
        id=f"plan-{suffix}",
        goal_id=goal.id,
        version=1,
        summary=f"{suffix} plan",
        project_id=project_id,
        work_orders=(order,),
        readiness=ReadinessStatus.READY,
        status=WorkPlanStatus.RUNNING,
    )
    store.upsert_goal(goal, source_p10_goal_id=f"p10-goal-{suffix}")
    store.save_plan(plan, source_p10_plan_id=f"p10-plan-{suffix}")
    return goal, order, plan


def test_context_packs_and_evidence_are_strictly_project_scoped(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.sqlite3")
    project_a = project_store.create(name="Project A", goal="A only")
    project_b = project_store.create(name="Project B", goal="B only")

    evidence = EvidenceStore(tmp_path / "evidence.sqlite3")
    for project, marker in ((project_a, "A"), (project_b, "B")):
        evidence.record_evidence(
            Evidence(
                id=f"ev-{marker}",
                project_id=project["id"],
                work_order_id=f"order-{marker}",
                source_type="tool_result",
                source=f"tool-{marker}",
                subject=f"{marker} proof",
                observation=f"private observation for project {marker}",
                provenance=EvidenceProvenance.TOOL_VERIFIED,
                verification_state=VerificationState.VERIFIED,
                confidence=1.0,
            )
        )

    memory = _ScopedProvider(
        [
            {"id": "mem-A", "project_id": project_a["id"], "content": "memory A"},
            {"id": "mem-B", "project_id": project_b["id"], "content": "memory B"},
        ]
    )
    knowledge = _ScopedProvider(
        [
            {"chunk_id": "kn-A", "project_id": project_a["id"], "excerpt": "knowledge A"},
            {"chunk_id": "kn-B", "project_id": project_b["id"], "excerpt": "knowledge B"},
        ]
    )
    builder = ContextPackBuilder(
        memory=memory,
        knowledge=knowledge,
        project_store=project_store,
        evidence_store=evidence,
    )

    pack_a = builder.build(goal_id="goal-A", query="shared query", project_id=project_a["id"])
    pack_b = builder.build(goal_id="goal-B", query="shared query", project_id=project_b["id"])

    text_a = pack_a.prompt_text()
    text_b = pack_b.prompt_text()
    assert "memory A" in text_a and "memory B" not in text_a
    assert "knowledge A" in text_a and "knowledge B" not in text_a
    assert "private observation for project A" in text_a
    assert "private observation for project B" not in text_a
    assert "memory B" in text_b and "memory A" not in text_b
    assert "knowledge B" in text_b and "knowledge A" not in text_b
    assert "private observation for project B" in text_b
    assert "private observation for project A" not in text_b
    assert memory.calls[-2:] == [("shared query", project_a["id"]), ("shared query", project_b["id"])]


def test_work_claim_scope_budget_and_autonomy_mode_do_not_leak_between_projects(tmp_path):
    project_store = ProjectStore(tmp_path / "projects.sqlite3")
    project_a = project_store.create(name="Project A", goal="coding")
    project_b = project_store.create(name="Project B", goal="research")

    work = WorkStore(tmp_path / "work.sqlite3")
    _, order_a, plan_a = _save_project_work(
        work, project_a["id"], "A", worker="coding", status=WorkOrderStatus.RUNNING,
        repo="org/repo-a", cost=10.0,
    )
    _, order_b, plan_b = _save_project_work(
        work, project_b["id"], "B", worker="research", status=WorkOrderStatus.VERIFYING,
        repo="org/repo-b", cost=20.0,
    )

    assert [row["plan"].id for row in work.project_plan_records(project_a["id"])] == [plan_a.id]
    assert [row["plan"].id for row in work.project_plan_records(project_b["id"])] == [plan_b.id]
    assert work.get_order(order_a.id).resource_scope.allowed_repositories == ("org/repo-a",)
    assert work.get_order(order_b.id).resource_scope.allowed_repositories == ("org/repo-b",)
    assert work.get_order(order_a.id).cost_budget == 10.0
    assert work.get_order(order_b.id).cost_budget == 20.0

    evidence = EvidenceStore(tmp_path / "evidence.sqlite3")
    claim_a = Claim("claim-A", "A result", project_id=project_a["id"], work_order_id=order_a.id, state=ClaimState.VERIFIED, confidence=1.0)
    claim_b = Claim("claim-B", "B result", project_id=project_b["id"], work_order_id=order_b.id, state=ClaimState.VERIFIED, confidence=1.0)
    evidence.create_claim(claim_a)
    evidence.create_claim(claim_b)
    assert [item.id for item in evidence.list_claims(project_id=project_a["id"])] == [claim_a.id]
    assert [item.id for item in evidence.list_claims(project_id=project_b["id"])] == [claim_b.id]

    modes = ProjectAutonomyModeStore(project_store.path)
    modes.set(project_a["id"], "active")
    modes.set(project_b["id"], "shadow")
    reloaded = ProjectAutonomyModeStore(project_store.path)
    assert reloaded.get(project_a["id"]).mode.value == "active"
    assert reloaded.get(project_b["id"]).mode.value == "shadow"


def test_approval_and_recovery_attention_remain_bound_to_the_correct_projects(tmp_path):
    work_orders = [
        {"project_id": "project-A", "project_name": "Project A", "plan_id": "plan-A", "task_id": "task-A", "work_order_id": "order-A", "title": "Code A", "worker_type": "coding", "status": "RUNNING"},
        {"project_id": "project-B", "project_name": "Project B", "plan_id": "plan-B", "task_id": "task-B", "work_order_id": "order-B", "title": "Research B", "worker_type": "research", "status": "RUNNING"},
        {"project_id": "project-C", "project_name": "Project C", "plan_id": "plan-C", "task_id": "task-C", "work_order_id": "order-C", "title": "Send C", "worker_type": "communications", "status": "WAITING_APPROVAL"},
        {"project_id": "project-D", "project_name": "Project D", "plan_id": "plan-D", "task_id": "task-D", "work_order_id": "order-D", "title": "Verify D", "worker_type": "project", "status": "VERIFYING"},
        {"project_id": "project-E", "project_name": "Project E", "plan_id": "plan-E", "task_id": "task-E", "work_order_id": "order-E", "title": "Recover E", "worker_type": "browser", "status": "RECOVERY_REQUIRED"},
    ]
    projects = [{"project_id": f"project-{suffix}", "project_name": f"Project {suffix}", "plan_id": f"plan-{suffix}"} for suffix in "ABCDE"]
    task_map = {
        f"plan-{suffix}": [
            {
                "id": f"task-{suffix}",
                "status": work_orders[index]["status"],
                "operation_id": f"exec-{suffix}",
            }
        ]
        for index, suffix in enumerate("ABCDE")
    }
    snapshot = {"projects": projects, "work_orders": work_orders}
    fake_work = _FakeWorkService(snapshot, _FakeAutonomy(task_map))

    approvals = ApprovalManager(ttl_seconds=3600, path=tmp_path / "approvals.sqlite3")
    ticket = approvals.create(
        "exec-C",
        "gmail.send",
        {"message": "C only"},
        owner_id="owner",
        device_id="device-1",
        session_id="session-1",
        destination="mailto:c@example.test",
    )
    service = WorkAttentionService(
        {},
        None,
        work_service=fake_work,
        approvals_projection=ApprovalsProjection(approvals),
    )
    attention = service.summary(owner_id="owner", device_id="device-1", session_id="session-1")

    approval_item = next(item for item in attention["items"] if item["kind"] == "approval_required")
    recovery_item = next(item for item in attention["items"] if item["kind"] == "recovery_required")
    assert approval_item["approval_id"] == ticket.id
    assert approval_item["project_id"] == "project-C"
    assert approval_item["work_order_id"] == "order-C"
    assert recovery_item["project_id"] == "project-E"
    assert recovery_item["work_order_id"] == "order-E"
    assert all(item.get("project_id") not in {"project-A", "project-B"} for item in attention["items"])

    work_snapshot = {
        "task_counts": {"RUNNING": 2, "WAITING_APPROVAL": 1, "VERIFYING": 1, "RECOVERY_REQUIRED": 1},
        "active_projects": 5,
        "work_orders": work_orders,
    }
    living = LivingAgentWorkProjection.project(work_snapshot, attention)
    assert living["authority"] == "presentation_only"
    assert living["state"] == "waiting_approval"
    assert living["attention_count"] == 2
    assert living["approval_count"] == 1
    assert living["recovery_count"] == 1
    assert living["projects_active"] == 5
    assert living["current_project_name"] == "Project C"
