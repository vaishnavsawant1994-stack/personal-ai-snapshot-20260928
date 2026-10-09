from __future__ import annotations

from types import SimpleNamespace

from evidence.models import Claim, ClaimState, Evidence, EvidenceProvenance, VerificationState
from evidence.store import EvidenceStore
from future_intelligence.work_orchestration.living_projection import LivingAgentWorkProjection
from future_intelligence.work_orchestration.memory_promotion import assess_usefulness
from future_intelligence.work_orchestration.models import (
    GoalSpec,
    ReadinessStatus,
    ResourceScope,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)
from future_intelligence.work_orchestration.store import WorkStore
from notifications.service import NotificationService
from qualification.work_performance import assert_measurement, measure, query_plan_uses_index


PROJECTS = 50
PLANS_PER_PROJECT = 2
ORDERS_PER_PLAN = 2


def _seed_work(path):
    store = WorkStore(path)
    source_ids = []
    order_ids = []
    for project_index in range(PROJECTS):
        project_id = f"project-{project_index:03d}"
        goal = GoalSpec(
            id=f"goal-{project_index:03d}",
            title=f"Project {project_index}",
            objective="Scale qualification",
            desired_outcome="Bounded canonical Work reads",
            project_id=project_id,
        )
        store.upsert_goal(goal, source_p10_goal_id=f"p10-goal-{project_index:03d}")
        previous_order = None
        for version in range(1, PLANS_PER_PROJECT + 1):
            plan_id = f"work-plan-{project_index:03d}-{version}"
            source = f"p10-plan-{project_index:03d}"
            orders = []
            for order_index in range(ORDERS_PER_PLAN):
                order_id = f"order-{project_index:03d}-{version}-{order_index}"
                dependencies = (previous_order,) if previous_order and order_index == 0 else ()
                order = WorkOrder(
                    id=order_id,
                    plan_id=plan_id,
                    project_id=project_id,
                    title=f"Work {project_index}-{version}-{order_index}",
                    objective="Keep product projections bounded",
                    worker_type="project",
                    status=WorkOrderStatus.RUNNING if order_index == 0 else WorkOrderStatus.WAITING,
                    dependencies=dependencies,
                    resource_scope=ResourceScope(metadata={"p10_task_id": f"task-{project_index}-{version}-{order_index}"}),
                )
                orders.append(order)
                order_ids.append(order_id)
                previous_order = order_id
            plan = WorkPlan(
                id=plan_id,
                goal_id=goal.id,
                version=version,
                summary=f"Scale plan {version}",
                project_id=project_id,
                work_orders=tuple(orders),
                readiness=ReadinessStatus.READY,
                status=WorkPlanStatus.RUNNING,
            )
            store.save_plan(plan, source_p10_plan_id=source)
            source_ids.append(source)
    return store, sorted(set(source_ids)), order_ids


def _seed_evidence(path, order_ids):
    store = EvidenceStore(path)
    for index, order_id in enumerate(order_ids):
        project_id = f"project-{index // (PLANS_PER_PROJECT * ORDERS_PER_PLAN):03d}"
        for item_index in range(3):
            evidence = Evidence(
                id=f"evidence-{index}-{item_index}",
                project_id=project_id,
                work_order_id=order_id,
                source_type="tool_result",
                source="qualified-scale-tool",
                subject="scale proof",
                observation=f"Project API uses stable route /api/v2/{index}/{item_index} for this bounded qualification fact.",
                provenance=EvidenceProvenance.TOOL_VERIFIED,
                verification_state=VerificationState.VERIFIED,
                confidence=1.0,
            )
            store.record_evidence(evidence)
        claim = Claim(
            id=f"claim-{index}",
            project_id=project_id,
            work_order_id=order_id,
            text=f"Project {project_id} uses a stable bounded qualification contract for order {index}.",
            state=ClaimState.VERIFIED,
            confidence=1.0,
        )
        store.create_claim(claim)
    return store


