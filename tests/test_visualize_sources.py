from __future__ import annotations

import base64

import pytest

from visual_intelligence import deep_repository
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


class _FakeResponse:
    def __init__(self, payload=None, *, text='', status=200):
        self._payload = payload
        self.text = text
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class _FakeGitHubClient:
    commit_sha = 'a' * 40
    tree_sha = 'b' * 40

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None, headers=None):
        if url.endswith('/repos/example/deep-demo'):
            return _FakeResponse({'name': 'deep-demo', 'default_branch': 'main'})
        if url.endswith('/repos/example/deep-demo/branches/main'):
            return _FakeResponse({'commit': {'sha': self.commit_sha, 'commit': {'tree': {'sha': self.tree_sha}}}})
        if url.endswith('/git/trees/' + self.tree_sha):
            return _FakeResponse({'sha': self.tree_sha, 'truncated': False, 'tree': [
                {'path': 'app/main.py', 'type': 'blob', 'sha': '1' * 40, 'size': 120},
                {'path': 'app/db.py', 'type': 'blob', 'sha': '2' * 40, 'size': 80},
            ]})
        if url == f'https://raw.githubusercontent.com/example/deep-demo/{self.commit_sha}/app/main.py':
            assert params is None
            assert headers['Accept'].startswith('text/plain')
            return _FakeResponse(text="from .db import store\nfrom fastapi import APIRouter\nrouter=APIRouter()\n\n@router.get('/health')\ndef health():\n    return store.ok()\n")
        if url == f'https://raw.githubusercontent.com/example/deep-demo/{self.commit_sha}/app/db.py':
            assert params is None
            assert headers['Accept'].startswith('text/plain')
            return _FakeResponse(text='class Store:\n    def ok(self):\n        return True\n\nstore=Store()\n')
        raise AssertionError(f'Unexpected GitHub request: {url}')


def test_deep_repository_analysis_pins_verified_evidence_to_commit(monkeypatch):
    monkeypatch.setattr(deep_repository.httpx, 'Client', _FakeGitHubClient)
    graph = deep_repository.DeepGitHubRepositoryAnalyzer().analyze('https://github.com/example/deep-demo')
    assert graph.metadata['analysis'] == 'github-source-code'
    assert graph.metadata['commit_sha'] == _FakeGitHubClient.commit_sha
    assert graph.metadata['tree_sha'] == _FakeGitHubClient.tree_sha
    assert graph.metadata['source_files_analyzed'] == 2
    verified = [node for node in graph.nodes if node.evidence_level.value == 'verified']
    assert verified
    evidence = [item for node in verified for item in node.evidence if item.get('kind') == 'source_lines']
    assert evidence
    assert all(item['ref'] == _FakeGitHubClient.commit_sha for item in evidence)
    assert all('/blob/' + _FakeGitHubClient.commit_sha + '/' in item['url'] for item in evidence)
    health = next(node for node in graph.nodes if node.label == 'health')
    assert health.evidence[0]['line_start'] == 6
    assert health.evidence[0]['line_end'] == 7
    imports = [edge for edge in graph.edges if edge.kind == 'imports']
    assert len(imports) == 1
    assert imports[0].metadata['evidence_level'] == 'verified'
    assert imports[0].metadata['evidence'][0]['line_start'] == 1


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
