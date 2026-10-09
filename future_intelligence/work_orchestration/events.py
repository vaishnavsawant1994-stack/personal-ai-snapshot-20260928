from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkEvent:
    id: str
    work_order_id: str
    event_type: str
    created_at: str
    attempt_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
