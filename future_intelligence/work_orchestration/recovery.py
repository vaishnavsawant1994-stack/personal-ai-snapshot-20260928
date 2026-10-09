from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RecoveryReason(StrEnum):
    LEASE_EXPIRED = "lease_expired"
    WORKER_LOST = "worker_lost"
    UNKNOWN_EFFECT = "unknown_effect"
    INTERRUPTED_VERIFICATION = "interrupted_verification"


@dataclass(frozen=True)
class RecoveryDecision:
    work_order_id: str
    attempt_id: str | None
    reason: RecoveryReason
    retry_allowed: bool = False


def requires_manual_recovery(reason: RecoveryReason) -> bool:
    return reason in {
        RecoveryReason.LEASE_EXPIRED,
        RecoveryReason.WORKER_LOST,
        RecoveryReason.UNKNOWN_EFFECT,
        RecoveryReason.INTERRUPTED_VERIFICATION,
    }
