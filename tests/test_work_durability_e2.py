from __future__ import annotations

from datetime import datetime, timezone

import pytest

from future_intelligence.work_orchestration.attempts import WorkAttemptStatus
from future_intelligence.work_orchestration.dispatcher import WorkDispatcher
from future_intelligence.work_orchestration.durable_store import DurableWorkStore
from future_intelligence.work_orchestration.failure_policy import (
    FailureClass,
    RetryDisposition,
    WorkFailure,
)
from future_intelligence.work_orchestration.models import (
    GoalSpec,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
)
from future_intelligence.work_orchestration.recovery import RecoveryReason
from future_intelligence.work_orchestration.workspace import (
    WorkspaceState,
    WorkWorkspace,
)


def _seed(store: DurableWorkStore, *, with_dependency: bool = False) -> tuple[WorkOrder, WorkOrder | None]:
    goal = GoalSpec(
        id="goal-1",
        title="Durable work",
        objective="Exercise durable execution",
        desired_outcome="Verified durable lifecycle",
    )
    store.upsert_goal(goal)
    dependency = None
    dependencies = ()
    orders = []
    if with_dependency:
        dependency = WorkOrder(
            id="work-dependency",
            plan_id="plan-1",
            title="Dependency",
            objective="Finish first",
            worker_type="test",
            status=WorkOrderStatus.QUEUED,
        )
        dependencies = (dependency.id,)
        orders.append(dependency)
    order = WorkOrder(
        id="work-1",
        plan_id="plan-1",
        title="Main work",
        objective="Execute safely",
        worker_type="test",
        status=WorkOrderStatus.QUEUED,
        dependencies=dependencies,
    )
    orders.append(order)
    store.save_plan(
        WorkPlan(
            id="plan-1",
            goal_id=goal.id,
            version=1,
            summary="Durability plan",
            work_orders=tuple(orders),
        )
    )
    return order, dependency


def test_schema_v3_and_single_owner_claim(tmp_path):
    db = tmp_path / "work.db"
    with DurableWorkStore(db) as first:
        order, _ = _seed(first)
        versions = {
            int(row[0])
            for row in first.connection.execute("SELECT version FROM work_schema_migrations")
        }
        assert 3 in versions

        claim = first.claim_work_order(
            order.id,
            worker_id="worker-a",
            runtime_epoch=7,
            lease_seconds=60,
            execution_id="exec-1",
        )
        assert claim is not None
        assert claim.attempt.attempt_number == 1
        assert first.get_order(order.id).status is WorkOrderStatus.RUNNING

        with DurableWorkStore(db) as second:
            assert (
                second.claim_work_order(
                    order.id,
                    worker_id="worker-b",
                    runtime_epoch=7,
                )
                is None
            )

        renewed = first.renew_lease(
            order.id,
            lease_token=claim.lease.lease_token,
            worker_id="worker-a",
            runtime_epoch=7,
        )
        assert renewed is not None


def test_expired_lease_becomes_recovery_required_not_retry(tmp_path):
    db = tmp_path / "work.db"
    with DurableWorkStore(db) as store:
        order, _ = _seed(store)
        claim = store.claim_work_order(
            order.id,
            worker_id="worker-a",
            runtime_epoch=1,
        )
        assert claim is not None
        store.connection.execute(
            "UPDATE work_leases SET expires_at = ? WHERE work_order_id = ?",
            ("2000-01-01T00:00:00+00:00", order.id),
        )
        store.connection.commit()

        assert (
            store.claim_work_order(
                order.id,
                worker_id="worker-b",
                runtime_epoch=1,
            )
            is None
        )
        assert store.get_lease(order.id) is None
        attempt = store.get_attempt(claim.attempt.id)
        assert attempt.status is WorkAttemptStatus.RECOVERY_REQUIRED
        assert attempt.failure_class == FailureClass.UNKNOWN_EFFECT.value
        assert attempt.retry_disposition == RetryDisposition.RECOVERY_REQUIRED.value
        assert store.get_order(order.id).status is WorkOrderStatus.RECOVERY_REQUIRED

        with pytest.raises(ValueError, match="recovery-required"):
            store.retry_work_order(
                order.id,
                actor="worker-b",
                reason="blind retry must be blocked",
            )


def test_failure_retry_creates_new_attempt_and_preserves_parent_lineage(tmp_path):
    with DurableWorkStore(tmp_path / "work.db") as store:
        order, _ = _seed(store)
        first = store.claim_work_order(
            order.id,
            worker_id="worker-a",
            runtime_epoch=2,
        )
        assert first is not None
        failed = store.finish_attempt(
            first.attempt.id,
            lease_token=first.lease.lease_token,
            status=WorkAttemptStatus.FAILED,
            failure=WorkFailure(
                failure_class=FailureClass.NETWORK,
                code="network_reset",
            ),
        )
        assert failed.retry_disposition == RetryDisposition.AUTO_RETRY.value
        assert store.get_order(order.id).status is WorkOrderStatus.FAILED

        store.retry_work_order(
            order.id,
            actor="recovery-worker",
            reason="known transient network failure",
        )
        second = store.claim_work_order(
            order.id,
            worker_id="worker-b",
            runtime_epoch=2,
        )
        assert second is not None
        assert second.attempt.attempt_number == 2
        assert second.attempt.parent_attempt_id == first.attempt.id
        assert [item.id for item in store.list_attempts(order.id)] == [
            first.attempt.id,
            second.attempt.id,
        ]


def test_dispatcher_respects_dependencies_and_workspace_is_portable(tmp_path):
    with DurableWorkStore(tmp_path / "work.db") as store:
        order, dependency = _seed(store, with_dependency=True)
        assert dependency is not None
        dispatcher = WorkDispatcher(store)

        assert (
            dispatcher.claim(
                order.id,
                worker_id="worker-main",
                runtime_epoch=1,
            )
            is None
        )

        dep_claim = dispatcher.claim(
            dependency.id,
            worker_id="worker-dep",
            runtime_epoch=1,
        )
        assert dep_claim is not None
        store.finish_attempt(
            dep_claim.attempt.id,
            lease_token=dep_claim.lease.lease_token,
            status=WorkAttemptStatus.SUCCEEDED,
        )
        assert not store.dependencies_ready(order.id)

        now = datetime.now(timezone.utc).isoformat()
        workspace = WorkWorkspace(
            id="workspace-1",
            work_order_id=dependency.id,
            attempt_id=dep_claim.attempt.id,
            repository="vaishnavsawant1994-stack/vishnu",
            base_revision="abc123",
            branch_ref="agent/test",
            state=WorkspaceState.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        store.register_workspace(workspace)
        persisted = store.get_workspace(workspace.id)
        assert persisted == workspace
        assert "local_path" not in dict(persisted.metadata)


def test_unknown_effect_can_only_retry_with_explicit_reconciliation_override(tmp_path):
    with DurableWorkStore(tmp_path / "work.db") as store:
        order, _ = _seed(store)
        claim = store.claim_work_order(
            order.id,
            worker_id="worker-a",
            runtime_epoch=3,
        )
        assert claim is not None
        store.mark_recovery_required(
            order.id,
            reason=RecoveryReason.UNKNOWN_EFFECT,
            attempt_id=claim.attempt.id,
        )

        with pytest.raises(ValueError, match="reconciliation override"):
            store.retry_work_order(
                order.id,
                actor="owner",
                reason="try again",
            )

        store.retry_work_order(
            order.id,
            actor="owner",
            reason="remote side reconciled; safe to retry",
            allow_recovery_override=True,
        )
        assert store.get_order(order.id).status is WorkOrderStatus.RETRYING
