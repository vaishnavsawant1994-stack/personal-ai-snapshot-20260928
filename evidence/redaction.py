from __future__ import annotations

import re

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+\-/=]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*['\"]?([^\s,'\"}]+)"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.DOTALL),
        "[REDACTED_PRIVATE_KEY]",
    ),
)


def redact_text(value: object) -> str:
    text = str(value or "")
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def contains_probable_secret(value: object) -> bool:
    text = str(value or "")
    return redact_text(text) != text
