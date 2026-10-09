from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, Sequence


_BRANCH_SAFE = re.compile(r"[^A-Za-z0-9._/-]+")


@dataclass(frozen=True)
class RepositoryWorkspaceSession:
    repository: str
    work_order_id: str
    attempt_id: str
    base_revision: str
    branch_ref: str
    local_path: Path


@dataclass(frozen=True)
class RepositoryStatus:
    revision: str
    dirty: bool
    changes: tuple[str, ...]


class RepositoryWorkspaceProvider(Protocol):
    """Provider contract for isolated repository work.

    Implementations may create local workspaces and local commits. They MUST NOT
    push, merge, deploy, or activate a Vishnu Body revision through this contract.
    """

    repository: str

    def resolve_revision(self, revision: str) -> str: ...

    def read_text_at(self, revision: str, path: str) -> str: ...

    def changed_paths(self, *, base_revision: str, working_revision: str) -> tuple[str, ...]: ...

    def prepare(
        self,
        *,
        repository: str,
        work_order_id: str,
        attempt_id: str,
        base_revision: str,
        branch_ref: str,
    ) -> RepositoryWorkspaceSession: ...

    def resume(
        self,
        *,
        repository: str,
        work_order_id: str,
        attempt_id: str,
        base_revision: str,
        branch_ref: str,
    ) -> RepositoryWorkspaceSession: ...

    def status(self, session: RepositoryWorkspaceSession) -> RepositoryStatus: ...

    def commit_all(self, session: RepositoryWorkspaceSession, *, message: str) -> RepositoryStatus: ...

    def preserve(self, session: RepositoryWorkspaceSession) -> None: ...


