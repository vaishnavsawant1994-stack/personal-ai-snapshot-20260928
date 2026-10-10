from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.agent_work_requests_api as module
from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.agent_work_requests_api import agent_work_requests_router


class Registry:
    def authenticate(self, device_id, token):
        return device_id == "device-1" and token == "token-1"

    def authorize(self, device_id, scope):
        return device_id == "device-1" and scope == "ai:chat"


class Projects:
    def __init__(self):
        self.rows = {
            "project-a": {"id": "project-a", "name": "Alpha", "status": "active"},
            "project-b": {"id": "project-b", "name": "Beta", "status": "active"},
        }

    def get(self, project_id):
        return self.rows.get(project_id)


class FakeProjectWorkService:
    calls = []

    def __init__(self, runtime, store):
        self.runtime = runtime
        self.store = store

    def create_plan(self, project_id, **kwargs):
        self.__class__.calls.append((project_id, kwargs))
        return {
            "project_id": project_id,
            "goal_id": "goal-1",
            "created": True,
            "plan_id": "plan-1",
        }


class Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ProjectWorkService", FakeProjectWorkService)
    FakeProjectWorkService.calls.clear()
    events = Events()
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    workforce = AgentWorkforceService(store, events=events)
    projects = Projects()
    runtime = {
        "device_registry": Registry(),
        "project_store": projects,
        "agent_workforce": workforce,
    }
    app = FastAPI()
    app.include_router(agent_work_requests_router(runtime))
    client = TestClient(app)
    client.cookies.set("pa_device", "device-1")
    client.cookies.set("pa_token", "token-1")
    return client, workforce, events


def write(client, path, payload):
    token = set_trusted_request(TrustedRequestContext(device_id="device-1", session_id="session-1"))
    try:
        return client.post(path, json=payload)
    finally:
        reset_trusted_request(token)


def test_work_request_requires_current_trusted_session(tmp_path, monkeypatch):
    client, workforce, _ = make_client(tmp_path, monkeypatch)
    coding = workforce.store.get_template_by_slug("coding")
    response = client.post(
        f"/iphone/api/agents/{coding['id']}/work-requests",
        json={"project_id": "project-a", "prompt": "Fix the tests"},
    )
    assert response.status_code == 401
    assert FakeProjectWorkService.calls == []


def test_direct_specialist_request_creates_canonical_work_without_execution_authority(tmp_path, monkeypatch):
    client, workforce, events = make_client(tmp_path, monkeypatch)
    coding = workforce.store.get_template_by_slug("coding")
    instance = workforce.create_instance(coding["id"], project_id="project-a")
    conversation = workforce.create_conversation(
        coding["id"], project_id="project-a", instance_id=instance["id"], title="Coding work"
    )
    response = write(
        client,
        f"/iphone/api/agents/{coding['id']}/work-requests",
        {"project_id": "project-a", "prompt": "Fix the failing repository tests", "conversation_id": conversation["id"]},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["work"]["created"] is True
    assert body["execution_authority"] is False
    assert body["tool_authority"] is False
    assert body["completion_authority"] is False
    assert FakeProjectWorkService.calls[0][0] == "project-a"
    query = FakeProjectWorkService.calls[0][1]["query"]
    assert "Coding Agent" in query
    assert "Fix the failing repository tests" in query
    messages = workforce.conversation(conversation["id"], project_id="project-a")["messages"]
    assert [row["role"] for row in messages] == ["user", "assistant"]
    assert "Canonical Project Work" in messages[-1]["content"]
    assert any(name == "agent.work_request.created" for name, _ in events.rows)


def test_work_request_rejects_cross_project_conversation(tmp_path, monkeypatch):
    client, workforce, _ = make_client(tmp_path, monkeypatch)
    coding = workforce.store.get_template_by_slug("coding")
    instance = workforce.create_instance(coding["id"], project_id="project-a")
    conversation = workforce.create_conversation(coding["id"], project_id="project-a", instance_id=instance["id"])
    response = write(
        client,
        f"/iphone/api/agents/{coding['id']}/work-requests",
        {"project_id": "project-b", "prompt": "Try to mix projects", "conversation_id": conversation["id"]},
    )
    assert response.status_code == 403
    assert FakeProjectWorkService.calls == []


def test_work_request_rejects_unknown_or_archived_project_before_planning(tmp_path, monkeypatch):
    client, workforce, _ = make_client(tmp_path, monkeypatch)
    coding = workforce.store.get_template_by_slug("coding")
    response = write(
        client,
        f"/iphone/api/agents/{coding['id']}/work-requests",
        {"project_id": "missing", "prompt": "Do work"},
    )
    assert response.status_code == 404
    assert FakeProjectWorkService.calls == []
