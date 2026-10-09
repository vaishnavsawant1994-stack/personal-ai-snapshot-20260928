from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class WorkspaceState(StrEnum):
    PREPARED = "prepared"
    ACTIVE = "active"
    DIRTY = "dirty"
    REVIEW = "review"
    CLOSED = "closed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class WorkWorkspace:
    id: str
    work_order_id: str
    repository: str
    base_revision: str
    state: WorkspaceState
    created_at: str
    updated_at: str
    attempt_id: str | None = None
    working_revision: str | None = None
    branch_ref: str | None = None
    review_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("id", self.id),
            ("work_order_id", self.work_order_id),
            ("repository", self.repository),
            ("base_revision", self.base_revision),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
