from __future__ import annotations

from pathlib import Path
from typing import Any

from identity.store import IdentityStore
from recovery.backup import BackupService

from .authority import HostContinuationAuthority
from .checkpoint import ContinuityCheckpointService
from .runtime_config import detect_running_git_revision
from .service import AgentContinuityService
from .store import ContinuityStore
from .verifier import ContinuityCompatibilityVerifier


def build_agent_continuity_runtime(
    *,
    data_dir: str | Path,
    backups: BackupService,
    identity_store: IdentityStore,
    agent_executor,
    events=None,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    """Attach E8 host authority to the normal runtime without weakening startup.

    The execution guard is attached even when exact Body revision discovery is
    unavailable. Cross-host checkpoint/export is simply unavailable until an
    exact revision is configured; ordinary execution still requires a valid
    local continuation-authority lease.
    """

    root = Path(data_dir).expanduser().resolve()
    store = ContinuityStore(root / "agent-continuity.sqlite3")
    authority = HostContinuationAuthority(store)
    authority_ready = False
    authority_error: str | None = None
    try:
        lease = authority.bootstrap_or_resume()
        authority_ready = True
        if events is not None:
            events.emit(
                "continuity.authority.ready",
                host_id=lease.host_id,
                epoch=lease.epoch,
            )
    except Exception as exc:
        authority_error = type(exc).__name__
        if events is not None:
            events.emit(
                "continuity.authority.unavailable",
                host_id=authority.host_id,
                error_type=authority_error,
            )

    # Always attach the guard. If bootstrap failed because this host is fenced or
    # the restored authority belongs elsewhere, every effect fails closed.
    if hasattr(agent_executor, "attach_continuation_authority"):
        agent_executor.attach_continuation_authority(authority.assert_active)

    running_revision = detect_running_git_revision(repository_root=repository_root)
    verifier = ContinuityCompatibilityVerifier(
        ContinuityCheckpointService.supported_schema_versions()
    )
    checkpoint_service = None
    service = None
    if running_revision:
        checkpoint_service = ContinuityCheckpointService(
            store=store,
            authority=authority,
            backups=backups,
            identity_store=identity_store,
            running_git_revision=running_revision,
        )
        service = AgentContinuityService(
            store=store,
            authority=authority,
            backups=backups,
            verifier=verifier,
            running_git_revision=running_revision,
            checkpoint_service=checkpoint_service,
            maintenance_mode=False,
        )
    elif events is not None:
        events.emit(
            "continuity.checkpoint_unavailable",
            reason="exact_running_revision_unknown",
        )

    return {
        "agent_continuity_store": store,
        "continuation_authority": authority,
        "continuation_authority_ready": authority_ready,
        "continuation_authority_error": authority_error,
        "running_git_revision": running_revision,
        "continuity_checkpoint_service": checkpoint_service,
        "agent_continuity": service,
    }
