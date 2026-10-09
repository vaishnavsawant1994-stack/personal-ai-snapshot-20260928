from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from security.request_context import current_trusted_request


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
