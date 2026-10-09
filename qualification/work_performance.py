from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from time import perf_counter
from typing import Any, Callable


@dataclass(frozen=True)
class PerformanceMeasurement:
    name: str
    samples_ms: tuple[float, ...]
    max_allowed_ms: float

    @property
    def median_ms(self) -> float:
        return median(self.samples_ms) if self.samples_ms else 0.0

    @property
    def mean_ms(self) -> float:
        return mean(self.samples_ms) if self.samples_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms) if self.samples_ms else 0.0

    @property
    def passed(self) -> bool:
        return self.max_ms <= self.max_allowed_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "samples_ms": list(self.samples_ms),
            "median_ms": self.median_ms,
            "mean_ms": self.mean_ms,
            "max_ms": self.max_ms,
            "max_allowed_ms": self.max_allowed_ms,
            "passed": self.passed,
        }


def measure(
    name: str,
    operation: Callable[[], Any],
    *,
    iterations: int = 5,
    warmup: int = 1,
    max_allowed_ms: float = 1000.0,
) -> PerformanceMeasurement:
    """Measure deterministic Work read paths without changing runtime authority."""
    for _ in range(max(0, int(warmup))):
        operation()
    samples = []
    for _ in range(max(1, int(iterations))):
        started = perf_counter()
        operation()
        samples.append((perf_counter() - started) * 1000.0)
    return PerformanceMeasurement(name, tuple(samples), float(max_allowed_ms))


def assert_measurement(measurement: PerformanceMeasurement) -> PerformanceMeasurement:
    if not measurement.passed:
        raise AssertionError(
            f"{measurement.name} exceeded {measurement.max_allowed_ms:.1f}ms: "
            f"max={measurement.max_ms:.1f}ms median={measurement.median_ms:.1f}ms"
        )
    return measurement


def query_plan_uses_index(connection, sql: str, params: tuple[Any, ...] = ()) -> bool:
    rows = connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    detail = " ".join(str(row[-1]).upper() for row in rows)
    return "USING INDEX" in detail or "USING COVERING INDEX" in detail
