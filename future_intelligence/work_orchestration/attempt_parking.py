from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .attempts import WorkAttemptStatus
from .durability import LeaseLostError
from .leases import WorkClaim
from .models import WorkOrderStatus


def _now():
    return datetime.now(timezone.utc)


def park_attempt(store, attempt_id: str, *, lease_token: str, status: WorkAttemptStatus, metadata: dict | None = None):
    if status not in {WorkAttemptStatus.WAITING_APPROVAL, WorkAttemptStatus.WAITING_RESOURCE}:
        raise ValueError("attempt can only be parked for approval or a resource")
    stamp = _now().isoformat()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        row = store.connection.execute(
            "SELECT a.*, l.lease_token FROM work_attempts a JOIN work_leases l ON l.attempt_id=a.id WHERE a.id=?",
            (str(attempt_id),),
        ).fetchone()
        if row is None or str(row["lease_token"]) != str(lease_token):
            raise LeaseLostError(attempt_id)
        if str(row["status"]) != WorkAttemptStatus.RUNNING.value:
            raise ValueError("attempt is not running")
        work_order_id = str(row["work_order_id"])
        merged = json.loads(row["metadata_json"])
        merged.update(metadata or {})
        store.connection.execute(
            "UPDATE work_attempts SET status=?, metadata_json=? WHERE id=?",
            (status.value, json.dumps(merged, sort_keys=True, separators=(",", ":")), str(attempt_id)),
        )
        store.connection.execute("DELETE FROM work_leases WHERE attempt_id=?", (str(attempt_id),))
        order_status = WorkOrderStatus.WAITING_APPROVAL if status is WorkAttemptStatus.WAITING_APPROVAL else WorkOrderStatus.WAITING_RESOURCE
        store._set_order_status_locked(work_order_id, order_status, now=stamp)
        store._append_work_event_locked(work_order_id, f"attempt.{status.value}", {"lease_released": True}, attempt_id=str(attempt_id), created_at=stamp)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    result = store.get_attempt(str(attempt_id))
    if result is None:
        raise RuntimeError("parked attempt disappeared")
    return result


def resume_parked_attempt(store, attempt_id: str, *, worker_id: str, runtime_epoch: int, lease_seconds: int = 120) -> WorkClaim:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    now = _now()
    stamp = now.isoformat()
    expires = (now + timedelta(seconds=lease_seconds)).isoformat()
    token = f"wlease_{uuid4().hex}"
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        row = store.connection.execute("SELECT * FROM work_attempts WHERE id=?", (str(attempt_id),)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        current = WorkAttemptStatus(str(row["status"]))
        if current not in {WorkAttemptStatus.WAITING_APPROVAL, WorkAttemptStatus.WAITING_RESOURCE}:
            raise ValueError("attempt is not parked")
        work_order_id = str(row["work_order_id"])
        if store.connection.execute("SELECT 1 FROM work_leases WHERE work_order_id=?", (work_order_id,)).fetchone() is not None:
            raise ValueError("work order already has a lease")
        store.connection.execute(
            "UPDATE work_attempts SET status=?, worker_id=?, runtime_epoch=? WHERE id=?",
            (WorkAttemptStatus.RUNNING.value, str(worker_id), int(runtime_epoch), str(attempt_id)),
        )
        store.connection.execute(
            "INSERT INTO work_leases(work_order_id,attempt_id,lease_token,worker_id,runtime_epoch,claimed_at,heartbeat_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (work_order_id, str(attempt_id), token, str(worker_id), int(runtime_epoch), stamp, stamp, expires),
        )
        store._set_order_status_locked(work_order_id, WorkOrderStatus.RUNNING, now=stamp)
        store._append_work_event_locked(work_order_id, "attempt.resumed", {"worker_id": str(worker_id), "runtime_epoch": int(runtime_epoch)}, attempt_id=str(attempt_id), created_at=stamp)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    attempt = store.get_attempt(str(attempt_id))
    lease = store.get_lease(work_order_id)
    if attempt is None or lease is None:
        raise RuntimeError("resumed attempt was not persisted")
    return WorkClaim(attempt=attempt, lease=lease)


def cancel_parked_attempt(store, attempt_id: str, *, actor: str, reason: str) -> None:
    stamp = _now().isoformat()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        row = store.connection.execute("SELECT * FROM work_attempts WHERE id=?", (str(attempt_id),)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        current = WorkAttemptStatus(str(row["status"]))
        if current not in {WorkAttemptStatus.WAITING_APPROVAL, WorkAttemptStatus.WAITING_RESOURCE}:
            raise ValueError("attempt is not parked")
        work_order_id = str(row["work_order_id"])
        store.connection.execute("UPDATE work_attempts SET status=?, finished_at=? WHERE id=?", (WorkAttemptStatus.CANCELLED.value, stamp, str(attempt_id)))
        store._set_order_status_locked(work_order_id, WorkOrderStatus.CANCELLED, now=stamp)
        store._append_work_event_locked(work_order_id, "attempt.cancelled", {"actor": str(actor), "reason": str(reason)[:1000]}, attempt_id=str(attempt_id), created_at=stamp)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