class LocalGitRepositoryProvider:
    """Isolated Git worktree provider with no remote mutation methods."""

    def __init__(
        self,
        *,
        repository: str,
        repository_root: str | Path,
        workspace_root: str | Path,
        git_binary: str = "git",
    ) -> None:
        self.repository = str(repository or "").strip()
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.git_binary = str(git_binary or "git")
        if not self.repository:
            raise ValueError("repository is required")
        if not self.repository_root.exists() or not self.repository_root.is_dir():
            raise ValueError("repository_root must be an existing directory")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        top = self._run(("-C", str(self.repository_root), "rev-parse", "--show-toplevel"))
        if Path(top.strip()).resolve() != self.repository_root:
            raise ValueError("repository_root must be the Git repository top level")

    def _run(self, args: Sequence[str], *, cwd: Path | None = None) -> str:
        process = subprocess.run(
            [self.git_binary, *map(str, args)],
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "git command failed").strip()
            raise RuntimeError(error[:2000])
        return process.stdout

    def resolve_revision(self, revision: str) -> str:
        value = str(revision or "").strip()
        if not value:
            raise ValueError("revision is required")
        return self._run(("-C", str(self.repository_root), "rev-parse", "--verify", f"{value}^{{commit}}" )).strip()

    def read_text_at(self, revision: str, path: str) -> str:
        resolved = self.resolve_revision(revision)
        candidate = PurePosixPath(str(path or "").strip())
        if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("repository path must be a safe relative path")
        return self._run(("-C", str(self.repository_root), "show", f"{resolved}:{candidate.as_posix()}"))

    def changed_paths(self, *, base_revision: str, working_revision: str) -> tuple[str, ...]:
        base = self.resolve_revision(base_revision)
        working = self.resolve_revision(working_revision)
        raw = self._run(("-C", str(self.repository_root), "diff", "--name-only", f"{base}..{working}", "--"))
        paths: list[str] = []
        for value in raw.splitlines():
            candidate = PurePosixPath(value.strip())
            if candidate.parts and not candidate.is_absolute() and ".." not in candidate.parts:
                paths.append(candidate.as_posix())
        return tuple(dict.fromkeys(paths))

    @staticmethod
    def normalized_branch(branch_ref: str) -> str:
        value = _BRANCH_SAFE.sub("-", str(branch_ref or "").strip()).strip("-./")
        if not value or ".." in value or value.startswith("-"):
            raise ValueError("invalid branch_ref")
        return value[:180]

    def _workspace_path(self, work_order_id: str, attempt_id: str) -> Path:
        workspace_name = f"{str(work_order_id)[:48]}-{str(attempt_id)[:32]}"
        target = (self.workspace_root / workspace_name).resolve()
        if self.workspace_root not in target.parents:
            raise ValueError("workspace path escapes configured workspace_root")
        return target

    def prepare(
        self,
        *,
        repository: str,
        work_order_id: str,
        attempt_id: str,
        base_revision: str,
        branch_ref: str,
    ) -> RepositoryWorkspaceSession:
        if str(repository) != self.repository:
            raise ValueError("repository is outside the configured provider scope")
        resolved = self.resolve_revision(base_revision)
        branch = self.normalized_branch(branch_ref)
        target = self._workspace_path(work_order_id, attempt_id)
        if target.exists():
            raise FileExistsError(f"workspace already exists: {target.name}")
        self._run(("-C", str(self.repository_root), "worktree", "add", "-b", branch, str(target), resolved))
        return RepositoryWorkspaceSession(
            repository=self.repository,
            work_order_id=str(work_order_id),
            attempt_id=str(attempt_id),
            base_revision=resolved,
            branch_ref=branch,
            local_path=target,
        )

    def resume(
        self,
        *,
        repository: str,
        work_order_id: str,
        attempt_id: str,
        base_revision: str,
        branch_ref: str,
    ) -> RepositoryWorkspaceSession:
        if str(repository) != self.repository:
            raise ValueError("repository is outside the configured provider scope")
        session = RepositoryWorkspaceSession(
            repository=self.repository,
            work_order_id=str(work_order_id),
            attempt_id=str(attempt_id),
            base_revision=self.resolve_revision(base_revision),
            branch_ref=self.normalized_branch(branch_ref),
            local_path=self._workspace_path(work_order_id, attempt_id),
        )
        self._validate_session(session)
        actual_branch = self._run(("-C", str(session.local_path), "branch", "--show-current")).strip()
        if actual_branch != session.branch_ref:
            raise RuntimeError("workspace branch no longer matches durable workspace metadata")
        return session

    def status(self, session: RepositoryWorkspaceSession) -> RepositoryStatus:
        self._validate_session(session)
        revision = self._run(("-C", str(session.local_path), "rev-parse", "HEAD")).strip()
        raw = self._run(("-C", str(session.local_path), "status", "--porcelain=v1", "--untracked-files=all"))
        changes = tuple(line.rstrip() for line in raw.splitlines() if line.strip())
        return RepositoryStatus(revision=revision, dirty=bool(changes), changes=changes)

    def commit_all(self, session: RepositoryWorkspaceSession, *, message: str) -> RepositoryStatus:
        self._validate_session(session)
        summary = str(message or "").strip()
        if not summary:
            raise ValueError("commit message is required")
        before = self.status(session)
        if not before.dirty:
            raise ValueError("workspace has no changes to commit")
        self._run(("-C", str(session.local_path), "add", "--all"))
        self._run(("-C", str(session.local_path), "commit", "-m", summary[:500]))
        after = self.status(session)
        if after.dirty:
            raise RuntimeError("workspace remained dirty after commit")
        if after.revision == session.base_revision:
            raise RuntimeError("commit did not advance repository revision")
        return after

    def preserve(self, session: RepositoryWorkspaceSession) -> None:
        self._validate_session(session)
        # Intentionally no cleanup/removal: failed or review-pending workspaces are
        # preserved for human inspection and recovery. Removal belongs to an
        # explicit maintenance path, never automatic failure handling.

    def _validate_session(self, session: RepositoryWorkspaceSession) -> None:
        if session.repository != self.repository:
            raise ValueError("workspace repository does not match provider")
        resolved = Path(session.local_path).expanduser().resolve()
        if self.workspace_root not in resolved.parents:
            raise ValueError("workspace is outside configured workspace_root")
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(resolved)

    @staticmethod
    def available(git_binary: str = "git") -> bool:
        return shutil.which(git_binary) is not None
