from pathlib import Path
from memory.store import MemoryStore

def test_memory_graph(tmp_path:Path):
    s=MemoryStore(tmp_path/"m.sqlite3"); a=s.remember(type="project",subject="Alpha",content="Project"); b=s.remember(type="person",subject="Sam",content="Contributor"); s.relate(b,"works_on",a); g=s.graph(); assert len(g["nodes"])==2 and len(g["edges"])==1


def test_conversation_history_is_durable_and_isolated_by_thread(tmp_path: Path):
    path = tmp_path / 'm.sqlite3'
    store = MemoryStore(path)
    store.add_message('user', 'alpha question', conversation_id='alpha', device_id='phone')
    store.add_message('assistant', 'alpha answer', conversation_id='alpha', device_id='desktop')
    store.add_message('user', 'beta question', conversation_id='beta', device_id='phone')

    reopened = MemoryStore(path)

    assert reopened.recent_messages(conversation_id='alpha') == [
        {'role': 'user', 'content': 'alpha question'},
        {'role': 'assistant', 'content': 'alpha answer'},
    ]
    assert reopened.recent_messages(conversation_id='beta') == [
        {'role': 'user', 'content': 'beta question'},
    ]


def test_memory_settings_persist_and_soft_removed_records_leave_retrieval(tmp_path: Path):
    from memory.second_brain import SecondBrain

    store = MemoryStore(tmp_path / 'memory.sqlite3')
    memory_id = store.remember(type='preference', subject='Writing', content='Use concise examples')
    brain = SecondBrain(store)
    assert brain.context('concise examples')

    assert store.soft_delete(memory_id)
    assert store.get(memory_id) is None
    assert store.recently_removed()[0]['id'] == memory_id
    assert brain.context('concise examples') == []
    assert store.restore(memory_id)
    assert brain.context('concise examples')

    assert store.update_preferences(memory_enabled=False)['memory_enabled'] is False
    reopened = MemoryStore(tmp_path / 'memory.sqlite3')
    assert reopened.preferences()['memory_enabled'] is False
    assert SecondBrain(reopened).context('concise examples') == []


def test_memory_review_preference_controls_governed_candidates(tmp_path: Path):
    from memory.governance import GovernedMemory
    from memory.second_brain import MemoryCandidate, SecondBrain

    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    governed = GovernedMemory(brain, tmp_path / 'governance.sqlite3')
    candidate = MemoryCandidate(type='fact', subject='Preferred format', content='Detailed steps', confidence=0.8, source='assistant-derived')

    pending_id = governed.remember(candidate)
    assert store.get(pending_id) is None
    store.update_preferences(review_before_saving=False)
    saved_id = governed.remember(candidate)
    assert store.get(saved_id)['content'] == 'Detailed steps'
    store.update_preferences(memory_enabled=False)
    assert governed.remember(MemoryCandidate(type='fact', subject='New', content='Not saved', confidence=0.8, source='assistant-derived')) is None


def test_project_scoped_memory_is_hidden_from_personal_and_other_project_context(tmp_path: Path):
    from memory.second_brain import SecondBrain

    store = MemoryStore(tmp_path / 'memory.sqlite3')
    brain = SecondBrain(store)
    scoped_id = store.remember(
        type='decision', subject='Project only', content='Keep this inside Atlas.',
        source='owner-import:test', verified=True,
        metadata={'scope': 'project', 'project_id': 'atlas'},
    )
    personal_id = store.remember(
        type='preference', subject='Personal', content='Use concise notes.',
        source='user', verified=True,
    )

    assert scoped_id not in {row['id'] for row in brain.context('Keep this inside Atlas')}
    assert scoped_id not in {row['id'] for row in brain.temporal('Keep this inside Atlas')}
    assert scoped_id not in {row['id'] for row in brain.context('Keep this inside Atlas', project_id='other')}
    assert scoped_id in {row['id'] for row in brain.context('Keep this inside Atlas', project_id='atlas')}
    assert scoped_id in {row['id'] for row in brain.temporal('Keep this inside Atlas', project_id='atlas')}
    assert personal_id in {row['id'] for row in brain.context('Use concise notes', project_id='atlas')}
