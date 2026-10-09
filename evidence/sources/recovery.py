from __future__ import annotations

from evidence.ingestion import EvidenceSourceType, IngestionRecord


def recovery_record(
    observation: str,
    *,
    source: str = "recovery_runtime",
    work_order_id: str | None = None,
    worker_run_id: str | None = None,
    project_id: str | None = None,
) -> IngestionRecord:
    text = str(observation or "").strip()
    if not text:
        raise ValueError("recovery observation is required")
    return IngestionRecord(
        source_type=EvidenceSourceType.RECOVERY_EVENT,
        source=source,
        subject=(f"work_order:{work_order_id}" if work_order_id else "runtime recovery"),
        observation=text,
        project_id=project_id,
        work_order_id=work_order_id,
        worker_run_id=worker_run_id,
        confidence=0.95,
    )
