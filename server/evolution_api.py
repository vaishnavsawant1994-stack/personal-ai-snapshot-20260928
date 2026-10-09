from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from evolution import CandidateStatus
from security.request_context import current_trusted_request


class EvolutionApprovalBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    base_body_revision: str = Field(min_length=7, max_length=160)


class EvolutionRejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CodeCommitBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class CodeReviewBody(BaseModel):
    review_ref: str = Field(min_length=1, max_length=2000)


class AdoptionApprovalBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ActivationConfirmationBody(BaseModel):
    running_revision: str = Field(min_length=7, max_length=160)


def evolution_router(runtime):
    registry = runtime["device_registry"]
    service = runtime["evolution"]
    store = runtime["evolution_store"]
    handoffs = runtime.get("evolution_handoff")
    code_body = runtime.get("code_body")
    adoption = runtime.get("body_adoption")

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
            raise HTTPException(403, "This device is not permitted to review evolution proposals")
        return device_id

    router = APIRouter(
        prefix="/api/evolution",
        tags=["evolution"],
        dependencies=[Depends(require_owner_device)],
    )

    @router.get("/status")
    def status():
        candidates = store.list_candidates()
        code_config = runtime.get("code_body_config")
        return {
            "mode": service.mode.value,
            "authority": "owner",
            "execution_authority": "none_in_evolution_service",
            "candidates": len(candidates),
            "recommended": sum(item.status is CandidateStatus.RECOMMENDED for item in candidates),
            "deferred": sum(item.status is CandidateStatus.DEFERRED for item in candidates),
            "restricted": sum(item.status is CandidateStatus.RESTRICTED for item in candidates),
            "handed_off": sum(item.status is CandidateStatus.HANDED_OFF for item in candidates),
            "adoption_approved": sum(item.status is CandidateStatus.ADOPTION_APPROVED for item in candidates),
            "adopted": sum(item.status is CandidateStatus.ADOPTED for item in candidates),
            "code_body_enabled": code_body is not None,
            "local_code_verification_enabled": bool(
                code_config is not None and code_config.local_verification_enabled
            ),
            "merge_authority": "not_exposed",
            "deploy_authority": "not_exposed",
        }

    @router.post("/scan")
    def scan():
        cycle = service.run_cycle()
        return {
            "mode": cycle.mode.value,
            "scanned": cycle.scanned,
            "skipped_ids": list(cycle.skipped_ids),
            "candidates": [item.to_dict() for item in cycle.created_or_existing],
        }

    @router.get("/candidates")
    def list_candidates(limit: int = Query(default=50, ge=1, le=200)):
        items = store.list_candidates()[-limit:]
        return {"candidates": [item.to_dict() for item in items]}

    @router.get("/candidates/{candidate_id}")
    def candidate_detail(candidate_id: str):
        item = store.get_candidate(candidate_id)
        if item is None:
            raise HTTPException(404, "Evolution candidate not found")
        result = item.to_dict()
        result["decisions"] = store.decisions_for(candidate_id)
        if handoffs is not None:
            handoff = handoffs.get(candidate_id)
            result["handoff"] = handoff.to_dict() if handoff is not None else None
        if code_body is not None:
            run = code_body.latest(candidate_id)
            result["code_body"] = run.to_dict() if run is not None else None
        if adoption is not None:
            record = adoption.get(candidate_id)
            result["adoption"] = record.__dict__ if record is not None else None
        return result

    @router.post("/candidates/{candidate_id}/approve")
    def approve_candidate(candidate_id: str, body: EvolutionApprovalBody):
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
        if handoffs is None:
            raise HTTPException(503, "Evolution handoff service unavailable")
        try:
            handoffs.reject(candidate_id, owner_id="owner", reason=body.reason)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": "rejected", "authority": "owner", "candidate_id": candidate_id}

    @router.post("/candidates/{candidate_id}/code/prepare")
    def prepare_code(candidate_id: str):
        if code_body is None:
            raise HTTPException(503, "Code-body evolution is not enabled on this runtime")
        try:
            run = code_body.prepare(
                candidate_id,
                worker_id="evolution-code-worker",
                runtime_epoch=int(runtime.get("code_worker_epoch", 0)),
            )
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": run.status.value, "code_body": run.to_dict()}

    @router.post("/candidates/{candidate_id}/code/commit")
    def commit_code(candidate_id: str, body: CodeCommitBody):
        if code_body is None:
            raise HTTPException(503, "Code-body evolution is not enabled on this runtime")
        try:
            run = code_body.commit(candidate_id, message=body.message)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": run.status.value, "code_body": run.to_dict()}

    @router.post("/candidates/{candidate_id}/code/verify")
    def verify_code(candidate_id: str):
        if code_body is None:
            raise HTTPException(503, "Code-body evolution is not enabled on this runtime")
        try:
            run = code_body.verify(candidate_id)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": run.status.value, "code_body": run.to_dict()}

    @router.post("/candidates/{candidate_id}/code/review")
    def verify_review(candidate_id: str, body: CodeReviewBody):
        if code_body is None:
            raise HTTPException(503, "Code-body evolution is not enabled on this runtime")
        try:
            run = code_body.attach_review(candidate_id, review_ref=body.review_ref)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": run.status.value, "code_body": run.to_dict()}

    @router.post("/candidates/{candidate_id}/adoption/approve")
    def approve_adoption(candidate_id: str, body: AdoptionApprovalBody):
        if adoption is None:
            raise HTTPException(503, "Body adoption service is unavailable")
        try:
            record = adoption.approve(candidate_id, owner_id="owner", reason=body.reason)
        except KeyError:
            raise HTTPException(404, "Evolution candidate not found")
        except (PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": record.status, "authority": "owner", "adoption": record.__dict__}

    @router.post("/candidates/{candidate_id}/activation/confirm")
    def confirm_activation(candidate_id: str, body: ActivationConfirmationBody):
        if adoption is None:
            raise HTTPException(503, "Body adoption service is unavailable")
        try:
            record = adoption.confirm_activation(
                candidate_id,
                running_revision=body.running_revision,
                actor="trusted_owner_activation_confirmation",
            )
        except (KeyError, PermissionError, ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        return {"status": record.status, "adoption": record.__dict__}

    return router
