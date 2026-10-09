from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


PROTECTED_PATTERNS: dict[str, tuple[str, ...]] = {
    "owner_authority": ("owner authority", "owner control", "ownership authority"),
    "approval_bypass": ("approval bypass", "skip approval", "disable approval", "auto approve"),
    "vault_secrets": ("vault", "secret", "credential", "token storage", "password"),
    "permission_enforcement": ("permission", "authorization", "authorize", "capability grant"),
    "audit_evidence_integrity": ("delete evidence", "erase evidence", "audit deletion", "disable audit"),
    "evolution_safety": ("evolution safety", "protected scope", "self approval", "self-adopt"),
    "continuation_authority": ("continuation authority", "host fencing", "source fencing"),
    "authentication": ("authentication", "sign-in", "reauthentication", "2fa", "two-step"),
    "security_policy": ("security policy", "security guardrail", "emergency stop"),
    "migration_history": ("migration history", "schema migration rollback history"),
    "safety_tests": ("safety test", "conformance test", "security test bypass"),
    "automatic_adoption": ("auto merge", "automatic merge", "auto deploy", "automatic deploy", "auto activate"),
}


@dataclass(frozen=True)
class ProtectedScopeMatch:
    key: str
    phrase: str


def protected_scope_matches(values: Iterable[str]) -> tuple[ProtectedScopeMatch, ...]:
    haystack = "\n".join(str(value).lower() for value in values if str(value).strip())
    matches: list[ProtectedScopeMatch] = []
    for key, phrases in PROTECTED_PATTERNS.items():
        for phrase in phrases:
            if phrase in haystack:
                matches.append(ProtectedScopeMatch(key=key, phrase=phrase))
                break
    return tuple(matches)
