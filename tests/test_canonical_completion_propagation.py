from __future__ import annotations

from future_intelligence.work_orchestration.completion_propagation import (
    bind_notifications,
    canonical_live_projection,
    canonical_task_rows,
    canonicalize_global_summary,
)


def _p10(raw_dependency_status="COMPLETED"):
    return {
        "id": "plan-1",
        "state": "COMPLETED",
        "replan_count": 0,
        "updated_at": "2026-10-09T10:00:00+00:00",
        "tasks": [
            {"id": "build", "status": raw_dependency_status, "dependencies": []},
            {"id": "deploy", "status": "WAITING", "dependencies": ["build"]},
        ],
    }


def _work(build_status="verifying", passed=False, plan_status="reviewing"):
    return {
        "id": "work-1",
        "status": plan_status,
        "completion": {"complete": plan_status == "completed", "state": plan_status},
        "work_orders": [
            {
                "id": "wo-build",
                "status": build_status,
                "execution_status": "completed",
                "completion": {"passed": passed, "state": build_status, "score": 80.0},
                "resource_scope": {"metadata": {"p10_task_id": "build"}},
            },
            {
                "id": "wo-deploy",
                "status": "waiting",
                "resource_scope": {"metadata": {"p10_task_id": "deploy"}},
            },
        ],
    }


def test_raw_p10_completed_does_not_unlock_dependency_without_completion_judge():
    rows = canonical_task_rows(_p10(), _work())
    by_task = {row["task_id"]: row for row in rows}
    assert by_task["build"]["execution_status"] == "COMPLETED"
    assert by_task["build"]["status"] == "VERIFYING"

    live = canonical_live_projection(_p10(), _work())
    assert live["state"] == "REVIEWING"
    assert live["task_counts"]["VERIFYING"] == 1
    assert live["ready_task_ids"] == []
    assert live["completion_authority"] == "deterministic_completion_judge"


def test_dependency_becomes_ready_only_after_canonical_completion_passes():
    work = _work(build_status="completed", passed=True, plan_status="reviewing")
    live = canonical_live_projection(_p10(), work)
    assert live["task_counts"]["COMPLETED"] == 1
    assert live["ready_task_ids"] == ["deploy"]


class _Autonomy:
    def __init__(self, work_plan):
        self._p10 = _p10()
        self._work = work_plan

    def plan(self, plan_id, *, owner_id):
        assert plan_id == "plan-1"
        assert owner_id == "owner"
        return self._p10

    def work_plan(self, plan_id, *, owner_id):
        assert plan_id == "plan-1"
        assert owner_id == "owner"
        return self._work


def test_global_summary_recomputes_completed_ready_and_project_state_from_judge():
    summary = {
        "projects_total": 1,
        "projects_with_work": 1,
        "active_projects": 0,
        "task_counts": {"COMPLETED": 1, "WAITING": 1},
        "counts": {"completed": 1, "ready": 1, "work_orders": 2},
        "living": {"state": "completed", "detail": "raw"},
        "projects": [
            {
                "project_id": "project-1",
                "project_name": "Launch",
                "plan_id": "plan-1",
                "state": "COMPLETED",
                "task_counts": {"COMPLETED": 1, "WAITING": 1},
            }
        ],
        "work_orders": [
            {
                "project_id": "project-1",
                "project_name": "Launch",
                "plan_id": "plan-1",
                "task_id": "build",
                "status": "COMPLETED",
                "ready": False,
                "title": "Build",
            },
            {
                "project_id": "project-1",
                "project_name": "Launch",
                "plan_id": "plan-1",
                "task_id": "deploy",
                "status": "WAITING",
                "ready": True,
                "title": "Deploy",
            },
        ],
    }

    result = canonicalize_global_summary(
        summary,
        _Autonomy(_work()),
        living_state_fn=lambda **counts: (
            "verifying" if counts["verifying"] else "idle",
            "canonical",
        ),
    )

    build = next(item for item in result["work_orders"] if item["task_id"] == "build")
    deploy = next(item for item in result["work_orders"] if item["task_id"] == "deploy")
    assert build["status"] == "VERIFYING"
    assert deploy["ready"] is False
    assert result["counts"]["completed"] == 0
    assert result["counts"]["ready"] == 0
    assert result["counts"]["verifying"] == 1
    assert result["active_projects"] == 1
    assert result["projects"][0]["state"] == "REVIEWING"
    assert result["living"]["state"] == "verifying"


class _Events:
    def __init__(self):
        self.handlers = {}

    def subscribe(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)
        return lambda: None

    def emit(self, name, **payload):
        for handler in list(self.handlers.get(name, [])):
            handler(payload)


class _Bridge:
    def __init__(self):
        self._P10_STATE_EVENTS = {"COMPLETED": "work.order.completed", "BLOCKED": "work.order.blocked"}
        self._unsubscribers = []
        self.events = _Events()
        self.emitted = []

    def _emit(self, name, source):
        self.emitted.append((name, dict(source)))


class _CompletionAutonomy:
    def __init__(self, passed):
        self.passed = passed

    def work_order_completion(self, plan_id, task_id, *, owner_id):
        return {
            "passed": self.passed,
            "state": "completed" if self.passed else "verifying",
            "score": 100 if self.passed else 50,
        }

    def work_completion(self, plan_id, *, owner_id):
        return {
            "complete": self.passed,
            "state": "completed" if self.passed else "verifying",
            "score": 100 if self.passed else 50,
        }


def test_notification_bridge_suppresses_raw_completion_until_judge_passes():
    bridge = _Bridge()
    bind_notifications(bridge, _CompletionAutonomy(False))
    assert "COMPLETED" not in bridge._P10_STATE_EVENTS
    bridge.events.emit("work_completion_observed", plan_id="plan-1", task_id="build")
    assert bridge.emitted == []


def test_notification_bridge_emits_work_and_goal_completion_after_judge_passes():
    bridge = _Bridge()
    bind_notifications(bridge, _CompletionAutonomy(True))
    bridge.events.emit("work_completion_observed", plan_id="plan-1", task_id="build")
    names = [name for name, _ in bridge.emitted]
    assert names == ["work.order.completed", "work.goal.completed"]
    assert bridge.emitted[1][1]["task_id"] is None
