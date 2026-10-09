from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def evidence_fingerprint(
    *,
    source_type: str,
    source: str,
    subject: str,
    observation: str,
    project_id: str | None = None,
    work_order_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    canonical = {
        "source_type": str(source_type).strip().lower(),
        "source": str(source).strip(),
        "subject": " ".join(str(subject).split()),
        "observation": " ".join(str(observation).split()),
        "project_id": project_id,
        "work_order_id": work_order_id,
        "metadata": dict(metadata or {}),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
