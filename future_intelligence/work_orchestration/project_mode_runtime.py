from __future__ import annotations

from typing import Any

from projects.autonomy_modes import ProjectAutonomyMode, ProjectAutonomyModeStore


_STOP_STATES = {
    "WAITING_APPROVAL",
    "VERIFYING",
    "RECOVERING",
    "RECOVERY_REQUIRED",
    "UNCERTAIN",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "COMPLETED",
    "PAUSED",
}


def install(cls) -> None:
    """Enforce durable Project autonomy modes around the existing P10 execution path."""
    if getattr(cls, "_project_autonomy_modes_installed", False):
        return

    original_execute_task = cls.execute_task
    original_status = cls.status

    def _project_id(self, plan_id: str) -> str | None:
        bridge = getattr(self, "_work_bridge", None)
        if bridge is None:
            return None
        plan = bridge.work_plan_for_p10(plan_id)
        return str(plan.project_id) if plan is not None and plan.project_id else None

    def _mode_store(self) -> ProjectAutonomyModeStore:
        project_store = getattr(self, "project_store", None)
        path = getattr(project_store, "path", None)
        if path is None:
            raise RuntimeError("ProjectStore is unavailable for autonomy mode enforcement")
        cached = getattr(self, "_project_autonomy_mode_store", None)
        if cached is not None and getattr(cached, "path", None) == path:
            return cached
        cached = ProjectAutonomyModeStore(path)
        self._project_autonomy_mode_store = cached
        return cached

    def project_autonomy_mode(self, project_id: str):
        return _mode_store(self).get(project_id).to_dict()

    def set_project_autonomy_mode(self, project_id: str, mode: str, *, updated_by: str = "owner"):
        settings = _mode_store(self).set(project_id, ProjectAutonomyMode(str(mode)), updated_by=updated_by)
        self._event(
            "project_autonomy_mode_changed",
            project_id=str(project_id),
            autonomy_mode=settings.mode.value,
            authority="owner_project_setting",
        )
        return settings.to_dict()

    def execute_task(self, plan_id, task_id, *args, **kwargs):
        automatic = bool(kwargs.pop("_project_automatic", False))
        project_id = _project_id(self, str(plan_id))
        if project_id:
            settings = _mode_store(self).get(project_id)
            if settings.mode is ProjectAutonomyMode.SHADOW:
                raise PermissionError("Project is in shadow mode; execution is disabled")
            if automatic and settings.mode is not ProjectAutonomyMode.ACTIVE:
                raise PermissionError("automatic Project execution requires active mode")
        return original_execute_task(self, plan_id, task_id, *args, **kwargs)

    def advance_project_plan(
        self,
        plan_id: str,
        *,
        owner_id: str = "owner",
        device_id: str = "",
        session_id: str = "",
        reauthenticated_at: float | None = None,
        max_steps: int = 10,
    ) -> dict[str, Any]:
        project_id = _project_id(self, str(plan_id))
        if not project_id:
            raise KeyError("project-bound work plan not found")
        settings = _mode_store(self).get(project_id)
        if settings.mode is not ProjectAutonomyMode.ACTIVE:
            raise PermissionError("automatic Project execution requires active mode")
        if self._canonical_stop_active():
            raise PermissionError("Emergency Stop active")

        executed: list[str] = []
        stop_reason = "no_ready_work"
        bounded_steps = max(1, min(int(max_steps), 20))
        for _ in range(bounded_steps):
            if self._canonical_stop_active():
                stop_reason = "emergency_stop"
                break
            plan = self.plan(plan_id, owner_id=owner_id)
            state = str(plan.get("state") or "").upper()
            if state in _STOP_STATES:
                stop_reason = f"plan_state:{state.lower()}"
                break
            attention_task = next(
                (
                    item
                    for item in plan.get("tasks", [])
                    if str(item.get("status") or "").upper() in _STOP_STATES - {"COMPLETED"}
                ),
                None,
            )
            if attention_task is not None:
                stop_reason = f"task_state:{str(attention_task.get('status')).lower()}"
                break
            ready = self.ready_tasks(plan_id, owner_id=owner_id)
            if not ready:
                stop_reason = "no_ready_work"
                break
            task = ready[0]
            task_id = str(task["id"])
            try:
                self.execute_task(
                    plan_id,
                    task_id,
                    owner_id=owner_id,
                    device_id=device_id,
                    session_id=session_id,
                    reauthenticated_at=reauthenticated_at,
                    background=True,
                    _project_automatic=True,
                )
            except (PermissionError, RuntimeError) as exc:
                stop_reason = f"governed_stop:{type(exc).__name__}:{str(exc)[:160]}"
                break
            executed.append(task_id)
            refreshed = self.plan(plan_id, owner_id=owner_id)
            updated = next((item for item in refreshed.get("tasks", []) if str(item.get("id")) == task_id), None)
            updated_state = str((updated or {}).get("status") or "").upper()
            if updated_state in _STOP_STATES - {"COMPLETED"}:
                stop_reason = f"task_state:{updated_state.lower()}"
                break
            if updated_state == "COMPLETED" and hasattr(self, "work_order_completion"):
                completion = self.work_order_completion(plan_id, task_id, owner_id=owner_id)
                if not bool(completion.get("passed")):
                    stop_reason = f"completion_state:{str(completion.get('state') or 'blocked').lower()}"
                    break
            if str(refreshed.get("state") or "").upper() in _STOP_STATES:
                stop_reason = f"plan_state:{str(refreshed.get('state')).lower()}"
                break
        else:
            stop_reason = "step_budget_reached"

        return {
            "project_id": project_id,
            "plan_id": str(plan_id),
            "mode": settings.mode.value,
            "executed_task_ids": executed,
            "stop_reason": stop_reason,
            "emergency_stop": bool(self._canonical_stop_active()),
            "execution_authority": "existing_p10_p6_runtime",
            "completion_authority": "deterministic_completion_judge",
        }

    def status(self):
        result = original_status(self)
        result["project_autonomy_modes"] = {
            "installed": True,
            "modes": [item.value for item in ProjectAutonomyMode],
            "default": ProjectAutonomyMode.ASSISTED.value,
            "execution_authority": "existing_p10_p6_runtime",
            "completion_authority": "deterministic_completion_judge",
            "emergency_stop_authoritative": True,
        }
        return result

    cls.execute_task = execute_task
    cls.project_autonomy_mode = project_autonomy_mode
    cls.set_project_autonomy_mode = set_project_autonomy_mode
    cls.advance_project_plan = advance_project_plan
    cls.status = status
    cls._project_autonomy_modes_installed = True
