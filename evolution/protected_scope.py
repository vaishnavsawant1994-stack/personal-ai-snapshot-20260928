from __future__ import annotations

from dataclasses import dataclass


_PROTECTED_PREFIXES = (
    "core/permissions.py",
    "core/durable_approval_runtime.py",
    "security/",
    "identity/body.py",
    "identity/store.py",
    "continuity/authority.py",
    "evolution/protected_scope.py",
    "evolution/handoff.py",
    "evolution/service.py",
    ".github/workflows/",
)

_PROTECTED_PHRASES = (
    "bypass approval",
    "disable approval",
    "grant permission",
    "grant itself",
    "weaken permission",
    "disable audit",
    "delete audit",
    "delete evidence",
    "erase evidence",
    "auto merge",
    "automatic merge",
    "auto deploy",
    "automatic deploy",
    "activate body",
    "body activation",
    "continuation authority",
    "fencing token",
    "vault secret",
    "secret vault",
    "disable security",
    "weaken security",
)


@dataclass(frozen=True)
class ProtectedScopeDecision:
    restricted: bool
    reasons: tuple[str, ...]


def evaluate_protected_scope(
    affected_scope: tuple[str, ...],
    proposed_change: str,
) -> ProtectedScopeDecision:
    reasons: list[str] = []
    for scope in affected_scope:
        normalized = str(scope).strip().lower().replace("\\", "/")
        for prefix in _PROTECTED_PREFIXES:
            if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                reasons.append(f"protected scope: {scope}")
                break
    proposal = " ".join(str(proposed_change).lower().split())
    for phrase in _PROTECTED_PHRASES:
        if phrase in proposal:
            reasons.append(f"protected authority change: {phrase}")
    return ProtectedScopeDecision(bool(reasons), tuple(dict.fromkeys(reasons)))
