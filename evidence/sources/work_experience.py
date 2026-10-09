from __future__ import annotations

from evidence.ingestion import EvidenceSourceType, IngestionRecord


def work_experience_record(
    observation: str,
    *,
    work_order_id: str,
    source: str = "work_runtime",
    project_id: str | None = None,
    worker_run_id: str | None = None,
    repeated_intervention: bool = False,
    workflow_friction: bool = False,
) -> IngestionRecord:
    text = str(observation or "").strip()
    if not text:
        raise ValueError("work observation is required")
    if repeated_intervention:
        source_type = EvidenceSourceType.REPEATED_INTERVENTION
    elif workflow_friction:
        source_type = EvidenceSourceType.WORKFLOW_FRICTION
    else:
        source_type = EvidenceSourceType.WORK_EXPERIENCE
    return IngestionRecord(
        source_type=source_type,
        source=source,
        subject=f"work_order:{work_order_id}",
        observation=text,
        project_id=project_id,
        work_order_id=work_order_id,
        worker_run_id=worker_run_id,
        confidence=0.85,
    )
