from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import threading
import time
from typing import Callable, Any


class SchedulerError(RuntimeError):
    pass


class DependencyCycle(SchedulerError):
    pass


@dataclass(frozen=True)
class ScheduledTask:
    task_id: str
    payload: Any
    depends_on: tuple[str, ...] = ()
    priority: int = 0
    timeout_seconds: float | None = None
    continue_on_failure: bool = False


@dataclass
class TaskResult:
    task_id: str
    status: str
    value: Any = None
    error_type: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class ScheduleResult:
    results: dict[str, TaskResult] = field(default_factory=dict)

    @property
    def completed(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.results.items() if value.status == 'completed')

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.results.items() if value.status == 'failed')

    @property
    def blocked(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.results.items() if value.status == 'blocked')


class ParallelTaskScheduler:
    """Bounded dependency scheduler for independent Vishnu work.

    It owns ordering/concurrency only. Tool permissions, approvals and execution
    authority remain with the supplied executor callback.
    """

    def __init__(self, *, max_parallel: int = 4):
        self.max_parallel = max(1, min(32, int(max_parallel)))

    @staticmethod
    def _validate(tasks: tuple[ScheduledTask, ...]) -> dict[str, ScheduledTask]:
        by_id: dict[str, ScheduledTask] = {}
        for task in tasks:
            if not task.task_id or task.task_id in by_id:
                raise SchedulerError('task ids must be unique and non-empty')
            by_id[task.task_id] = task
        for task in tasks:
            missing = [dependency for dependency in task.depends_on if dependency not in by_id]
            if missing:
                raise SchedulerError(f'{task.task_id} depends on unknown tasks')
        visiting, visited = set(), set()
        def walk(task_id: str):
            if task_id in visiting: raise DependencyCycle('task dependency cycle detected')
            if task_id in visited: return
            visiting.add(task_id)
            for dependency in by_id[task_id].depends_on: walk(dependency)
            visiting.remove(task_id); visited.add(task_id)
        for task_id in by_id: walk(task_id)
        return by_id

    def run(self, tasks, executor: Callable[[ScheduledTask], Any], *, cancel_event: threading.Event | None = None, on_state: Callable[[TaskResult], None] | None = None) -> ScheduleResult:
        tasks = tuple(tasks)
        by_id = self._validate(tasks)
        result = ScheduleResult({task_id: TaskResult(task_id, 'pending') for task_id in by_id})
        pending = set(by_id)
        running: dict[Future, ScheduledTask] = {}

        def emit(row: TaskResult):
            if on_state: on_state(row)

        def invoke(task: ScheduledTask):
            started = time.time()
            return started, executor(task)

        with ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix='vishnu-agent') as pool:
            while pending or running:
                if cancel_event is not None and cancel_event.is_set():
                    for task_id in list(pending):
                        row = result.results[task_id]; row.status = 'cancelled'; row.completed_at = time.time(); emit(row)
                    for future in running: future.cancel()
                    pending.clear()
                    break

                made_progress = False
                ordered = sorted((by_id[task_id] for task_id in pending), key=lambda item: (-item.priority, item.task_id))
                for task in ordered:
                    dependencies = [result.results[item] for item in task.depends_on]
                    failed_dependencies = [item for item in dependencies if item.status in {'failed', 'blocked', 'cancelled'}]
                    if failed_dependencies and not task.continue_on_failure:
                        row = result.results[task.task_id]; row.status = 'blocked'; row.error_type = 'dependency_failed'; row.completed_at = time.time()
                        pending.remove(task.task_id); emit(row); made_progress = True; continue
                    if not all(item.status == 'completed' or (task.continue_on_failure and item.status in {'failed','blocked','cancelled'}) for item in dependencies):
                        continue
                    if len(running) >= self.max_parallel: break
                    row = result.results[task.task_id]; row.status = 'running'; row.started_at = time.time(); emit(row)
                    running[pool.submit(invoke, task)] = task
                    pending.remove(task.task_id); made_progress = True

                if not running:
                    if pending and not made_progress:
                        raise SchedulerError('scheduler made no progress')
                    continue

                done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    task = running.pop(future); row = result.results[task.task_id]
                    try:
                        started, value = future.result(timeout=task.timeout_seconds)
                        row.started_at = started; row.value = value; row.status = 'completed'
                    except Exception as exc:
                        row.status = 'failed'; row.error_type = type(exc).__name__
                    row.completed_at = time.time(); emit(row)
        return result