def test_v2_migrations_install_hot_read_indexes(tmp_path):
    work, _, order_ids = _seed_work(tmp_path / "work.sqlite3")
    evidence = _seed_evidence(tmp_path / "evidence.sqlite3", order_ids)

    work_versions = [row[0] for row in work.connection.execute("SELECT version FROM work_schema_migrations ORDER BY version")]
    evidence_versions = [row[0] for row in evidence.connection.execute("SELECT version FROM evidence_schema_migrations ORDER BY version")]
    assert work_versions == [1, 2]
    assert evidence_versions == [1, 2]

    assert query_plan_uses_index(
        work.connection,
        "SELECT payload_json FROM work_plans WHERE source_p10_plan_id=? ORDER BY version DESC,created_at DESC LIMIT 1",
        ("p10-plan-000",),
    )
    assert query_plan_uses_index(
        evidence.connection,
        "SELECT payload_json FROM claims WHERE work_order_id=? AND state=? ORDER BY updated_at DESC,id",
        (order_ids[0], "verified"),
    )
    assert query_plan_uses_index(
        evidence.connection,
        "SELECT payload_json FROM evidence WHERE work_order_id=? AND verification_state=? ORDER BY created_at,id",
        (order_ids[0], "verified"),
    )


def test_scale_read_paths_remain_bounded_at_50_projects_and_200_workorders(tmp_path):
    work, source_ids, order_ids = _seed_work(tmp_path / "work.sqlite3")
    evidence = _seed_evidence(tmp_path / "evidence.sqlite3", order_ids)

    measurements = [
        measure(
            "work.project_history_50",
            lambda: [work.project_plan_records(f"project-{index:03d}") for index in range(PROJECTS)],
            iterations=3,
            max_allowed_ms=1500,
        ),
        measure(
            "work.latest_plan_100",
            lambda: [work.latest_plan_for_source(source_ids[index % len(source_ids)]) for index in range(100)],
            iterations=3,
            max_allowed_ms=1200,
        ),
        measure(
            "evidence.work_order_100",
            lambda: [evidence.list_evidence(work_order_id=order_ids[index]) for index in range(100)],
            iterations=3,
            max_allowed_ms=1200,
        ),
        measure(
            "claims.work_order_100",
            lambda: [evidence.list_claims(work_order_id=order_ids[index]) for index in range(100)],
            iterations=3,
            max_allowed_ms=1200,
        ),
        measure(
            "memory.usefulness_1000",
            lambda: [assess_usefulness(f"Project API uses /api/v2/{index} and requires verified approval policy before publishing.") for index in range(1000)],
            iterations=3,
            max_allowed_ms=750,
        ),
    ]
    for item in measurements:
        assert_measurement(item)


def test_living_projection_and_notification_persistence_are_bounded(tmp_path):
    orders = [
        {
            "project_id": f"project-{index % PROJECTS:03d}",
            "project_name": f"Project {index % PROJECTS}",
            "work_order_id": f"order-{index}",
            "title": f"Work {index}",
            "worker_type": "coding" if index % 2 else "research",
            "status": "RUNNING" if index < 80 else "VERIFYING",
        }
        for index in range(200)
    ]
    work = {
        "task_counts": {"RUNNING": 80, "VERIFYING": 20, "WAITING": 100},
        "active_projects": PROJECTS,
        "work_orders": orders,
    }
    attention = {"counts": {"total": 0}, "items": []}
    projection = measure(
        "living.projection_500",
        lambda: [LivingAgentWorkProjection.project(work, attention) for _ in range(500)],
        iterations=3,
        max_allowed_ms=750,
    )
    assert_measurement(projection)

    notifications = NotificationService(
        tmp_path / "notifications.sqlite3",
        registry=SimpleNamespace(list=lambda: []),
        start_scheduler=False,
    )
    sequence = {"value": 0}

    def insert_batch():
        base = sequence["value"]
        for offset in range(100):
            key = f"scale-{base + offset}"
            notifications._insert("device-1", key, "work_completed", "Work completed", "Bounded scale qualification")
        sequence["value"] += 100

    inserted = measure(
        "notifications.insert_100",
        insert_batch,
        iterations=3,
        warmup=0,
        max_allowed_ms=2000,
    )
    assert_measurement(inserted)
    assert len(notifications.list("device-1", limit=200)) == 200
    notifications.close()
