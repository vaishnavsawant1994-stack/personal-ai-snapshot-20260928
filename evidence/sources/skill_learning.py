from __future__ import annotations

from evidence.ingestion import EvidenceSourceType, IngestionRecord


def skill_assessment_record(
    skill_id: str,
    observation: str,
    *,
    source: str = "skill_assessment",
    work_order_id: str | None = None,
    project_id: str | None = None,
    performance_regression: bool = False,
) -> IngestionRecord:
    skill = str(skill_id or "").strip()
    text = str(observation or "").strip()
    if not skill or not text:
        raise ValueError("skill_id and observation are required")
    return IngestionRecord(
        source_type=(
            EvidenceSourceType.PERFORMANCE_REGRESSION
            if performance_regression
            else EvidenceSourceType.SKILL_ASSESSMENT
        ),
        source=source,
        subject=f"skill:{skill}",
        observation=text,
        project_id=project_id,
        work_order_id=work_order_id,
        confidence=0.8,
        metadata={"skill_id": skill},
    )
