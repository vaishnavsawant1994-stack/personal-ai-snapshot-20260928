from __future__ import annotations

from dataclasses import asdict, dataclass
import threading
import time
import uuid


@dataclass(frozen=True)
class QuotaLimits:
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    tokens_per_minute: int | None = None
    tokens_per_day: int | None = None
    concurrent_requests: int | None = None


@dataclass
class _Window:
    minute_started: float
    day_started: float
    rpm: int = 0
    rpd: int = 0
    tpm: int = 0
    tpd: int = 0
    concurrent: int = 0


@dataclass(frozen=True)
class QuotaReservation:
    reservation_id: str
    key: str
    tokens: int
    created_at: float


class QuotaExceeded(RuntimeError):
    pass


class QuotaEngine:
    """In-process quota reservations with race-safe accounting.

    Distributed deployments can replace this implementation behind the same
    reserve/commit/release contract with a transactional shared store.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._limits: dict[str, QuotaLimits] = {}
        self._windows: dict[str, _Window] = {}
        self._reservations: dict[str, QuotaReservation] = {}

    @staticmethod
    def _fresh(now: float) -> _Window:
        return _Window(now, now)

    def configure(self, key: str, limits: QuotaLimits) -> None:
        with self._lock:
            self._limits[key] = limits
            self._windows.setdefault(key, self._fresh(time.time()))

    def _window(self, key: str, now: float) -> _Window:
        row = self._windows.setdefault(key, self._fresh(now))
        if now - row.minute_started >= 60:
            row.minute_started, row.rpm, row.tpm = now, 0, 0
        if now - row.day_started >= 86400:
            row.day_started, row.rpd, row.tpd = now, 0, 0
        return row

    @staticmethod
    def _over(value: int, limit: int | None) -> bool:
        return limit is not None and value > limit

    def can_reserve(self, key: str, *, tokens: int = 0) -> bool:
        with self._lock:
            limits = self._limits.get(key, QuotaLimits())
            row = self._window(key, time.time())
            return not any((
                self._over(row.rpm + 1, limits.requests_per_minute),
                self._over(row.rpd + 1, limits.requests_per_day),
                self._over(row.tpm + max(0, tokens), limits.tokens_per_minute),
                self._over(row.tpd + max(0, tokens), limits.tokens_per_day),
                self._over(row.concurrent + 1, limits.concurrent_requests),
            ))

    def reserve(self, key: str, *, tokens: int = 0) -> QuotaReservation:
        tokens = max(0, int(tokens))
        with self._lock:
            if not self.can_reserve(key, tokens=tokens):
                raise QuotaExceeded(f'quota unavailable for {key}')
            row = self._window(key, time.time())
            row.rpm += 1; row.rpd += 1; row.tpm += tokens; row.tpd += tokens; row.concurrent += 1
            reservation = QuotaReservation(f'quota_{uuid.uuid4().hex}', key, tokens, time.time())
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def commit(self, reservation_id: str, *, actual_tokens: int | None = None) -> None:
        with self._lock:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation is None:
                return
            row = self._window(reservation.key, time.time())
            row.concurrent = max(0, row.concurrent - 1)
            if actual_tokens is not None:
                delta = max(0, int(actual_tokens)) - reservation.tokens
                row.tpm = max(0, row.tpm + delta)
                row.tpd = max(0, row.tpd + delta)

    def release(self, reservation_id: str, *, count_request: bool = True) -> None:
        with self._lock:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation is None:
                return
            row = self._window(reservation.key, time.time())
            row.concurrent = max(0, row.concurrent - 1)
            row.tpm = max(0, row.tpm - reservation.tokens)
            row.tpd = max(0, row.tpd - reservation.tokens)
            if not count_request:
                row.rpm = max(0, row.rpm - 1)
                row.rpd = max(0, row.rpd - 1)

    def snapshot(self, key: str) -> dict:
        with self._lock:
            limits = self._limits.get(key, QuotaLimits())
            row = self._window(key, time.time())
            return {'key': key, 'limits': asdict(limits), 'usage': {
                'requests_minute': row.rpm, 'requests_day': row.rpd,
                'tokens_minute': row.tpm, 'tokens_day': row.tpd,
                'concurrent_requests': row.concurrent,
            }}
