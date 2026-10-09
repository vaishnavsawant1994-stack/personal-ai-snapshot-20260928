from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from future_intelligence.work_orchestration.repository import RepositoryWorkspaceSession


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    command: tuple[str, ...]
    passed: bool
    returncode: int
    duration_ms: int
    output_hash: str
    output_excerpt: str


@dataclass(frozen=True)
class VerificationReport:
    revision: str
    checks: tuple[VerificationCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def report_hash(self) -> str:
        payload = {
            "revision": self.revision,
            "checks": [
                {
                    "name": check.name,
                    "command": list(check.command),
                    "passed": check.passed,
                    "returncode": check.returncode,
                    "duration_ms": check.duration_ms,
                    "output_hash": check.output_hash,
                }
                for check in self.checks
            ],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class VerificationProvider(Protocol):
    def verify(self, session: RepositoryWorkspaceSession, *, revision: str) -> VerificationReport: ...


class LocalSubprocessVerificationProvider:
    """Explicitly enabled no-shell verification for trusted local development.

    Commands are supplied by trusted configuration when the provider is created;
    they are never synthesized from candidate text or model output.
    """

    def __init__(
        self,
        commands: Sequence[tuple[str, Sequence[str]]],
        *,
        enabled: bool = False,
        timeout_seconds: int = 900,
        max_output_chars: int = 12000,
    ) -> None:
        if not enabled:
            raise PermissionError("local code verification is disabled")
        normalized: list[tuple[str, tuple[str, ...]]] = []
        for name, command in commands:
            label = str(name or "").strip()
            args = tuple(str(part) for part in command if str(part))
            if not label or not args:
                raise ValueError("verification command name and argv are required")
            normalized.append((label, args))
        if not normalized:
            raise ValueError("at least one verification command is required")
        self.commands = tuple(normalized)
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_chars = max(256, int(max_output_chars))

    def verify(self, session: RepositoryWorkspaceSession, *, revision: str) -> VerificationReport:
        root = Path(session.local_path).resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(root)
        checks: list[VerificationCheck] = []
        for name, command in self.commands:
            started = time.perf_counter()
            process = subprocess.run(
                list(command),
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            duration = int((time.perf_counter() - started) * 1000)
            combined = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
            digest = hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest()
            excerpt = combined[-self.max_output_chars :]
            checks.append(
                VerificationCheck(
                    name=name,
                    command=command,
                    passed=process.returncode == 0,
                    returncode=int(process.returncode),
                    duration_ms=duration,
                    output_hash=digest,
                    output_excerpt=excerpt,
                )
            )
            if process.returncode != 0:
                break
        return VerificationReport(revision=str(revision), checks=tuple(checks))
