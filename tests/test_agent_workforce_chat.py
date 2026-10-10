from __future__ import annotations

from models.contracts import ModelResponse, UsageRecord
from future_intelligence.agent_workforce import AgentWorkforceService, AgentWorkforceStore


class CaptureModels:
    def __init__(self):
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            provider_id="test-provider",
            model_id="test-model",
            content=f"reply:{request.prompt}",
            usage=UsageRecord(input_tokens=3, output_tokens=2, total_tokens=5, estimated_cost=0.01),
        )


def workforce(tmp_path):
    store = AgentWorkforceStore(tmp_path / "agents.sqlite3")
    models = CaptureModels()
    return AgentWorkforceService(store, models=models), models


def test_agent_conversation_is_project_scoped_and_version_pinned(tmp_path):
    service, _ = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    original = service.store.preferred_version(coding["id"])
    instance = service.create_instance(coding["id"], project_id="project-a", version_id=original["id"])
    chat = service.create_conversation(
        coding["id"], project_id="project-a", instance_id=instance["id"], title="Fix CI"
    )
    candidate = service.create_version(
        coding["id"], version="1.1", parent_version_id=original["id"], instructions="candidate instructions"
    )
    assert candidate["id"] != original["id"]
    assert chat["version_id"] == original["id"]
    assert service.conversation(chat["id"], project_id="project-a")["version_id"] == original["id"]


def test_agent_conversation_rejects_cross_project_reads_and_writes(tmp_path):
    service, _ = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    instance = service.create_instance(coding["id"], project_id="project-a")
    chat = service.create_conversation(coding["id"], project_id="project-a", instance_id=instance["id"])

    try:
        service.conversation(chat["id"], project_id="project-b")
        raise AssertionError("cross-project read should fail")
    except PermissionError:
        pass

    try:
        service.direct_chat(chat["id"], project_id="project-b", prompt="leak context")
        raise AssertionError("cross-project send should fail")
    except PermissionError:
        pass


def test_direct_chat_is_model_only_uses_exact_project_context_and_persists_history(tmp_path):
    service, models = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    instance = service.create_instance(coding["id"], project_id="project-a")
    chat = service.create_conversation(coding["id"], project_id="project-a", instance_id=instance["id"])

    first = service.direct_chat(
        chat["id"], project_id="project-a", prompt="inspect the failing test",
        project_context='{"id":"project-a","name":"Alpha","secret_from_b":false}',
    )
    second = service.direct_chat(
        chat["id"], project_id="project-a", prompt="now suggest the smallest repair",
        project_context='{"id":"project-a","name":"Alpha"}',
    )

    assert first["model_output_authority"] is False
    assert first["tool_execution_authority"] is False
    assert first["completion_authority"] is False
    assert models.requests[0].project_id == "project-a"
    assert models.requests[0].tools_allowed == ()
    assert "Authorized Project context only" in models.requests[0].system
    assert '"id":"project-a"' in models.requests[0].system
    assert "another Project" in models.requests[0].system
    assert models.requests[1].history == (
        {"role": "user", "content": "inspect the failing test"},
        {"role": "assistant", "content": "reply:inspect the failing test"},
    )
    stored = service.conversation(chat["id"], project_id="project-a")["messages"]
    assert [row["role"] for row in stored] == ["user", "assistant", "user", "assistant"]
    assert stored[-1]["content"] == second["assistant_message"]["content"]


def test_separate_projects_keep_separate_agent_chat_histories(tmp_path):
    service, models = workforce(tmp_path)
    coding = service.store.get_template_by_slug("coding")
    a = service.create_instance(coding["id"], project_id="a")
    b = service.create_instance(coding["id"], project_id="b")
    chat_a = service.create_conversation(coding["id"], project_id="a", instance_id=a["id"])
    chat_b = service.create_conversation(coding["id"], project_id="b", instance_id=b["id"])

    service.direct_chat(chat_a["id"], project_id="a", prompt="alpha-only", project_context="alpha context")
    service.direct_chat(chat_b["id"], project_id="b", prompt="beta-only", project_context="beta context")

    assert models.requests[0].project_id == "a"
    assert models.requests[1].project_id == "b"
    assert "alpha-only" not in str(models.requests[1].history)
    assert "alpha context" not in models.requests[1].system
    assert [m["content"] for m in service.conversation(chat_a["id"], project_id="a")["messages"] if m["role"] == "user"] == ["alpha-only"]
    assert [m["content"] for m in service.conversation(chat_b["id"], project_id="b")["messages"] if m["role"] == "user"] == ["beta-only"]
