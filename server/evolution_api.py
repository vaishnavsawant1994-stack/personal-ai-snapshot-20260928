from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from evolution import CandidateStatus
from security.request_context import current_trusted_request


class EvolutionApprovalBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    base_body_revision: str = Field(min_length=7, max_length=160)


class EvolutionRejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def evolution_router(runtime):
    router = APIRouter(prefix="/api/evolution", tags=["evolution"])
    registry = runtime["device_registry"]
    service = runtime["evolution"]
    store = runtime["evolution_store"]
    handoffs = runtime.get("evolution_handoff")

    def require_owner():
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, "Trusted owner session required")
        if not registry.is_active(context.device_id):
            raise HTTPException(401, "Trusted device is revoked")
        if hasattr(registry, "authorize") and not registry.authorize(context.device_id, "ai:chat"):
            raise HTTPException(403, "This device is not permitted to review evolution proposals")
        return context

    @router.get("/status")
    def status():
        require_owner()
        candidates = store.list_candidates()
        return {
            "mode": service.mode.value,
            "authority": "owner",
            "execution_authority": "none_in_evolution_service",
            "candidates": len(candidates),
            "recommended": sum(item.status is CandidateStatus.RECOMMENDED for item in candidates),
            "deferred": sum(item.status is CandidateStatus.DEFERRED for item in candidates),
            "restricted": sum(item.status is CandidateStatus.RESTRICTED for item in candidates),
            "handed_off": sum(item.status is CandidateStatus.HANDED_OFF for item in candidates),
        }

    @router.post("/scan")
    def scan():
        require_owner()
        cycle = service.run_cycle()
        return {
            "mode": cycle.mode.value,
            "scanned": cycle.scanned,
            "skipped_ids": list(cycle.skipped_ids),
            "candidates": [item.to_dict() for item in cycle.created_or_existing],
        }

    @router.get("/candidates")
    def list_candidates(limit: int = Query(default=50, ge=1, le=200)):
        require_owner()
        items = store.list_candidates()[-limit:]
        return {"candidates": [item.to_dict() for item in items]}

    @router.get("/candidates/{candidate_id}")
    def candidate_detail(candidate_id: str):
        require_owner()
        item = store.get_candidate(candidate_id)
        if item is None:
            raise HTTPException(404, "Evolution candidate not found")
        result = item.to_dict()
        result["decisions"] = store.decisions_for(candidate_id)
        if handoffs is not None:
            handoff = handoffs.get(candidate_id)
            result["handoff"] = handoff.to_dict() if handoff is not None else None
        return result

    @router.post("/candidates/{candidate_id}/approve")
    def approve_candidate(candidate_id: str, body: EvolutionApprovalBody):
        require_owner()
        if handoffs is None:
            raise HTTPException(503, "Evolution handoff service unavailable")
        try:
            handoff = handoffs.approve(
                candidate_id,
                owner_id="owner",
                reason=body.reason,
                base_body_revision=body.base_body_revision,
            )
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError) as exc:
            raise HTTPException(409, str(exc))
        return {
            "status": "handed_off",
            "authority": "owner",
            "handoff": handoff.to_dict(),
        }

    @router.post("/candidates/{candidate_id}/reject")
    def reject_candidate(candidate_id: str, body: EvolutionRejectBody):
        require_owner()
        if handoffs is None:
            raise HTTPException(503, "Evolution handoff service unavailable")
        try:
            handoffs.reject(candidate_id, owner_id="owner", reason=body.reason)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": "rejected", "authority": "owner", "candidate_id": candidate_id}

    return router
