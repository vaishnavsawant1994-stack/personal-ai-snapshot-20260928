from __future__ import annotations

from .leases import WorkClaim


class WorkDispatcher:
    """Thin canonical dispatcher over WorkStore lease/attempt primitives."""

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

    def claim_first_ready(
        self,
        *,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 60,
    ) -> WorkClaim | None:
        rows = self.store.connection.execute(
            """
            SELECT id
            FROM work_orders
            WHERE status IN ('queued', 'retrying')
            ORDER BY updated_at, id
            """
        ).fetchall()
        for row in rows:
            claimed = self.claim(
                str(row[0]),
                worker_id=worker_id,
                runtime_epoch=runtime_epoch,
                lease_seconds=lease_seconds,
            )
            if claimed is not None:
                return claimed
        return None
