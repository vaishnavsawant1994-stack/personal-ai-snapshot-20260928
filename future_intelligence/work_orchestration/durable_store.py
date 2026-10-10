from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .attempts import WorkAttemptStatus
from .durability import WorkDurabilityMixin
from .durability_migrations import migrate_work_durability_schema
from .intelligence_durability import IntelligenceDurabilityMixin
from .models import WorkOrderStatus
from .store import WorkStore


class DurableWorkStore(IntelligenceDurabilityMixin, WorkDurabilityMixin, WorkStore):
    """Canonical WorkStore plus additive execution/intelligence durability primitives."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        super().__init__(db_path, connection=connection)
        migrate_work_durability_schema(self.connection)

    def complete_verified_work_order(
        self,
        work_order_id: str,
        *,
        attempt_id: str,
        evidence_ids: Iterable[str],
        review_ref: str | None = None,
        actor: str,
    ) -> None:
        """Complete Work only after a succeeded attempt and explicit proof refs.

        This transition does not decide whether evidence is true; the caller must
        be a governed verification/review service. It freezes the proof references
        into the Work event history and refuses completion from RUNNING/FAILED or
        any attempt that has not already reached SUCCEEDED.
        """

        order_id = str(work_order_id or "").strip()
        attempt_key = str(attempt_id or "").strip()
        actor_key = str(actor or "").strip()
        proofs = tuple(dict.fromkeys(str(item).strip() for item in evidence_ids if str(item).strip()))
        if not order_id or not attempt_key or not actor_key:
            raise ValueError("work_order_id, attempt_id and actor are required")
        if not proofs:
            raise ValueError("at least one evidence reference is required")
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            attempt = self.connection.execute(
                "SELECT work_order_id, status FROM work_attempts WHERE id = ?",
                (attempt_key,),
            ).fetchone()
            if attempt is None or str(attempt["work_order_id"]) != order_id:
                raise ValueError("attempt does not belong to work order")
            if str(attempt["status"]) != WorkAttemptStatus.SUCCEEDED.value:
                raise ValueError("work attempt must be succeeded before completion")
            order = self.connection.execute(
                "SELECT status FROM work_orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            if order is None:
                raise KeyError(order_id)
            if str(order["status"]) == WorkOrderStatus.COMPLETED.value:
                self.connection.rollback()
                return
            if str(order["status"]) not in {
                WorkOrderStatus.VERIFYING.value,
                WorkOrderStatus.REVIEWING.value,
            }:
                raise ValueError("work order must be verifying or reviewing before completion")
            self._set_order_status_locked(order_id, WorkOrderStatus.COMPLETED, now=now)
            self._append_work_event_locked(
                order_id,
                "work.verified_completed",
                {
                    "actor": actor_key,
                    "evidence_ids": list(proofs),
                    "review_ref": str(review_ref or "") or None,
                },
                attempt_id=attempt_key,
                created_at=now,
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
