from __future__ import annotations

from evidence.ingestion import EvidenceSourceType, IngestionRecord


def feedback_record(
    text: str,
    *,
    source: str = "owner_feedback",
    correction: bool = False,
    project_id: str | None = None,
    work_order_id: str | None = None,
) -> IngestionRecord:
    observation = str(text or "").strip()
    if not observation:
        raise ValueError("feedback text is required")
    return IngestionRecord(
        source_type=(
            EvidenceSourceType.USER_CORRECTION
            if correction
            else EvidenceSourceType.USER_FEEDBACK
        ),
        source=source,
        subject="owner feedback",
        observation=observation,
        project_id=project_id,
        work_order_id=work_order_id,
        confidence=1.0,
    )
