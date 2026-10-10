from __future__ import annotations

from .leases import WorkClaim


class WorkDispatcher:
    """Thin canonical dispatcher over WorkStore lease/attempt primitives.

    Parallelism is achieved by claiming several independently-ready work orders;
    execution authority remains with the existing governed worker/tool runtime.
    """

    def __init__(self, store) -> None:
        self.store = store

    def claim(
        self,
        work_order_id: str,
        *,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 60,
        execution_id: str | None = None,
    ) -> WorkClaim | None:
        if not self.store.dependencies_ready(work_order_id):
            return None
        return self.store.claim_work_order(
            work_order_id,
            worker_id=worker_id,
            runtime_epoch=runtime_epoch,
            lease_seconds=lease_seconds,
            execution_id=execution_id,
        )

    def _ready_order_ids(self) -> tuple[str, ...]:
        rows = self.store.connection.execute(
            """
            SELECT id
            FROM work_orders
            WHERE status IN ('queued', 'retrying')
            ORDER BY updated_at, id
            """
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def claim_first_ready(
        self,
        *,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 60,
    ) -> WorkClaim | None:
        for work_order_id in self._ready_order_ids():
            claimed = self.claim(
                work_order_id,
                worker_id=worker_id,
                runtime_epoch=runtime_epoch,
                lease_seconds=lease_seconds,
            )
            if claimed is not None:
                return claimed
        return None

    def claim_ready_batch(
        self,
        *,
        worker_id: str,
        runtime_epoch: int,
        max_claims: int = 4,
        lease_seconds: int = 60,
        execution_id_prefix: str | None = None,
    ) -> tuple[WorkClaim, ...]:
        """Claim a bounded set of currently independent work orders.

        Each individual claim is fenced by WorkStore's BEGIN IMMEDIATE lease
        transaction and dependency check, so concurrent dispatchers cannot
        double-execute a work order. No tool/model work is performed here.
        """
        limit = max(1, min(32, int(max_claims)))
        claims: list[WorkClaim] = []
        for work_order_id in self._ready_order_ids():
            if len(claims) >= limit:
                break
            execution_id = (
                f"{execution_id_prefix}:{work_order_id}"
                if execution_id_prefix
                else None
            )
            claimed = self.claim(
                work_order_id,
                worker_id=worker_id,
                runtime_epoch=runtime_epoch,
                lease_seconds=lease_seconds,
                execution_id=execution_id,
            )
            if claimed is not None:
                claims.append(claimed)
        return tuple(claims)
