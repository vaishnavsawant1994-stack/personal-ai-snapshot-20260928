from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from future_intelligence.work_orchestration.repository import (
    RepositoryWorkspaceProvider,
    RepositoryWorkspaceSession,
)
from identity import BodyManifest

from .code_policy import evaluate_code_change


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


class GuardedVerificationProvider:
    """Fail closed on protected diffs before candidate code is executed."""

    def __init__(
        self,
        *,
        repository_provider: RepositoryWorkspaceProvider,
        inner: VerificationProvider,
        body_manifest_path: str = "config/vishnu-body.yaml",
    ) -> None:
        self.repository_provider = repository_provider
        self.inner = inner
        self.body_manifest_path = str(body_manifest_path)

    @staticmethod
    def _check(name: str, passed: bool, details: str) -> VerificationCheck:
        digest = hashlib.sha256(details.encode("utf-8", errors="replace")).hexdigest()
        return VerificationCheck(
            name=name,
            command=("internal-policy-check",),
            passed=bool(passed),
            returncode=0 if passed else 1,
            duration_ms=0,
            output_hash=digest,
            output_excerpt=details[:4000],
        )

    def verify(self, session: RepositoryWorkspaceSession, *, revision: str) -> VerificationReport:
        changed = self.repository_provider.changed_paths(
            base_revision=session.base_revision,
            working_revision=revision,
        )
        policy = evaluate_code_change(changed)
        policy_check = self._check(
            "protected-code-scope",
            policy.allowed,
            policy.reason + (f"; protected={','.join(policy.protected_paths)}" if policy.protected_paths else ""),
        )
        if not policy.allowed:
            return VerificationReport(revision=str(revision), checks=(policy_check,))

        base_raw = self.repository_provider.read_text_at(session.base_revision, self.body_manifest_path)
        try:
            base_manifest = BodyManifest.from_dict(json.loads(base_raw))
            working_manifest = BodyManifest.load(Path(session.local_path) / self.body_manifest_path)
            manifest_same = base_manifest.manifest_hash == working_manifest.manifest_hash
            manifest_details = "Body manifest unchanged" if manifest_same else "Body manifest changed in ordinary evolution work"
        except Exception as exc:
            manifest_same = False
            manifest_details = f"Body manifest validation failed: {type(exc).__name__}"
        manifest_check = self._check("body-manifest-integrity", manifest_same, manifest_details)
        if not manifest_same:
            return VerificationReport(revision=str(revision), checks=(policy_check, manifest_check))

        inner = self.inner.verify(session, revision=revision)
        if inner.revision != str(revision):
            mismatch = self._check("verification-revision-binding", False, "inner verifier returned a different revision")
            return VerificationReport(revision=str(revision), checks=(policy_check, manifest_check, mismatch))
        return VerificationReport(
            revision=str(revision),
            checks=(policy_check, manifest_check, *inner.checks),
        )


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
