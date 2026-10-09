from __future__ import annotations

import os
import subprocess
from pathlib import Path


_RUNNING_REVISION_ENV = (
    "VISHNU_RUNNING_GIT_REVISION",
    "GITHUB_SHA",
    "RAILWAY_GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
)


def detect_running_git_revision(*, repository_root: str | Path | None = None) -> str | None:
    """Return an exact running Git commit or None; never guess from a branch name."""

    for name in _RUNNING_REVISION_ENV:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    if repository_root is None:
        return None
    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        return None
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    value = (process.stdout or "").strip()
    return value or None
