from __future__ import annotations

from projects.workforce_adapter import ProjectWorkforceStoreAdapter


class Projects:
    def __init__(self):
        self.rows = {}

    def create(self, *, name, **kwargs):
        project = {"id": f"p-{len(self.rows)+1}", "name": name, "status": "active", **kwargs}
        self.rows[project["id"]] = project
        return project

    def create_walkthrough(self):
        return self.create(name="Walkthrough")

    def get(self, project_id):
        return self.rows.get(project_id)

    def list(self, *args, **kwargs):
        return list(self.rows.values())

    def restore(self, project_id):
        project = self.rows.get(project_id)
        if not project:
            return False
        project["status"] = "active"
        return True


class Workforce:
    def __init__(self):
        self.calls = []
        self.instances = {}

    def reconcile_project_work(self, project_id):
        self.calls.append(project_id)
        self.instances.setdefault(project_id, {"id": f"pm-{project_id}"})
        return {
            "project_id": project_id,
            "manager": self.instances[project_id],
            "assignments": [],
            "unmapped": [],
            "execution_authority": False,
        }


class Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


def test_new_and_walkthrough_projects_reconcile_project_manager():
    projects, workforce, events = Projects(), Workforce(), Events()
    store = ProjectWorkforceStoreAdapter(projects, workforce, events=events)
    one = store.create(name="One")
    two = store.create_walkthrough()
    assert workforce.instances[one["id"]]["id"] == f"pm-{one['id']}"
    assert workforce.instances[two["id"]]["id"] == f"pm-{two['id']}"
    assert all(name == "agent.team.reconciled" for name, _ in events.rows)


def test_project_read_repairs_manager_missing_after_interrupted_write():
    projects, workforce = Projects(), Workforce()
    raw = projects.create(name="Interrupted")
    store = ProjectWorkforceStoreAdapter(projects, workforce)
    assert raw["id"] not in workforce.instances
    store.get(raw["id"])
    assert raw["id"] in workforce.instances


def test_active_project_read_reconciles_canonical_work_every_time_idempotently():
    projects, workforce = Projects(), Workforce()
    raw = projects.create(name="Active")
    store = ProjectWorkforceStoreAdapter(projects, workforce)
    store.get(raw["id"])
    store.get(raw["id"])
    assert workforce.calls == [raw["id"], raw["id"]]
    assert len(workforce.instances) == 1


def test_archived_projects_do_not_spawn_new_runtime_manager_or_reconcile_work():
    projects, workforce = Projects(), Workforce()
    raw = projects.create(name="Archived")
    raw["status"] = "archived"
    store = ProjectWorkforceStoreAdapter(projects, workforce)
    store.get(raw["id"])
    assert raw["id"] not in workforce.instances
    assert workforce.calls == []


def test_workforce_failure_never_rolls_back_or_hides_durable_project():
    class FailingWorkforce:
        def reconcile_project_work(self, project_id):
            raise RuntimeError("workforce unavailable")

    projects, events = Projects(), Events()
    store = ProjectWorkforceStoreAdapter(projects, FailingWorkforce(), events=events)
    created = store.create(name="Still durable")
    assert projects.get(created["id"])["name"] == "Still durable"
    assert events.rows[-1][0] == "agent.team.reconcile_failed"
