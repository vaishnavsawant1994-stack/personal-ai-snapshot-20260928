from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .attempts import WorkAttempt, WorkAttemptStatus
from .events import WorkEvent
from .failure_policy import FailureClass, RetryDisposition, WorkFailure, retry_disposition
from .leases import WorkClaim, WorkLease
from .models import WorkOrderStatus
from .recovery import RecoveryReason
from .workspace import WorkWorkspace, WorkspaceState


class LeaseLostError(RuntimeError):
    pass


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class WorkDurabilityMixin:
    """Attempt, lease, event, retry and workspace lifecycle for canonical WorkStore.

    The mixin uses additive side tables. Existing WorkOrder payload contracts remain
    unchanged while execution history gains causal attempts and fencing.
    """

    connection: sqlite3.Connection

    def _append_work_event_locked(
        self,
        work_order_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        attempt_id: str | None = None,
        created_at: str | None = None,
    ) -> WorkEvent:
        created = created_at or _iso(_now_dt())
        event = WorkEvent(
            id=f"wev_{uuid4().hex}",
            work_order_id=str(work_order_id),
            attempt_id=attempt_id,
            event_type=str(event_type),
            payload=dict(payload or {}),
            created_at=created,
        )
        self.connection.execute(
            """
            INSERT INTO work_events(
                id, work_order_id, attempt_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.work_order_id,
                event.attempt_id,
                event.event_type,
                _json(dict(event.payload)),
                event.created_at,
            ),
        )
        return event

    def append_work_event(
        self,
        work_order_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        attempt_id: str | None = None,
    ) -> WorkEvent:
        with self.connection:
            return self._append_work_event_locked(
                work_order_id,
                event_type,
                payload,
                attempt_id=attempt_id,
            )

    def list_work_events(self, work_order_id: str) -> list[WorkEvent]:
        rows = self.connection.execute(
            """
            SELECT id, work_order_id, attempt_id, event_type, payload_json, created_at
            FROM work_events
            WHERE work_order_id = ?
            ORDER BY created_at, id
            """,
            (str(work_order_id),),
        ).fetchall()
        return [
            WorkEvent(
                id=str(row["id"]),
                work_order_id=str(row["work_order_id"]),
                attempt_id=row["attempt_id"],
                event_type=str(row["event_type"]),
                payload=json.loads(row["payload_json"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def _attempt_from_row(self, row: sqlite3.Row) -> WorkAttempt:
        return WorkAttempt(
            id=str(row["id"]),
            work_order_id=str(row["work_order_id"]),
            attempt_number=int(row["attempt_number"]),
            parent_attempt_id=row["parent_attempt_id"],
            worker_id=str(row["worker_id"]),
            status=WorkAttemptStatus(str(row["status"])),
            runtime_epoch=int(row["runtime_epoch"]),
            execution_id=row["execution_id"],
            failure_class=row["failure_class"],
            failure_code=row["failure_code"],
            retry_disposition=row["retry_disposition"],
            started_at=str(row["started_at"]),
            finished_at=row["finished_at"],
            metadata=json.loads(row["metadata_json"]),
        )

    def get_attempt(self, attempt_id: str) -> WorkAttempt | None:
        row = self.connection.execute(
            "SELECT * FROM work_attempts WHERE id = ?",
            (str(attempt_id),),
        ).fetchone()
        return self._attempt_from_row(row) if row else None

    def list_attempts(self, work_order_id: str) -> list[WorkAttempt]:
        rows = self.connection.execute(
            """
            SELECT * FROM work_attempts
            WHERE work_order_id = ?
            ORDER BY attempt_number, started_at, id
            """,
            (str(work_order_id),),
        ).fetchall()
        return [self._attempt_from_row(row) for row in rows]

    def _lease_from_row(self, row: sqlite3.Row) -> WorkLease:
        return WorkLease(
            work_order_id=str(row["work_order_id"]),
            attempt_id=str(row["attempt_id"]),
            lease_token=str(row["lease_token"]),
            worker_id=str(row["worker_id"]),
            runtime_epoch=int(row["runtime_epoch"]),
            claimed_at=str(row["claimed_at"]),
            heartbeat_at=str(row["heartbeat_at"]),
            expires_at=str(row["expires_at"]),
        )

    def get_lease(self, work_order_id: str) -> WorkLease | None:
        row = self.connection.execute(
            "SELECT * FROM work_leases WHERE work_order_id = ?",
            (str(work_order_id),),
        ).fetchone()
        return self._lease_from_row(row) if row else None

    def _set_order_status_locked(
        self,
        work_order_id: str,
        status: WorkOrderStatus,
        *,
        now: str,
    ) -> None:
        row = self.connection.execute(
            "SELECT payload_json FROM work_orders WHERE id = ?",
            (str(work_order_id),),
        ).fetchone()
        if row is None:
            raise KeyError(work_order_id)
        payload = json.loads(row["payload_json"])
        payload["status"] = status.value
        payload["updated_at"] = now
        self.connection.execute(
            """
            UPDATE work_orders
            SET status = ?, payload_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, _json(payload), now, str(work_order_id)),
        )

    def dependencies_ready(self, work_order_id: str) -> bool:
        rows = self.connection.execute(
            """
            SELECT dependency.status
            FROM work_order_dependencies AS edge
            JOIN work_orders AS dependency ON dependency.id = edge.depends_on_id
            WHERE edge.work_order_id = ?
            """,
            (str(work_order_id),),
        ).fetchall()
        return all(str(row[0]) == WorkOrderStatus.COMPLETED.value for row in rows)

    def _transition_expired_lease_locked(
        self,
        lease_row: sqlite3.Row,
        *,
        now: str,
        reason: RecoveryReason = RecoveryReason.LEASE_EXPIRED,
    ) -> None:
        attempt_id = str(lease_row["attempt_id"])
        work_order_id = str(lease_row["work_order_id"])
        self.connection.execute(
            """
            UPDATE work_attempts
            SET status = ?, failure_class = ?, failure_code = ?,
                retry_disposition = ?, finished_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                WorkAttemptStatus.RECOVERY_REQUIRED.value,
                FailureClass.UNKNOWN_EFFECT.value,
                reason.value,
                RetryDisposition.RECOVERY_REQUIRED.value,
                now,
                attempt_id,
                WorkAttemptStatus.RUNNING.value,
            ),
        )
        self.connection.execute(
            "DELETE FROM work_leases WHERE work_order_id = ?",
            (work_order_id,),
        )
        self._set_order_status_locked(
            work_order_id,
            WorkOrderStatus.RECOVERY_REQUIRED,
            now=now,
        )
        self._append_work_event_locked(
            work_order_id,
            "lease.expired_recovery_required",
            {
                "reason": reason.value,
                "worker_id": str(lease_row["worker_id"]),
                "runtime_epoch": int(lease_row["runtime_epoch"]),
            },
            attempt_id=attempt_id,
            created_at=now,
        )

    def claim_work_order(
        self,
        work_order_id: str,
        *,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 60,
        execution_id: str | None = None,
    ) -> WorkClaim | None:
        work_order_id = str(work_order_id or "").strip()
        worker_id = str(worker_id or "").strip()
        if not work_order_id or not worker_id:
            raise ValueError("work_order_id and worker_id are required")
        if runtime_epoch < 0:
            raise ValueError("runtime_epoch must be non-negative")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

        now_dt = _now_dt()
        now = _iso(now_dt)
        expires = _iso(now_dt + timedelta(seconds=lease_seconds))

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            order_row = self.connection.execute(
                "SELECT status FROM work_orders WHERE id = ?",
                (work_order_id,),
            ).fetchone()
            if order_row is None:
                raise KeyError(work_order_id)

            lease_row = self.connection.execute(
                "SELECT * FROM work_leases WHERE work_order_id = ?",
                (work_order_id,),
            ).fetchone()
            if lease_row is not None:
                if str(lease_row["expires_at"]) <= now:
                    self._transition_expired_lease_locked(lease_row, now=now)
                    self.connection.commit()
                    return None
                self.connection.rollback()
                return None

            status = str(order_row["status"])
            if status not in {
                WorkOrderStatus.QUEUED.value,
                WorkOrderStatus.RETRYING.value,
            }:
                self.connection.rollback()
                return None
            if not self.dependencies_ready(work_order_id):
                self.connection.rollback()
                return None

            previous = self.connection.execute(
                """
                SELECT id, attempt_number
                FROM work_attempts
                WHERE work_order_id = ?
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                (work_order_id,),
            ).fetchone()
            attempt_number = 1 if previous is None else int(previous["attempt_number"]) + 1
            parent_attempt_id = None if previous is None else str(previous["id"])
            attempt_id = f"wat_{uuid4().hex}"
            lease_token = f"wlease_{uuid4().hex}"

            self.connection.execute(
                """
                INSERT INTO work_attempts(
                    id, work_order_id, attempt_number, parent_attempt_id,
                    worker_id, status, runtime_epoch, execution_id,
                    failure_code, failure_class, retry_disposition,
                    started_at, finished_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, ?)
                """,
                (
                    attempt_id,
                    work_order_id,
                    attempt_number,
                    parent_attempt_id,
                    worker_id,
                    WorkAttemptStatus.RUNNING.value,
                    runtime_epoch,
                    execution_id,
                    now,
                    "{}",
                ),
            )
            self.connection.execute(
                """
                INSERT INTO work_leases(
                    work_order_id, attempt_id, lease_token, worker_id,
                    runtime_epoch, claimed_at, heartbeat_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_order_id,
                    attempt_id,
                    lease_token,
                    worker_id,
                    runtime_epoch,
                    now,
                    now,
                    expires,
                ),
            )
            self._set_order_status_locked(
                work_order_id,
                WorkOrderStatus.RUNNING,
                now=now,
            )
            self._append_work_event_locked(
                work_order_id,
                "attempt.started",
                {
                    "attempt_number": attempt_number,
                    "worker_id": worker_id,
                    "runtime_epoch": runtime_epoch,
                },
                attempt_id=attempt_id,
                created_at=now,
            )
            self._append_work_event_locked(
                work_order_id,
                "lease.claimed",
                {"worker_id": worker_id, "runtime_epoch": runtime_epoch},
                attempt_id=attempt_id,
                created_at=now,
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        attempt = self.get_attempt(attempt_id)
        lease = self.get_lease(work_order_id)
        if attempt is None or lease is None:
            raise RuntimeError("claimed work was not durably persisted")
        return WorkClaim(attempt=attempt, lease=lease)

    def renew_lease(
        self,
        work_order_id: str,
        *,
        lease_token: str,
        worker_id: str,
        runtime_epoch: int,
        lease_seconds: int = 60,
    ) -> WorkLease | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        now_dt = _now_dt()
        now = _iso(now_dt)
        expires = _iso(now_dt + timedelta(seconds=lease_seconds))

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT * FROM work_leases WHERE work_order_id = ?",
                (str(work_order_id),),
            ).fetchone()
            if row is None:
                self.connection.rollback()
                return None
            if str(row["expires_at"]) <= now:
                self._transition_expired_lease_locked(row, now=now)
                self.connection.commit()
                return None
            if (
                str(row["lease_token"]) != str(lease_token)
                or str(row["worker_id"]) != str(worker_id)
                or int(row["runtime_epoch"]) != int(runtime_epoch)
            ):
                self.connection.rollback()
                return None
            self.connection.execute(
                """
                UPDATE work_leases
                SET heartbeat_at = ?, expires_at = ?
                WHERE work_order_id = ?
                """,
                (now, expires, str(work_order_id)),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_lease(str(work_order_id))

    def release_lease(
        self,
        work_order_id: str,
        *,
        lease_token: str,
        event_type: str = "lease.released",
    ) -> bool:
        now = _iso(_now_dt())
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT * FROM work_leases WHERE work_order_id = ?",
                (str(work_order_id),),
            ).fetchone()
            if row is None or str(row["lease_token"]) != str(lease_token):
                self.connection.rollback()
                return False
            self.connection.execute(
                "DELETE FROM work_leases WHERE work_order_id = ?",
                (str(work_order_id),),
            )
            self._append_work_event_locked(
                str(work_order_id),
                event_type,
                {"worker_id": str(row["worker_id"])},
                attempt_id=str(row["attempt_id"]),
                created_at=now,
            )
            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            raise

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        lease_token: str,
        status: WorkAttemptStatus,
        failure: WorkFailure | None = None,
        metadata: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> WorkAttempt:
        if status not in {
            WorkAttemptStatus.SUCCEEDED,
            WorkAttemptStatus.FAILED,
            WorkAttemptStatus.RECOVERY_REQUIRED,
            WorkAttemptStatus.CANCELLED,
        }:
            raise ValueError("finish_attempt requires a terminal attempt status")
        if status is WorkAttemptStatus.FAILED and failure is None:
            raise ValueError("failed attempts require WorkFailure")
        if status is not WorkAttemptStatus.FAILED and failure is not None:
            raise ValueError("WorkFailure is only valid for failed attempts")

        now = _iso(_now_dt())
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT a.*, l.lease_token
                FROM work_attempts AS a
                JOIN work_leases AS l ON l.attempt_id = a.id
                WHERE a.id = ?
                """,
                (str(attempt_id),),
            ).fetchone()
            if row is None or str(row["lease_token"]) != str(lease_token):
                raise LeaseLostError(attempt_id)
            if WorkAttemptStatus(str(row["status"])) is not WorkAttemptStatus.RUNNING:
                raise ValueError("attempt is not running")

            disposition: RetryDisposition | None = None
            failure_class: str | None = None
            failure_code: str | None = None
            if status is WorkAttemptStatus.FAILED:
                assert failure is not None
                disposition = retry_disposition(
                    failure.failure_class,
                    attempt_number=int(row["attempt_number"]),
                    max_attempts=max_attempts,
                )
                failure_class = failure.failure_class.value
                failure_code = failure.code
            elif status is WorkAttemptStatus.RECOVERY_REQUIRED:
                disposition = RetryDisposition.RECOVERY_REQUIRED
                failure_class = FailureClass.UNKNOWN_EFFECT.value
                failure_code = RecoveryReason.UNKNOWN_EFFECT.value

            merged_metadata = json.loads(row["metadata_json"])
            merged_metadata.update(metadata or {})
            if failure is not None:
                merged_metadata["failure"] = {
                    "message": failure.message,
                    "metadata": dict(failure.metadata),
                }

            self.connection.execute(
                """
                UPDATE work_attempts
                SET status = ?, failure_class = ?, failure_code = ?,
                    retry_disposition = ?, finished_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    failure_class,
                    failure_code,
                    None if disposition is None else disposition.value,
                    now,
                    _json(merged_metadata),
                    str(attempt_id),
                ),
            )
            work_order_id = str(row["work_order_id"])
            order_status = {
                WorkAttemptStatus.SUCCEEDED: WorkOrderStatus.VERIFYING,
                WorkAttemptStatus.FAILED: WorkOrderStatus.FAILED,
                WorkAttemptStatus.RECOVERY_REQUIRED: WorkOrderStatus.RECOVERY_REQUIRED,
                WorkAttemptStatus.CANCELLED: WorkOrderStatus.CANCELLED,
            }[status]
            self._set_order_status_locked(work_order_id, order_status, now=now)
            self.connection.execute(
                "DELETE FROM work_leases WHERE attempt_id = ?",
                (str(attempt_id),),
            )
            self._append_work_event_locked(
                work_order_id,
                f"attempt.{status.value}",
                {
                    "failure_class": failure_class,
                    "failure_code": failure_code,
                    "retry_disposition": None if disposition is None else disposition.value,
                },
                attempt_id=str(attempt_id),
                created_at=now,
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        result = self.get_attempt(str(attempt_id))
        if result is None:
            raise RuntimeError("attempt disappeared after completion")
        return result

    def mark_recovery_required(
        self,
        work_order_id: str,
        *,
        reason: RecoveryReason,
        attempt_id: str | None = None,
    ) -> None:
        now = _iso(_now_dt())
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if attempt_id is None:
                row = self.connection.execute(
                    """
                    SELECT id FROM work_attempts
                    WHERE work_order_id = ?
                    ORDER BY attempt_number DESC
                    LIMIT 1
                    """,
                    (str(work_order_id),),
                ).fetchone()
                attempt_id = None if row is None else str(row["id"])
            if attempt_id is not None:
                self.connection.execute(
                    """
                    UPDATE work_attempts
                    SET status = ?, failure_class = ?, failure_code = ?,
                        retry_disposition = ?, finished_at = COALESCE(finished_at, ?)
                    WHERE id = ?
                    """,
                    (
                        WorkAttemptStatus.RECOVERY_REQUIRED.value,
                        FailureClass.UNKNOWN_EFFECT.value,
                        reason.value,
                        RetryDisposition.RECOVERY_REQUIRED.value,
                        now,
                        attempt_id,
                    ),
                )
                self.connection.execute(
                    "DELETE FROM work_leases WHERE attempt_id = ?",
                    (attempt_id,),
                )
            self._set_order_status_locked(
                str(work_order_id),
                WorkOrderStatus.RECOVERY_REQUIRED,
                now=now,
            )
            self._append_work_event_locked(
                str(work_order_id),
                "work.recovery_required",
                {"reason": reason.value},
                attempt_id=attempt_id,
                created_at=now,
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def retry_work_order(
        self,
        work_order_id: str,
        *,
        actor: str,
        reason: str,
        allow_recovery_override: bool = False,
    ) -> None:
        actor = str(actor or "").strip()
        reason = str(reason or "").strip()
        if not actor or not reason:
            raise ValueError("actor and reason are required")
        now = _iso(_now_dt())
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            lease = self.connection.execute(
                "SELECT 1 FROM work_leases WHERE work_order_id = ?",
                (str(work_order_id),),
            ).fetchone()
            if lease is not None:
                raise ValueError("cannot retry while a live lease exists")
            latest = self.connection.execute(
                """
                SELECT * FROM work_attempts
                WHERE work_order_id = ?
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                (str(work_order_id),),
            ).fetchone()
            if latest is None:
                raise ValueError("cannot retry work with no prior attempt")
            disposition = latest["retry_disposition"]
            if (
                str(latest["status"]) == WorkAttemptStatus.RECOVERY_REQUIRED.value
                or disposition == RetryDisposition.RECOVERY_REQUIRED.value
            ) and not allow_recovery_override:
                raise ValueError("recovery-required work needs explicit reconciliation override")
            if disposition == RetryDisposition.TERMINAL.value:
                raise ValueError("terminal failure is not retryable")
            self._set_order_status_locked(
                str(work_order_id),
                WorkOrderStatus.RETRYING,
                now=now,
            )
            self._append_work_event_locked(
                str(work_order_id),
                "work.retry_requested",
                {
                    "actor": actor,
                    "reason": reason,
                    "recovery_override": bool(allow_recovery_override),
                    "prior_attempt_id": str(latest["id"]),
                },
                attempt_id=str(latest["id"]),
                created_at=now,
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def register_workspace(self, workspace: WorkWorkspace) -> WorkWorkspace:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO work_workspaces(
                    id, work_order_id, attempt_id, repository, base_revision,
                    working_revision, branch_ref, review_ref, state,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.id,
                    workspace.work_order_id,
                    workspace.attempt_id,
                    workspace.repository,
                    workspace.base_revision,
                    workspace.working_revision,
                    workspace.branch_ref,
                    workspace.review_ref,
                    workspace.state.value,
                    _json(dict(workspace.metadata)),
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
            self._append_work_event_locked(
                workspace.work_order_id,
                "workspace.registered",
                {
                    "workspace_id": workspace.id,
                    "repository": workspace.repository,
                    "base_revision": workspace.base_revision,
                },
                attempt_id=workspace.attempt_id,
                created_at=workspace.created_at,
            )
        return workspace

    def get_workspace(self, workspace_id: str) -> WorkWorkspace | None:
        row = self.connection.execute(
            "SELECT * FROM work_workspaces WHERE id = ?",
            (str(workspace_id),),
        ).fetchone()
        if row is None:
            return None
        return WorkWorkspace(
            id=str(row["id"]),
            work_order_id=str(row["work_order_id"]),
            attempt_id=row["attempt_id"],
            repository=str(row["repository"]),
            base_revision=str(row["base_revision"]),
            working_revision=row["working_revision"],
            branch_ref=row["branch_ref"],
            review_ref=row["review_ref"],
            state=WorkspaceState(str(row["state"])),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
