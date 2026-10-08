import time

from memory.governance import GovernedMemory
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore
from projects.store import ProjectStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.memory_ambient_api import memory_ambient_router


def make_governed(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    brain = SecondBrain(store)
    return store, GovernedMemory(brain, tmp_path / "governance.sqlite3")


def candidate():
    return MemoryCandidate(
        type="preference",
        subject="Prefers short summaries",
        content="The owner prefers concise summaries.",
        confidence=0.84,
        source="user-message",
        verified=False,
    )


def test_ambient_chat_candidate_is_pending_even_if_global_review_is_disabled(tmp_path):
    store, governed = make_governed(tmp_path)
    store.update_preferences(review_before_saving=False)

    candidate_id = governed.remember_ambient(candidate(), conversation_id="conversation-1")

    assert candidate_id
    assert governed.candidates(status="pending")[0]["id"] == candidate_id
    assert store.search("concise") == []


def test_ambient_pause_and_chat_exclusion_stop_new_capture(tmp_path):
    _, governed = make_governed(tmp_path)
    settings = governed.ambient_settings()
    governed.exclude_conversation("private-conversation")

    assert not governed.ambient_can_capture("chats", "private-conversation")
    assert governed.ambient_can_capture("chats", "another-conversation")

    governed.update_ambient_settings({"pause_until": time.time() + 3600})
    assert not governed.ambient_can_capture("chats", "another-conversation")

    governed.update_ambient_settings({"pause_until": None, "enabled": False})
    assert not governed.ambient_can_capture("chats", "another-conversation")
    assert settings["capabilities"] == {"chats": True, "projects": True, "files": True}


def test_ambient_settings_persist_and_enabled_sources_are_supported(tmp_path):
    _, governed = make_governed(tmp_path)
    governed.update_ambient_settings({"enabled": False, "sources": {"chats": False, "projects": True, "files": True}, "retention": "6_months"})
    restarted = GovernedMemory(SecondBrain(MemoryStore(tmp_path / "memory.sqlite3")), tmp_path / "governance.sqlite3")

    assert restarted.ambient_settings()["enabled"] is False
    assert restarted.ambient_settings()["sources"]["chats"] is False
    assert restarted.ambient_settings()["capabilities"] == {"chats": True, "projects": True, "files": True}
    assert restarted.ambient_settings()["retention"] == "6_months"


def test_ambient_candidate_can_be_corrected_before_owner_approval(tmp_path):
    store, governed = make_governed(tmp_path)
    candidate_id = governed.remember_ambient(candidate(), conversation_id="conversation-1")

    edited = governed.update_candidate(candidate_id, {
        "subject": "Prefers concise explanations",
        "content": "The owner prefers concise, actionable explanations.",
    })

    assert edited["candidate"]["subject"] == "Prefers concise explanations"
    assert edited["candidate"]["content"] == "The owner prefers concise, actionable explanations."
    assert edited["candidate"]["metadata"]["conversation_id"] == "conversation-1"
    assert store.search("actionable") == []
    assert governed.candidates(status="pending")[0]["id"] == candidate_id

    memory_id = governed.approve_candidate(candidate_id)
    assert store.get(memory_id)["subject"] == "Prefers concise explanations"


def test_ambient_candidate_edit_rejects_duplicates_and_non_owner(tmp_path):
    _, governed = make_governed(tmp_path)
    first_id = governed.remember_ambient(candidate(), conversation_id="conversation-1")
    second_id = governed.remember_ambient(
        MemoryCandidate(type="preference", subject="Different title", content="Other content", confidence=.7,
                        source="user-message", verified=False),
        conversation_id="conversation-2",
    )

    try:
        governed.update_candidate(second_id, {
            "subject": "Prefers short summaries",
            "content": "The owner prefers concise summaries.",
        })
    except ValueError as error:
        assert "duplicates" in str(error)
    else:
        raise AssertionError("duplicate candidate edit was accepted")

    try:
        governed.update_candidate(first_id, {"subject": "Private"}, owner_id="another-owner")
    except PermissionError:
        pass
    else:
        raise AssertionError("candidate edit was not owner-scoped")


def test_explicit_memory_relationships_remain_canonical_and_owner_scoped(tmp_path):
    store, governed = make_governed(tmp_path)
    first = governed.remember(MemoryCandidate(type="note", subject="First", content="One", confidence=1, source="explicit-owner", verified=True))
    second = governed.remember(MemoryCandidate(type="note", subject="Second", content="Two", confidence=1, source="explicit-owner", verified=True))
    store.relate(first, "supports goal", second)

    graph = governed.graph()
    assert {edge["relation"] for edge in graph["edges"]} == {"supports goal"}
    assert {node["id"] for node in graph["nodes"]} == {first, second}


def test_project_and_file_candidates_remain_pending_and_keep_project_scope(tmp_path):
    _, governed = make_governed(tmp_path)
    governed.update_ambient_settings({"sources": {"projects": True, "files": True}})

    project_candidate = governed.remember_ambient(candidate(), source_type="projects", project_id="project-private", source_id="project-private")
    file_candidate = governed.remember_ambient(candidate(), source_type="files", project_id="project-private", source_id="file-private")

    assert project_candidate and file_candidate
    assert governed.candidate(project_candidate)["status"] == "pending"
    assert governed.candidate(project_candidate)["candidate"]["metadata"]["project_id"] == "project-private"
    assert governed.candidate(file_candidate)["candidate"]["metadata"]["source_id"] == "file-private"
    assert not governed.graph()["nodes"]


def test_retention_expires_only_approved_ambient_memories(tmp_path):
    store, governed = make_governed(tmp_path)
    governed.update_ambient_settings({"retention": "6_months"})
    ambient_id = governed.remember_ambient(candidate(), conversation_id="conversation-retention")
    governed.approve_candidate(ambient_id)
    explicit_id = governed.remember(MemoryCandidate(type="note", subject="Explicit", content="Keep this", confidence=1,
        source="explicit-owner", verified=True))

    expired = governed.expire_ambient_memories(now_ts=time.time() + 184 * 86400)

    assert expired == 1
    assert store.get(ambient_id) is None
    assert store.get(explicit_id) is not None


def test_retention_change_applies_to_existing_ambient_memories_only(tmp_path):
    store, governed = make_governed(tmp_path)
    candidate_id = governed.remember_ambient(candidate(), conversation_id="conversation-retention-update")
    ambient_id = governed.approve_candidate(candidate_id)
    explicit_id = governed.remember(MemoryCandidate(type="note", subject="Explicit", content="Keep this", confidence=1,
        source="explicit-owner", verified=True))

    governed.update_ambient_settings({"retention": "1_year"})
    metadata = __import__("json").loads(store.get(ambient_id)["metadata_json"])

    assert metadata["ambient_expires_at"] > time.time() + 360 * 86400
    assert "ambient_expires_at" not in __import__("json").loads(store.get(explicit_id)["metadata_json"])


def test_owner_scan_generates_review_only_project_and_indexed_file_candidates(tmp_path):
    class Extractor:
        def json(self, prompt, **kwargs):
            assert kwargs.get("sensitivity") == "sensitive"
            return {"memories": [{"type": "project", "subject": "Project goal", "content": "Build a calm product.", "confidence": .8}]}

    class Registry:
        def is_active(self, device_id): return device_id == "owner-device"
        def authorize(self, device_id, scope): return True

    store = MemoryStore(tmp_path / "memory.sqlite3")
    governed = GovernedMemory(SecondBrain(store, models=Extractor()), tmp_path / "governance.sqlite3")
    governed.update_ambient_settings({"sources": {"projects": True, "files": True}})
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    project = projects.create(name="Private project", goal="Ship the product", description="Owner project context")
    projects.add_upload(project["id"], title="brief.md", media_type="text/markdown",
        content=b"# Project brief\nBuild a calm product with a private memory experience.")
    router = memory_ambient_router({"device_registry": Registry(), "second_brain": governed,
        "memory": store, "continuity": None, "project_store": projects})
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/scan"))
    token = set_trusted_request(TrustedRequestContext("owner-device", "owner-session"))
    try:
        result = endpoint()
    finally:
        reset_trusted_request(token)

    candidates = governed.candidates(status="pending")
    assert result == {"candidates_created": 2, "projects_scanned": 1, "files_scanned": 1, "requires_owner_review": True}
    assert len(candidates) == 2
    assert {item["candidate"]["metadata"]["ambient_source"] for item in candidates} == {"projects", "files"}
    assert all(item["candidate"]["metadata"]["project_id"] == project["id"] for item in candidates)
    assert store.search("calm") == []
