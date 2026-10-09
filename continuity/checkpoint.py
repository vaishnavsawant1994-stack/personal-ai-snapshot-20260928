from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from evidence.migrations import EVIDENCE_SCHEMA_VERSION
from evolution.migrations import EVOLUTION_SCHEMA_VERSION
from future_intelligence.work_orchestration.durability_migrations import WORK_DURABILITY_SCHEMA_VERSION
from identity.migrations import IDENTITY_SCHEMA_VERSION
from identity.store import IdentityStore
from recovery.backup import BackupService

from .authority import HostContinuationAuthority
from .migrations import AGENT_CONTINUITY_SCHEMA_VERSION
from .models import ContinuityCheckpoint
from .store import ContinuityStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hash(manifest: dict) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckpointArtifact:
    checkpoint: ContinuityCheckpoint
    backup_path: Path


class ContinuityCheckpointService:
    """Creates immutable checkpoint metadata over the existing encrypted backup system."""

    def __init__(
        self,
        *,
        store: ContinuityStore,
        authority: HostContinuationAuthority,
        backups: BackupService,
        identity_store: IdentityStore,
        running_git_revision: str,
    ) -> None:
        self.store = store
        self.authority = authority
        self.backups = backups
        self.identity_store = identity_store
        self.running_git_revision = str(running_git_revision or "").strip()
        if not self.running_git_revision:
            raise ValueError("running_git_revision is required for cross-host continuity")

    @staticmethod
    def supported_schema_versions() -> dict[str, tuple[int, ...]]:
        return {
            "identity": (IDENTITY_SCHEMA_VERSION,),
            "evidence": (EVIDENCE_SCHEMA_VERSION,),
            "evolution": (EVOLUTION_SCHEMA_VERSION,),
            "work": (WORK_DURABILITY_SCHEMA_VERSION,),
            "agent_continuity": (AGENT_CONTINUITY_SCHEMA_VERSION,),
        }

    def create(self) -> CheckpointArtifact:
        lease = self.authority.assert_active()
        active_body = self.identity_store.active_body_revision()
        if active_body is not None and str(active_body["git_revision"]) != self.running_git_revision:
            raise RuntimeError("running revision does not match the active Body revision")

        checkpoint_id = f"ccp_{uuid4().hex}"
        backup = self.backups.create(f"continuity-{checkpoint_id}.paibackup")
        manifest = self.backups.inspect(backup)
        payload = self.backups._decrypt_payload(backup)
        try:
            payload_sha = _sha256(payload)
        finally:
            payload.unlink(missing_ok=True)

        files = tuple(manifest.get("files") or ())
        total_bytes = sum(int(item.get("size", 0)) for item in files if isinstance(item, dict))
        checkpoint = ContinuityCheckpoint(
            id=checkpoint_id,
            source_host_id=lease.host_id,
            authority_epoch=lease.epoch,
            backup_filename=backup.name,
            backup_sha256=_sha256(backup),
            backup_size=backup.stat().st_size,
            payload_sha256=payload_sha,
            data_manifest_hash=_manifest_hash(manifest),
            active_body_revision_id=(str(active_body["revision_id"]) if active_body else None),
            active_body_git_revision=self.running_git_revision,
            schema_versions=self.supported_schema_versions(),
            state_summary={
                "file_count": len(files),
                "snapshot_bytes": total_bytes,
                "backup_encrypted": bool(manifest.get("encrypted")),
                "credentials_rebind_required": True,
                "security_authority_restored": False,
            },
        )
        self.store.record_checkpoint(checkpoint)
        return CheckpointArtifact(checkpoint=checkpoint, backup_path=backup)

    def verify_source_artifact(self, artifact: CheckpointArtifact) -> dict:
        checkpoint = artifact.checkpoint
        backup = Path(artifact.backup_path)
        if not backup.is_file():
            raise FileNotFoundError(backup)
        if backup.name != checkpoint.backup_filename:
            raise ValueError("checkpoint backup filename mismatch")
        if backup.stat().st_size != checkpoint.backup_size:
            raise ValueError("checkpoint backup size mismatch")
        if _sha256(backup) != checkpoint.backup_sha256:
            raise ValueError("checkpoint backup digest mismatch")
        manifest = self.backups.inspect(backup)
        if _manifest_hash(manifest) != checkpoint.data_manifest_hash:
            raise ValueError("checkpoint data manifest mismatch")
        payload = self.backups._decrypt_payload(backup)
        try:
            if _sha256(payload) != checkpoint.payload_sha256:
                raise ValueError("checkpoint portable payload digest mismatch")
        finally:
            payload.unlink(missing_ok=True)
        return manifest
