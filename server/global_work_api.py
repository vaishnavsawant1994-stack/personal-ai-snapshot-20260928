from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Cookie, HTTPException


_ACTIVE = {"RUNNING", "VERIFYING", "RECOVERING"}
_BLOCKED = {"BLOCKED", "UNCERTAIN", "FAILED"}
_TERMINAL_PLAN = {"COMPLETED", "FAILED", "CANCELLED", "UNCERTAIN"}


class GlobalWorkService:
    """Read-only, owner-scoped projection of canonical Work across Projects.

    This service cannot create plans, execute tools, approve actions, retry work,
    verify claims, or recover operations. It only summarizes the already-qualified
    Project Work/P10 state for global Home/Today/living-agent presentation.
    """

    def __init__(self, runtime: dict, store) -> None:
        self.runtime = runtime
        self.store = store

    def _autonomy(self):
        autonomy = self.runtime.get("advanced_autonomy")
        if autonomy is None or getattr(autonomy, "_work_bridge", None) is None:
            raise RuntimeError("canonical Work runtime unavailable")
        return autonomy

    @staticmethod
    def _order_by_task(work_plan: dict) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for order in work_plan.get("work_orders") or []:
            metadata = (order.get("resource_scope") or {}).get("metadata") or {}
            task_id = str(metadata.get("p10_task_id") or "")
            if task_id:
                result[task_id] = order
        return result

    @staticmethod
    def _ready_ids(tasks: list[dict]) -> set[str]:
        completed = {
            str(item.get("id"))
            for item in tasks
            if str(item.get("status") or "").upper() == "COMPLETED"
        }
        return {
            str(item.get("id"))
            for item in tasks
            if str(item.get("status") or "").upper() == "WAITING"
            and set(str(dep) for dep in item.get("dependencies") or []).issubset(completed)
        }

    @staticmethod
    def _living_state(*, active: int, approval: int, blocked: int, ready: int) -> tuple[str, str]:
        if approval:
            return "approval", f"{approval} WorkOrder{'s' if approval != 1 else ''} waiting for your approval."
        if blocked:
            return "attention", f"{blocked} WorkOrder{'s' if blocked != 1 else ''} blocked or uncertain and need attention."
        if active:
            return "background", f"Vishnu is working on {active} WorkOrder{'s' if active != 1 else ''} across your projects."
        if ready:
            return "ready", f"{ready} WorkOrder{'s are' if ready != 1 else ' is'} ready to start."
        return "idle", "No canonical Project Work is active right now."

    def summary(self, *, project_limit: int = 50, work_order_limit: int = 250) -> dict:
        autonomy = self._autonomy()
        bridge = autonomy._work_bridge
        projects = list(self.store.list(query="", status="all", sort="recent"))[: max(1, min(int(project_limit), 100))]
        project_rows: list[dict] = []
        work_orders: list[dict] = []
        task_counts: Counter[str] = Counter()

        for project in projects:
            project_id = str(project.get("id") or "")
            if not project_id:
                continue
            records = bridge.work.project_plan_records(project_id)
            if not records:
                continue
            latest = records[-1]
            source_plan_id = str(latest.get("source_p10_plan_id") or "")
            if not source_plan_id:
                continue
            try:
                p10_plan = autonomy.plan(source_plan_id, owner_id="owner")
                work_plan = autonomy.work_plan(source_plan_id, owner_id="owner")
            except (KeyError, RuntimeError):
                continue

            tasks = list(p10_plan.get("tasks") or [])
            ready_ids = self._ready_ids(tasks)
            order_by_task = self._order_by_task(work_plan)
            project_counts = Counter(str(item.get("status") or "UNKNOWN").upper() for item in tasks)
            task_counts.update(project_counts)
            project_rows.append(
                {
                    "project_id": project_id,
                    "project_name": str(project.get("name") or "Untitled project")[:200],
                    "project_status": project.get("status"),
                    "plan_id": source_plan_id,
                    "work_plan_id": work_plan.get("id"),
                    "plan_version": int(work_plan.get("version") or 1),
                    "readiness": work_plan.get("readiness"),
                    "state": p10_plan.get("state"),
                    "task_counts": dict(project_counts),
                    "replan_count": int(p10_plan.get("replan_count") or 0),
                    "updated_at": p10_plan.get("updated_at"),
                }
            )

            for task in tasks:
                if len(work_orders) >= max(1, min(int(work_order_limit), 500)):
                    break
                task_id = str(task.get("id") or "")
                order = order_by_task.get(task_id) or {}
                metadata = (order.get("resource_scope") or {}).get("metadata") or {}
                status = str(task.get("status") or order.get("status") or "UNKNOWN").upper()
                work_orders.append(
                    {
                        "project_id": project_id,
                        "project_name": str(project.get("name") or "Untitled project")[:200],
                        "plan_id": source_plan_id,
                        "work_plan_id": work_plan.get("id"),
                        "task_id": task_id,
                        "work_order_id": order.get("id"),
                        "title": str(order.get("title") or order.get("objective") or task.get("objective") or task_id)[:300],
                        "objective": str(order.get("objective") or task.get("objective") or "")[:1000],
                        "worker_type": order.get("worker_type"),
                        "requested_tool": metadata.get("requested_tool"),
                        "status": status,
                        "ready": task_id in ready_ids,
                        "updated_at": p10_plan.get("updated_at"),
                    }
                )

        active = sum(task_counts[state] for state in _ACTIVE)
        approval = task_counts["WAITING_APPROVAL"]
        blocked = sum(task_counts[state] for state in _BLOCKED)
        ready = sum(1 for item in work_orders if item["ready"])
        completed = task_counts["COMPLETED"]
        active_projects = sum(1 for item in project_rows if str(item.get("state") or "").upper() not in _TERMINAL_PLAN)
        living_state, living_detail = self._living_state(
            active=active,
            approval=approval,
            blocked=blocked,
            ready=ready,
        )

        priority = {"WAITING_APPROVAL": 0, "BLOCKED": 1, "UNCERTAIN": 1, "FAILED": 1, "VERIFYING": 2, "RECOVERING": 2, "RUNNING": 2, "WAITING": 3, "COMPLETED": 5}
        work_orders.sort(
            key=lambda item: (
                priority.get(str(item.get("status") or ""), 4),
                0 if item.get("ready") else 1,
                str(item.get("project_name") or "").lower(),
                str(item.get("title") or "").lower(),
            )
        )
        return {
            "authority": "read_only_projection",
            "execution_authority": "existing_p10_p6_runtime",
            "projects_total": len(projects),
            "projects_with_work": len(project_rows),
            "active_projects": active_projects,
            "task_counts": dict(task_counts),
            "counts": {
                "active": active,
                "waiting_approval": approval,
                "blocked": blocked,
                "ready": ready,
                "completed": completed,
                "work_orders": sum(task_counts.values()),
            },
            "living": {"state": living_state, "detail": living_detail},
            "projects": project_rows,
            "work_orders": work_orders,
        }


def global_work_router(runtime: dict, store) -> APIRouter:
    router = APIRouter(prefix="/iphone/api/work", tags=["global-work"])
    service = GlobalWorkService(runtime, store)
    registry = runtime["device_registry"]

    def authenticate(device_id: str | None, token: str | None) -> None:
        if not device_id or not token:
            raise HTTPException(401, "Owner device sign-in required")
        try:
            registry.authenticate(device_id, token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc

    @router.get("/summary")
    def work_summary(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        try:
            return service.summary()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
