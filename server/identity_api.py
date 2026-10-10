from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from security.request_context import current_trusted_request


def identity_router(runtime):
    registry = runtime["device_registry"]
    identity = runtime["identity_runtime"]
    store = runtime["identity_store"]

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
            raise HTTPException(403, "This device is not permitted to inspect identity")
        return device_id

    router = APIRouter(
        prefix="/api/identity",
        tags=["identity"],
        dependencies=[Depends(require_owner_device)],
    )

    @router.get("/status")
    def status():
        return identity.status().to_dict()

    @router.get("/body")
    def body():
        return {
            "manifest": identity.body.to_dict(),
            "manifest_id": identity.body.manifest_id,
            "active_revision": store.active_body_revision(),
            "authority": "read_only",
            "activation_authority": "separate_owner_governed_adoption",
        }

    @router.get("/self")
    def self_profile():
        latest = store.latest_self_version()
        if latest is None:
            return {"version": None, "profile": None, "authority": "behavior_only"}
        version, profile = latest
        return {"version": version, "profile": profile.to_dict(), "authority": "behavior_only"}

    @router.put("/self")
    def update_self(payload: dict):
        try:
            version, profile = identity.update_self(payload, actor="owner")
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "version": version,
            "profile": profile.to_dict(),
            "authority": "behavior_only",
            "note": "Self cannot grant permissions, tool access, approval, merge, deploy or continuation authority.",
        }

    return router
