from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore
from models.contracts import ModelResponse, UsageRecord
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.agent_workforce_pwa_api import agent_workforce_pwa_router


class Registry:
    def authenticate(self, device_id, token):
        return device_id == "device-1" and token == "token-1"

    def authorize(self, device_id, scope):
        return device_id == "device-1" and scope == "ai:chat"


class Projects:
    def __init__(self):
        self.rows = {
            "project-a": {
                "id": "project-a", "name": "Alpha", "goal": "Ship Alpha", "description": "Alpha only",
                "success_criteria": "Tests pass", "instructions": "Stay inside Alpha", "context_notes": "A",
                "status": "active",
            },
            "project-b": {
                "id": "project-b", "name": "Beta", "goal": "Ship Beta", "description": "Beta only",
                "success_criteria": "Tests pass", "instructions": "Stay inside Beta", "context_notes": "B",
                "status": "active",
            },
        }

    def get(self, project_id):
        return self.rows.get(project_id)


class Models:
    def request(self, request):
        return ModelResponse(
            request_id=request.request_id, provider_id="provider", model_id="model",
            content=f"reply:{request.prompt}",
            usage=UsageRecord(input_tokens=1, output_tokens=1, total_tokens=2, estimated_cost=0.0),
        )


def make_client(tmp_path):
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    workforce = AgentWorkforceService(store, models=Models())
    runtime = {
        "device_registry": Registry(),
        "project_store": Projects(),
        "agent_workforce": workforce,
    }
    app = FastAPI()
    app.include_router(agent_workforce_pwa_router(runtime))
    client = TestClient(app)
    return client, workforce


def trusted(client):
    client.cookies.set("pa_device", "device-1")
    client.cookies.set("pa_token", "token-1")


def write(client, method, path, **kwargs):
    token = set_trusted_request(TrustedRequestContext(device_id="device-1", session_id="session-1"))
    try:
        return client.request(method, path, **kwargs)
    finally:
        reset_trusted_request(token)


def test_workforce_api_requires_trusted_browser(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/iphone/api/agents")
    assert response.status_code == 401


def test_trusted_reads_work_but_mutations_require_current_session_binding(tmp_path):
    client, workforce = make_client(tmp_path)
    trusted(client)
    read = client.get("/iphone/api/agents/summary")
    assert read.status_code == 200
    assert read.json()["total_agents"] == len(workforce.catalog())

    coding = workforce.store.get_template_by_slug("coding")
    denied = client.post(
        f"/iphone/api/agents/{coding['id']}/instances",
        json={"project_id": "project-a"},
    )
    assert denied.status_code == 401

    allowed = write(
        client, "POST", f"/iphone/api/agents/{coding['id']}/instances",
        json={"project_id": "project-a"},
    )
    assert allowed.status_code == 201
    assert allowed.json()["project_id"] == "project-a"


def test_instance_creation_rejects_missing_project(tmp_path):
    client, workforce = make_client(tmp_path)
    trusted(client)
    coding = workforce.store.get_template_by_slug("coding")
    response = write(
        client, "POST", f"/iphone/api/agents/{coding['id']}/instances",
        json={"project_id": "missing-project"},
    )
    assert response.status_code == 404
    assert workforce.store.list_instances(template_id=coding["id"]) == []


def test_pwa_agent_chat_cannot_be_read_or_sent_from_another_project(tmp_path):
    client, workforce = make_client(tmp_path)
    trusted(client)
    coding = workforce.store.get_template_by_slug("coding")
    instance = workforce.create_instance(coding["id"], project_id="project-a")

    created = write(
        client, "POST", f"/iphone/api/agents/{coding['id']}/conversations",
        json={"project_id": "project-a", "instance_id": instance["id"], "title": "Alpha chat"},
    )
    assert created.status_code == 201
    chat_id = created.json()["conversation"]["id"]

    wrong_read = client.get(
        f"/iphone/api/agents/conversations/{chat_id}", params={"project_id": "project-b"}
    )
    assert wrong_read.status_code == 403

    wrong_send = write(
        client, "POST", f"/iphone/api/agents/conversations/{chat_id}/messages",
        json={"project_id": "project-b", "prompt": "show me Alpha"},
    )
    assert wrong_send.status_code == 403

    correct = write(
        client, "POST", f"/iphone/api/agents/conversations/{chat_id}/messages",
        json={"project_id": "project-a", "prompt": "inspect Alpha"},
    )
    assert correct.status_code == 200
    assert correct.json()["completion_authority"] is False
    assert correct.json()["tool_execution_authority"] is False
