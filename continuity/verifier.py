from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from .models import ContinuityCheckpoint


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hash(manifest: dict) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ContinuityCompatibilityError(RuntimeError):
    pass


class ContinuityCompatibilityVerifier:
    """Fail-closed verifier for Body and durable-state contract compatibility."""

    def __init__(self, supported_schema_versions: Mapping[str, Sequence[int]]) -> None:
        self.supported = {
            str(key): tuple(sorted({int(value) for value in values}))
            for key, values in supported_schema_versions.items()
        }

    def verify_checkpoint(
        self,
        checkpoint: ContinuityCheckpoint,
        *,
        running_git_revision: str | None,
    ) -> None:
        if checkpoint.authority_epoch < 1:
            raise ContinuityCompatibilityError("checkpoint authority epoch is invalid")
        if checkpoint.backup_size <= 0:
            raise ContinuityCompatibilityError("checkpoint backup is empty")
        for label, value in (
            ("backup_sha256", checkpoint.backup_sha256),
            ("payload_sha256", checkpoint.payload_sha256),
            ("data_manifest_hash", checkpoint.data_manifest_hash),
            ("checkpoint_hash", checkpoint.checkpoint_hash),
        ):
            if len(str(value)) != 64 or any(ch not in "0123456789abcdef" for ch in str(value).lower()):
                raise ContinuityCompatibilityError(f"checkpoint {label} is invalid")

        for name, source_versions in checkpoint.schema_versions.items():
            versions = tuple(int(value) for value in source_versions)
            if not versions:
                raise ContinuityCompatibilityError(f"checkpoint schema {name} is empty")
            supported = self.supported.get(str(name))
            if not supported:
                raise ContinuityCompatibilityError(f"target does not support checkpoint schema {name}")
            if max(versions) > max(supported):
                raise ContinuityCompatibilityError(
                    f"checkpoint schema {name} is newer than the target runtime"
                )

        expected_body = str(checkpoint.active_body_git_revision or "").strip()
        running = str(running_git_revision or "").strip()
        if expected_body and running != expected_body:
            raise ContinuityCompatibilityError(
                "target runtime does not match checkpoint active Body revision"
            )

    def verify_payload(
        self,
        checkpoint: ContinuityCheckpoint,
        *,
        payload: str | Path,
        manifest: dict,
    ) -> None:
        path = Path(payload)
        if not path.is_file():
            raise ContinuityCompatibilityError("continuity payload is missing")
        if _sha256(path) != checkpoint.payload_sha256:
            raise ContinuityCompatibilityError("continuity payload digest mismatch")
        if _manifest_hash(manifest) != checkpoint.data_manifest_hash:
            raise ContinuityCompatibilityError("continuity data manifest mismatch")
