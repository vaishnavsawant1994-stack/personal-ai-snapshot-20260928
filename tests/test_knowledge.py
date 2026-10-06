from knowledge.store import KnowledgeError, KnowledgeStore


def test_knowledge_ingestion_search_provenance_update_and_delete(tmp_path):
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    data = b'Project Aurora launch date is 14 October. The owner approved the final plan.'

    document = store.ingest(
        filename='aurora-notes.txt',
        data=data,
        source='owner-upload:test',
        access_class='owner',
    )

    assert document['filename'] == 'aurora-notes.txt'
    assert document['chunks'][0]['content'].startswith('Project Aurora')
    listed = store.list()[0]
    assert listed['source'] == 'owner-upload:test'
    assert listed['indexed_chunk_count'] == len(document['chunks'])
    assert store.list('Aurora launch')[0]['indexed_chunk_count'] == len(document['chunks'])
    result = store.search('Aurora launch')[0]
    assert result['citation']['document_id'] == document['id']
    assert result['citation']['source'] == 'owner-upload:test'
    assert result['citation']['checksum'] == document['checksum']

    duplicate = store.ingest(filename='copy.txt', data=data)
    assert duplicate['id'] == document['id']
    assert store.update(document['id'], title='Aurora launch plan')['title'] == 'Aurora launch plan'
    assert store.delete(document['id']) is True
    assert store.detail(document['id']) is None
    assert list((tmp_path / 'objects').iterdir()) == []


def test_knowledge_rejects_unsafe_unsupported_or_empty_uploads(tmp_path):
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    for filename, data in [('../unsafe.exe', b'data'), ('empty.txt', b'')]:
        try:
            store.ingest(filename=filename, data=data)
        except KnowledgeError:
            pass
        else:
            raise AssertionError('unsafe knowledge upload was accepted')


def test_available_to_vishnu_gate_and_collection_lifecycle(tmp_path):
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    collection = store.create_collection('Project notes', 'Scoped project material')
    document = store.ingest(
        filename='project.txt', data=b'The private launch milestone is ready.',
        metadata={'collection_id': collection['id'], 'available_to_vishnu': True},
    )
    assert store.collections()[0]['item_count'] == 1
    assert store.search('private launch')

    metadata = dict(document['metadata'])
    metadata['available_to_vishnu'] = False
    store.update(document['id'], metadata=metadata)
    assert store.list()[0]['metadata']['available_to_vishnu'] is False
    assert store.search('private launch') == []

    store.delete_collection(collection['id'])
    assert store.detail(document['id'])['metadata'].get('collection_id') is None
    assert store.detail(document['id']) is not None
