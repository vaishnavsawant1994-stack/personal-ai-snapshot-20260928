from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr

from security.request_context import current_trusted_request


_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]{1,180}$")


class ContinuityExportBody(BaseModel):
    target_host_id: str = Field(min_length=4, max_length=200)
    confirm_source_fence: Literal["FENCE_AND_TRANSFER"]


class ContinuityValidateBody(BaseModel):
    bundle_filename: str = Field(min_length=1, max_length=180)
    transfer_token: SecretStr


def agent_continuity_router(runtime):
    registry = runtime["device_registry"]
    settings = runtime["settings"]
    store = runtime["agent_continuity_store"]
    authority = runtime["continuation_authority"]
    service = runtime.get("agent_continuity")
    checkpoint_service = runtime.get("continuity_checkpoint_service")
    export_root = (Path(settings.data_dir) / "continuity-exports").resolve()
    import_root = (Path(settings.data_dir) / "continuity-imports").resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    import_root.mkdir(parents=True, exist_ok=True)

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
            raise HTTPException(403, "This device is not permitted to manage agent continuity")
        return device_id

    router = APIRouter(
        prefix="/api/agent-continuity",
        tags=["agent-continuity"],
        dependencies=[Depends(require_owner_device)],
    )

    @router.get("/status")
    def status():
        row = store.current_authority()
        authority_status = None
        if row is not None:
            authority_status = {
                "host_id": row["host_id"],
                "epoch": int(row["epoch"]),
                "status": row["status"],
                "checkpoint_id": row["checkpoint_id"],
                "acquired_at": row["acquired_at"],
                "heartbeat_at": row["heartbeat_at"],
                "expires_at": row["expires_at"],
                "fenced_at": row["fenced_at"],
                "this_host": str(row["host_id"]) == authority.host_id,
            }
        return {
            "host_id": authority.host_id,
            "authority": authority_status,
            "authority_ready": bool(runtime.get("continuation_authority_ready")),
            "running_git_revision": runtime.get("running_git_revision"),
            "checkpoint_enabled": checkpoint_service is not None,
            "export_enabled": service is not None,
            "live_import_enabled": False,
            "import_mode": "stopped_runtime_only",
            "credentials_rebind_after_import": True,
        }

    @router.post("/checkpoints")
    def create_checkpoint():
        if checkpoint_service is None:
            raise HTTPException(503, "Exact running Body revision is unavailable")
        try:
            artifact = checkpoint_service.create()
            checkpoint_service.verify_source_artifact(artifact)
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc))
        return {
            "checkpoint": artifact.checkpoint.to_dict(),
            "backup_filename": artifact.backup_path.name,
        }

    @router.post("/export")
    def export(body: ContinuityExportBody):
        if service is None:
            raise HTTPException(503, "Cross-host continuity export is unavailable without an exact running revision")
        filename = f"vishnu-continuity-{secrets.token_hex(12)}.vcontinuity"
        destination = export_root / filename
        try:
            result = service.export_to(
                target_host_id=body.target_host_id,
                bundle_path=destination,
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(409, str(exc))
        # The transfer token is disclosed only in this successful owner response;
        # it is not persisted in the database or the bundle itself.
        return {
            "status": "source_fenced",
            "bundle_filename": filename,
            "download_path": f"/api/agent-continuity/exports/{filename}",
            "transfer_token": result.transfer_token,
            "checkpoint": result.checkpoint.to_dict(),
            "grant": result.grant.public_dict(include_token=False),
            "restart_source_to_resume": False,
            "source_may_execute": False,
        }

    @router.get("/exports/{filename}")
    def download_export(filename: str):
        if not _SAFE_FILE.fullmatch(str(filename)):
            raise HTTPException(404, "Continuity export not found")
        path = (export_root / filename).resolve()
        if export_root not in path.parents or not path.is_file():
            raise HTTPException(404, "Continuity export not found")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
        )

    @router.post("/validate-import")
    def validate_import(body: ContinuityValidateBody):
        if service is None:
            raise HTTPException(503, "Continuity validation requires an exact running Body revision")
        filename = str(body.bundle_filename)
        if not _SAFE_FILE.fullmatch(filename):
            raise HTTPException(404, "Continuity import not found")
        path = (import_root / filename).resolve()
        if import_root not in path.parents or not path.is_file():
            raise HTTPException(404, "Continuity import not found")
        try:
            return service.validate_import(
                bundle_path=path,
                transfer_token=body.transfer_token.get_secret_value(),
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc))

    return router
