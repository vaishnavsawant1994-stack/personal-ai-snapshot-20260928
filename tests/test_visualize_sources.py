from __future__ import annotations

import base64

import pytest

from visual_intelligence.file_sources import decode_file_payload, extract_source_text
from visual_intelligence.github_repository import build_repository_graph, parse_github_repository_url


def test_github_url_is_strictly_bounded():
    assert parse_github_repository_url('https://github.com/openai/openai-python') == ('openai', 'openai-python')
    assert parse_github_repository_url('https://github.com/openai/openai-python.git') == ('openai', 'openai-python')
    with pytest.raises(ValueError):
        parse_github_repository_url('https://example.com/openai/openai-python')
    with pytest.raises(ValueError):
        parse_github_repository_url('http://github.com/openai/openai-python')
    with pytest.raises(ValueError):
        parse_github_repository_url('https://github.com/openai/openai-python/issues/1')


def test_repository_graph_preserves_source_evidence():
    graph = build_repository_graph(
        owner='example',
        repo='vishnu-demo',
        branch='main',
        paths=[
            'server/api.py',
            'server/auth.py',
            'pwa/index.html',
            'pwa/app.js',
            'security/policy.py',
            'migrations/001.sql',
        ],
    )
    assert graph.type.value == 'architecture'
    assert graph.metadata['repository'] == 'example/vishnu-demo'
    assert graph.nodes[0].evidence_level.value == 'strong'
    labels = {node.label for node in graph.nodes}
    assert {'Server', 'Pwa', 'Security', 'Migrations'} <= labels
    assert all(node.evidence for node in graph.nodes)


def test_text_file_source_extracts_owner_supplied_content():
    raw = b'# System\nBrowser -> API -> Database\n'
    encoded = base64.b64encode(raw).decode('ascii')
    decoded = decode_file_payload('architecture.md', encoded)
    text, metadata = extract_source_text('architecture.md', decoded)
    assert 'Browser -> API -> Database' in text
    assert metadata['kind'] == 'md'
    assert metadata['bytes'] == len(raw)
    assert metadata['truncated'] is False


def test_file_source_rejects_unsupported_binary():
    encoded = base64.b64encode(b'not an image').decode('ascii')
    decoded = decode_file_payload('photo.png', encoded)
    with pytest.raises(ValueError, match='Unsupported file type'):
        extract_source_text('photo.png', decoded)
