from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from evidence.sources.feedback import feedback_record
from security.request_context import current_trusted_request


class FeedbackBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    project_id: str | None = Field(default=None, max_length=200)
    work_order_id: str | None = Field(default=None, max_length=200)


def evidence_router(runtime):
    registry = runtime["device_registry"]
    store = runtime["evidence_store"]
    ingestor = runtime["evidence_ingestor"]

    def require_owner_device(
        authorization: str | None = Header(default=None),
        x_device_id: str | None = Header(default=None),
    ) -> str:
        context = current_trusted_request()
        if context is not None:
            device_id = str(context.device_id)
        else:
            device_id = str(x_device_id or "").strip()
            token = str(authorization or "").removeprefix("Bearer ").strip()
            if not device_id or not token or not registry.authenticate(device_id, token):
                raise HTTPException(401, "Trusted owner device authentication required")
        if not registry.is_active(device_id):
            raise HTTPException(401, "Trusted device is revoked")
        if hasattr(registry, "authorize") and not registry.authorize(device_id, "ai:chat"):
            raise HTTPException(403, "This device is not permitted to inspect Evidence")
        return device_id

    router = APIRouter(
        prefix="/api/evidence",
        tags=["evidence"],
        dependencies=[Depends(require_owner_device)],
    )

    @router.get("")
    def list_evidence(
        limit: int = Query(default=100, ge=1, le=500),
        source_type: str | None = Query(default=None, max_length=100),
        status: str | None = Query(default=None, max_length=50),
    ):
        rows = store.list_evidence()
        result = []
        for item in rows:
            if source_type and item.source_type != source_type:
                continue
            lifecycle = ingestor.lifecycle(item.id)
            lifecycle_status = str((lifecycle or {}).get("status") or "active")
            if status and lifecycle_status != status:
                continue
            result.append({"evidence": item.to_dict(), "lifecycle": lifecycle})
        return {
            "authority": "read_only",
            "deletion_authority": "not_exposed",
            "count": min(len(result), limit),
            "evidence": result[-limit:],
        }

    def _ingest_feedback(body: FeedbackBody, *, correction: bool):
        item = ingestor.ingest(
            feedback_record(
                body.text,
                correction=correction,
                project_id=body.project_id,
                work_order_id=body.work_order_id,
            ),
            actor="owner",
        )
        runtime["events"].emit(
            "conversation.correction" if correction else "conversation.feedback",
            evidence_id=item.id,
            message=body.text,
            project_id=body.project_id,
            work_order_id=body.work_order_id,
        )
        return {"evidence": item.to_dict(), "lifecycle": ingestor.lifecycle(item.id)}

    @router.post("/feedback")
    def feedback(body: FeedbackBody):
        return _ingest_feedback(body, correction=False)

    @router.post("/correction")
    def correction(body: FeedbackBody):
        return _ingest_feedback(body, correction=True)

    @router.get("/{evidence_id}")
    def evidence_detail(evidence_id: str):
        item = store.get_evidence(evidence_id)
        if item is None:
            raise HTTPException(404, "Evidence not found")
        claims = []
        try:
            claims = [claim.to_dict() for claim in store.claims_for_evidence(evidence_id)]
        except AttributeError:
            claims = []
        return {
            "evidence": item.to_dict(),
            "lifecycle": ingestor.lifecycle(evidence_id),
            "claims": claims,
            "authority": "read_only",
            "deletion_authority": "not_exposed",
        }

    return router
