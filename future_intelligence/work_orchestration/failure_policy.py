from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    UPSTREAM = "upstream"
    AUTH = "auth"
    PERMISSION = "permission"
    VALIDATION = "validation"
    POLICY = "policy"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    DIRTY_WORKSPACE = "dirty_workspace"
    UNKNOWN_EFFECT = "unknown_effect"
    UNKNOWN = "unknown"


class RetryDisposition(StrEnum):
    AUTO_RETRY = "auto_retry"
    EXPLICIT_RETRY_ONLY = "explicit_retry_only"
    RECOVERY_REQUIRED = "recovery_required"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class WorkFailure:
    failure_class: FailureClass
    code: str
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


_AUTO_RETRY = frozenset({
    FailureClass.TRANSIENT,
    FailureClass.RATE_LIMIT,
    FailureClass.NETWORK,
    FailureClass.UPSTREAM,
})

_EXPLICIT_ONLY = frozenset({
    FailureClass.AUTH,
    FailureClass.PERMISSION,
    FailureClass.VALIDATION,
    FailureClass.POLICY,
    FailureClass.BUDGET,
    FailureClass.TIMEOUT,
    FailureClass.DIRTY_WORKSPACE,
    FailureClass.UNKNOWN,
})


def retry_disposition(
    failure_class: FailureClass,
    *,
    attempt_number: int,
    max_attempts: int = 3,
) -> RetryDisposition:
    if attempt_number < 1:
        raise ValueError("attempt_number must be at least 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if failure_class is FailureClass.UNKNOWN_EFFECT:
        return RetryDisposition.RECOVERY_REQUIRED
    if failure_class in _AUTO_RETRY:
        return (
            RetryDisposition.AUTO_RETRY
            if attempt_number < max_attempts
            else RetryDisposition.EXPLICIT_RETRY_ONLY
        )
    if failure_class in _EXPLICIT_ONLY:
        return RetryDisposition.EXPLICIT_RETRY_ONLY
    return RetryDisposition.TERMINAL
