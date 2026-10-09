from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class WorkAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkAttempt:
    id: str
    work_order_id: str
    attempt_number: int
    worker_id: str
    status: WorkAttemptStatus
    runtime_epoch: int
    started_at: str
    parent_attempt_id: str | None = None
    execution_id: str | None = None
    failure_class: str | None = None
    failure_code: str | None = None
    retry_disposition: str | None = None
    finished_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.work_order_id.strip() or not self.worker_id.strip():
            raise ValueError("attempt id, work_order_id and worker_id are required")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if self.runtime_epoch < 0:
            raise ValueError("runtime_epoch must be non-negative")
