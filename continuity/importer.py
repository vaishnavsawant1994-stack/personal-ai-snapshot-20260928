from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from recovery.backup import BackupService
from security.keychain import RootKeyStore

from .authority import HostContinuationAuthority
from .checkpoint import ContinuityCheckpointService
from .runtime_config import detect_running_git_revision
from .service import AgentContinuityService
from .store import ContinuityStore
from .verifier import ContinuityCompatibilityVerifier


def import_continuity_bundle(
    *,
    data_dir: str | Path,
    bundle_path: str | Path,
    transfer_token: str,
    running_git_revision: str,
    host_id: str | None = None,
    root_key_store: RootKeyStore | None = None,
) -> dict:
    """Import a cross-host bundle while the normal Vishnu runtime is stopped."""

    revision = str(running_git_revision or "").strip()
    token = str(transfer_token or "").strip()
    if not revision:
        raise ValueError("exact running Git revision is required")
    if not token:
        raise ValueError("transfer token is required")
    key_store = root_key_store or RootKeyStore()
    root = Path(data_dir).expanduser().resolve()
    backups = BackupService(root, root_key_store=key_store)
    store = ContinuityStore(root / "agent-continuity.sqlite3")
    authority = HostContinuationAuthority(
        store,
        host_id=host_id,
        root_key_store=key_store,
    )
    verifier = ContinuityCompatibilityVerifier(
        ContinuityCheckpointService.supported_schema_versions()
    )
    service = AgentContinuityService(
        store=store,
        authority=authority,
        backups=backups,
        verifier=verifier,
        running_git_revision=revision,
        maintenance_mode=True,
    )
    return service.import_bundle(
        bundle_path=Path(bundle_path).expanduser().resolve(),
        transfer_token=token,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Vishnu cross-host continuity bundle while Vishnu is stopped."
    )
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--host-id")
    parser.add_argument("--running-revision")
    args = parser.parse_args(argv)

    # Deliberately read the transfer credential from the environment instead of
    # accepting it as a CLI argument, so it is not exposed in process listings.
    token = str(os.getenv("VISHNU_CONTINUITY_TRANSFER_TOKEN") or "").strip()
    if not token:
        parser.error("VISHNU_CONTINUITY_TRANSFER_TOKEN must be set")
    revision = str(args.running_revision or "").strip() or detect_running_git_revision()
    if not revision:
        parser.error("--running-revision or VISHNU_RUNNING_GIT_REVISION is required")
    result = import_continuity_bundle(
        data_dir=args.data_dir,
        bundle_path=args.bundle,
        transfer_token=token,
        running_git_revision=revision,
        host_id=args.host_id,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
