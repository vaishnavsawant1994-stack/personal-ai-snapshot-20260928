from __future__ import annotations

from dataclasses import asdict, dataclass
import threading
import time
import uuid


@dataclass(frozen=True)
class BudgetLimits:
    max_cost: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_requests: int | None = None
    max_retries: int | None = None
    max_parallel_agents: int | None = None
    max_parallel_model_calls: int | None = None
    deadline_at: float | None = None


@dataclass
class BudgetUsage:
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    retries: int = 0
    active_agents: int = 0
    active_model_calls: int = 0


@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: str
    key: str
    cost: float
    input_tokens: int
    output_tokens: int
    model_call: bool
    agent_slot: bool


class BudgetExceeded(RuntimeError):
    pass


class BudgetEngine:
    """Hierarchical execution-budget accounting.

    Keys are arbitrary scopes such as global/user/project/execution/agent/task.
    A reservation can atomically consume several scopes so child work cannot
    escape a parent execution budget.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._limits: dict[str, BudgetLimits] = {}
        self._usage: dict[str, BudgetUsage] = {}
        self._reservations: dict[str, tuple[BudgetReservation, tuple[str, ...]]] = {}

    def configure(self, key: str, limits: BudgetLimits) -> None:
        with self._lock:
            self._limits[key] = limits
            self._usage.setdefault(key, BudgetUsage())

    @staticmethod
    def _violations(limits: BudgetLimits, usage: BudgetUsage, *, cost: float, input_tokens: int, output_tokens: int, model_call: bool, agent_slot: bool, retries: int) -> list[str]:
        failures = []
        if limits.deadline_at is not None and time.time() >= limits.deadline_at: failures.append('deadline')
        if limits.max_cost is not None and usage.cost + cost > limits.max_cost: failures.append('cost')
        if limits.max_input_tokens is not None and usage.input_tokens + input_tokens > limits.max_input_tokens: failures.append('input_tokens')
        if limits.max_output_tokens is not None and usage.output_tokens + output_tokens > limits.max_output_tokens: failures.append('output_tokens')
        if limits.max_requests is not None and usage.requests + int(model_call) > limits.max_requests: failures.append('requests')
        if limits.max_retries is not None and usage.retries + retries > limits.max_retries: failures.append('retries')
        if limits.max_parallel_agents is not None and usage.active_agents + int(agent_slot) > limits.max_parallel_agents: failures.append('parallel_agents')
        if limits.max_parallel_model_calls is not None and usage.active_model_calls + int(model_call) > limits.max_parallel_model_calls: failures.append('parallel_model_calls')
        return failures

    def reserve(self, scopes: tuple[str, ...] | list[str], *, cost: float = 0.0, input_tokens: int = 0, output_tokens: int = 0, model_call: bool = True, agent_slot: bool = False, retries: int = 0) -> BudgetReservation:
        scopes = tuple(dict.fromkeys(str(scope) for scope in scopes if scope))
        if not scopes:
            raise ValueError('at least one budget scope is required')
        cost = max(0.0, float(cost)); input_tokens = max(0, int(input_tokens)); output_tokens = max(0, int(output_tokens)); retries = max(0, int(retries))
        with self._lock:
            for scope in scopes:
                limits = self._limits.get(scope, BudgetLimits())
                usage = self._usage.setdefault(scope, BudgetUsage())
                failures = self._violations(limits, usage, cost=cost, input_tokens=input_tokens, output_tokens=output_tokens, model_call=model_call, agent_slot=agent_slot, retries=retries)
                if failures:
                    raise BudgetExceeded(f"budget exhausted for {scope}: {','.join(failures)}")
            for scope in scopes:
                usage = self._usage.setdefault(scope, BudgetUsage())
                usage.cost += cost; usage.input_tokens += input_tokens; usage.output_tokens += output_tokens
                usage.requests += int(model_call); usage.retries += retries
                usage.active_model_calls += int(model_call); usage.active_agents += int(agent_slot)
            reservation = BudgetReservation(f'budget_{uuid.uuid4().hex}', scopes[-1], cost, input_tokens, output_tokens, model_call, agent_slot)
            self._reservations[reservation.reservation_id] = (reservation, scopes)
            return reservation

    def commit(self, reservation_id: str, *, actual_cost: float | None = None, actual_input_tokens: int | None = None, actual_output_tokens: int | None = None) -> None:
        with self._lock:
            stored = self._reservations.pop(reservation_id, None)
            if stored is None: return
            reservation, scopes = stored
            cost = reservation.cost if actual_cost is None else max(0.0, float(actual_cost))
            inp = reservation.input_tokens if actual_input_tokens is None else max(0, int(actual_input_tokens))
            out = reservation.output_tokens if actual_output_tokens is None else max(0, int(actual_output_tokens))
            for scope in scopes:
                usage = self._usage[scope]
                usage.cost = max(0.0, usage.cost + cost - reservation.cost)
                usage.input_tokens = max(0, usage.input_tokens + inp - reservation.input_tokens)
                usage.output_tokens = max(0, usage.output_tokens + out - reservation.output_tokens)
                usage.active_model_calls = max(0, usage.active_model_calls - int(reservation.model_call))
                usage.active_agents = max(0, usage.active_agents - int(reservation.agent_slot))

    def release(self, reservation_id: str, *, count_request: bool = True) -> None:
        with self._lock:
            stored = self._reservations.pop(reservation_id, None)
            if stored is None: return
            reservation, scopes = stored
            for scope in scopes:
                usage = self._usage[scope]
                usage.cost = max(0.0, usage.cost - reservation.cost)
                usage.input_tokens = max(0, usage.input_tokens - reservation.input_tokens)
                usage.output_tokens = max(0, usage.output_tokens - reservation.output_tokens)
                usage.active_model_calls = max(0, usage.active_model_calls - int(reservation.model_call))
                usage.active_agents = max(0, usage.active_agents - int(reservation.agent_slot))
                if not count_request:
                    usage.requests = max(0, usage.requests - int(reservation.model_call))

    def snapshot(self, key: str) -> dict:
        with self._lock:
            return {'key': key, 'limits': asdict(self._limits.get(key, BudgetLimits())), 'usage': asdict(self._usage.get(key, BudgetUsage()))}
