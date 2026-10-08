import time

from memory.governance import GovernedMemory
from memory.second_brain import MemoryCandidate, SecondBrain
from memory.store import MemoryStore


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
    assert settings["capabilities"] == {"chats": True, "projects": False, "files": False}


def test_ambient_settings_persist_and_unsupported_sources_fail_closed(tmp_path):
    _, governed = make_governed(tmp_path)
    governed.update_ambient_settings({"enabled": False, "sources": {"chats": False}})
    restarted = GovernedMemory(SecondBrain(MemoryStore(tmp_path / "memory.sqlite3")), tmp_path / "governance.sqlite3")

    assert restarted.ambient_settings()["enabled"] is False
    assert restarted.ambient_settings()["sources"]["chats"] is False
    try:
        restarted.update_ambient_settings({"sources": {"files": True}})
    except ValueError as error:
        assert "not available" in str(error)
    else:
        raise AssertionError("unsupported candidate source was enabled")


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
