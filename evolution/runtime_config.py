from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CodeBodyRuntimeConfig:
    repository: str
    repository_root: Path | None
    workspace_root: Path
    local_verification_enabled: bool
    verification_timeout_seconds: int

    @classmethod
    def from_environment(cls, *, data_dir: Path) -> "CodeBodyRuntimeConfig":
        raw_root = os.getenv("VISHNU_REPOSITORY_ROOT", "").strip()
        repository_root = Path(raw_root).expanduser().resolve() if raw_root else None
        repository = os.getenv(
            "VISHNU_SOFTWARE_REPOSITORY",
            "vaishnavsawant1994-stack/vishnu",
        ).strip()
        workspace_raw = os.getenv(
            "VISHNU_EVOLUTION_WORKSPACE_ROOT",
            str(Path(data_dir) / "evolution-workspaces"),
        )
        return cls(
            repository=repository,
            repository_root=repository_root,
            workspace_root=Path(workspace_raw).expanduser().resolve(),
            local_verification_enabled=_bool("VISHNU_LOCAL_CODE_VERIFICATION_ENABLED", False),
            verification_timeout_seconds=max(
                30,
                min(3600, int(os.getenv("VISHNU_CODE_VERIFICATION_TIMEOUT_SECONDS", "900"))),
            ),
        )
