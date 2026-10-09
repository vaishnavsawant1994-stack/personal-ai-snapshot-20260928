from __future__ import annotations

from dataclasses import dataclass

from .attempts import WorkAttempt


@dataclass(frozen=True)
class WorkLease:
    work_order_id: str
    attempt_id: str
    lease_token: str
    worker_id: str
    runtime_epoch: int
    claimed_at: str
    heartbeat_at: str
    expires_at: str


@dataclass(frozen=True)
class WorkClaim:
    attempt: WorkAttempt
    lease: WorkLease
