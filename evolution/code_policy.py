from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


# These paths define authority, durable evidence, identity, self-evolution,
# capability execution, code-work isolation, release safety, or the regression
# tests that freeze those boundaries. Ordinary evidence-backed evolution work
# may not modify them through the E7 code worker. Changes to these surfaces need
# a separate human-controlled maintenance/release path.
PROTECTED_CODE_PATHS: tuple[str, ...] = (
    "config/vishnu-body.yaml",
    "identity/",
    "evidence/",
    "evolution/",
    "security/",
    "capabilities/",
    "tools/",
    "future_intelligence/work_orchestration/",
    "core/permissions.py",
    "core/security.py",
    "core/storage.py",
    "core/durable_approval_runtime.py",
    "core/p10_approval_continuation.py",
    "agent/durable_executor.py",
    "agent/executor.py",
    "server/evolution_api.py",
    "server/cloud_security.py",
    "server/approval_api.py",
    "server/approvals_center_api.py",
    ".github/workflows/",
    "tests/test_evolution_e5.py",
    "tests/test_evolution_e6_handoff.py",
    "tests/test_evolution_e7_code_body.py",
    "tests/test_evolution_e7_policy.py",
    "tests/test_evolution_e7_review.py",
)


@dataclass(frozen=True)
class CodePolicyDecision:
    allowed: bool
    changed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    reason: str


def evaluate_code_change(paths: Iterable[str]) -> CodePolicyDecision:
    normalized: list[str] = []
    for raw in paths:
        candidate = PurePosixPath(str(raw or "").strip())
        if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
            return CodePolicyDecision(False, tuple(normalized), (str(raw),), "unsafe repository path")
        normalized.append(candidate.as_posix())
    unique = tuple(dict.fromkeys(normalized))
    protected: list[str] = []
    for path in unique:
        for rule in PROTECTED_CODE_PATHS:
            if rule.endswith("/"):
                if path.startswith(rule):
                    protected.append(path)
                    break
            elif path == rule:
                protected.append(path)
                break
    return CodePolicyDecision(
        allowed=not protected,
        changed_paths=unique,
        protected_paths=tuple(dict.fromkeys(protected)),
        reason="change is within ordinary evolution scope" if not protected else "change touches protected authority/safety scope",
    )
