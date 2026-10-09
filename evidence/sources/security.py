from __future__ import annotations

from evidence.ingestion import EvidenceSourceType, IngestionRecord


def security_record(
    observation: str,
    *,
    source: str = "security_runtime",
    project_id: str | None = None,
    work_order_id: str | None = None,
) -> IngestionRecord:
    text = str(observation or "").strip()
    if not text:
        raise ValueError("security observation is required")
    return IngestionRecord(
        source_type=EvidenceSourceType.SECURITY_EVENT,
        source=source,
        subject="security event",
        observation=text,
        project_id=project_id,
        work_order_id=work_order_id,
        confidence=0.95,
        data_classification="sensitive",
    )
