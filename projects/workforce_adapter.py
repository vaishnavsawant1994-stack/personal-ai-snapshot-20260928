from __future__ import annotations


class ProjectWorkforceStoreAdapter:
    """ProjectStore compatibility adapter that reconciles workforce bootstrap.

    Projects and workforce live in separate durable SQLite stores, so pretending
    their writes are one transaction would be unsafe. Instead Project creation
    remains authoritative and this adapter idempotently reconciles Project
    Manager + canonical Work specialist projections after creation/restore and
    whenever an active Project is read again. A crash between writes is therefore
    repaired on the next normal access.
    """

    def __init__(self, store, workforce, *, events=None):
        self._store = store
        self._workforce = workforce
        self._events = events

    def __getattr__(self, name):
        return getattr(self._store, name)

    def _emit(self, name: str, **payload):
        if self._events is not None:
            self._events.emit(name, **payload)

    def _ensure(self, project):
        if not isinstance(project, dict):
            return project
        project_id = str(project.get("id") or "").strip()
        status = str(project.get("status") or "active")
        if not project_id or status == "archived":
            return project
        try:
            result = self._workforce.reconcile_project_work(project_id)
            manager = result.get("manager") if isinstance(result, dict) else None
            self._emit(
                "agent.team.reconciled",
                project_id=project_id,
                manager_instance_id=(manager or {}).get("id") or (manager or {}).get("instance_id"),
                assignments=len((result or {}).get("assignments", [])) if isinstance(result, dict) else 0,
                unmapped=len((result or {}).get("unmapped", [])) if isinstance(result, dict) else 0,
            )
        except Exception as exc:
            # Project durability wins. Reconciliation is idempotent and safe to
            # retry on the next Project read; workforce never owns Project state.
            self._emit(
                "agent.team.reconcile_failed",
                project_id=project_id,
                error_type=type(exc).__name__,
            )
        return project

    def create(self, *args, **kwargs):
        return self._ensure(self._store.create(*args, **kwargs))

    def create_walkthrough(self, *args, **kwargs):
        return self._ensure(self._store.create_walkthrough(*args, **kwargs))

    def get(self, project_id):
        return self._ensure(self._store.get(project_id))

    def list(self, *args, **kwargs):
        rows = self._store.list(*args, **kwargs)
        for project in rows:
            self._ensure(project)
        return rows

    def restore(self, project_id):
        restored = self._store.restore(project_id)
        if restored:
            self._ensure(self._store.get(project_id))
        return restored
