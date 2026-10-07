from pathlib import Path

import pytest

from core.preferences import Preferences
from core.personal_ai_runtime import CanonicalTurnRuntime
from memory.governance import GovernedMemory
from memory.second_brain import MemoryCandidate
from memory.store import MemoryStore
from tools import memory_tools


class Registry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool


class Memory:
    def search(self, query, limit):
        return [{'content': 'private memory'}]

    def remember(self, **values):
        return 'memory-1'

    def temporal_search(self, *args, **kwargs):
        return []

    def get(self, memory_id):
        return None

    def conflicts(self, limit):
        return []

    def context(self, *args, **kwargs):
        return [{'content': 'private memory'}]

    def temporal(self, *args, **kwargs):
        return [{'content': 'private memory'}]


def test_memory_preference_persists_for_runtime_restart(tmp_path: Path):
    path = tmp_path / 'preferences.json'
    preferences = Preferences(path)
    assert preferences.get('memory_enabled') is True
    preferences.set('memory_enabled', False)
    assert Preferences(path).get('memory_enabled') is False


def test_disabling_memory_blocks_memory_tools(tmp_path: Path):
    preferences = Preferences(tmp_path / 'preferences.json')
    registry = Registry()
    memory_tools.register(registry, Memory(), is_enabled=lambda: preferences.get('memory_enabled'))

    assert registry.tools['search_memory'].handler({'query': 'private'})
    preferences.set('memory_enabled', False)
    with pytest.raises(PermissionError, match='Memory is turned off'):
        registry.tools['search_memory'].handler({'query': 'private'})
    with pytest.raises(PermissionError, match='Memory is turned off'):
        registry.tools['remember'].handler({'content': 'new private detail'})


def test_governed_memory_toggle_blocks_runtime_recall_and_writes(tmp_path: Path):
    enabled = [True]
    brain = Memory()
    governed = GovernedMemory(brain, tmp_path / 'candidates.sqlite3', is_enabled=lambda: enabled[0])
    assert governed.context('private')
    enabled[0] = False
    assert governed.context('private') == []
    assert governed.temporal('private') == []
    assert governed.remember(MemoryCandidate(type='note', subject='x', content='y', confidence=1.0)) is None


def test_clearing_chat_messages_preserves_saved_memories(tmp_path: Path):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    store.add_message('user', 'conversation text', conversation_id='thread-1')
    memory_id = store.remember(type='note', subject='Keep', content='saved memory', source='explicit-owner', verified=True)
    assert store.clear_conversation_messages() == 1
    assert store.recent_messages() == []
    assert store.get(memory_id)['content'] == 'saved memory'


def test_turn_history_clear_refuses_active_work_and_removes_completed_turns(tmp_path: Path):
    runtime = CanonicalTurnRuntime(object(), object(), tmp_path / 'turns.sqlite3')
    with runtime._con() as con:
        con.execute("INSERT INTO canonical_turns(request_id,owner_id,conversation_id,device_id,session_id,surface,input_modality,privacy_level,risk_level,user_text,status,created_at,updated_at) VALUES('r1','owner','c1','d1','s1','web','text','normal','low','private','started',1,1)")
    with pytest.raises(RuntimeError, match='active assistant work'):
        runtime.clear_conversation_history()
    with runtime._con() as con:
        con.execute("UPDATE canonical_turns SET status='completed' WHERE request_id='r1'")
    assert runtime.clear_conversation_history() == 1
