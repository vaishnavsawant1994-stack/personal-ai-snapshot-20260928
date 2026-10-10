from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .models import EvidenceLevel, VisualEdge, VisualGraph, VisualNode, VisualType


_GITHUB_PATH = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def parse_github_repository_url(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme != 'https' or parsed.hostname not in {'github.com', 'www.github.com'}:
        raise ValueError('Only https://github.com/<owner>/<repository> URLs are supported')
    match = _GITHUB_PATH.match(parsed.path)
    if not match:
        raise ValueError('GitHub repository URL must identify exactly one owner and repository')
    return match.group(1), match.group(2)


def _category(path: str) -> str:
    token = path.casefold().split('/', 1)[0]
    if token in {'web', 'webapp', 'frontend', 'client', 'ui', 'pwa', 'ios', 'android', 'mobile'}:
        return 'frontend'
    if token in {'server', 'backend', 'api', 'app', 'services', 'service'}:
        return 'backend'
    if token in {'db', 'database', 'data', 'migrations', 'storage'}:
        return 'database'
    if token in {'security', 'auth', 'identity', 'permissions'}:
        return 'security'
    if token in {'deploy', 'infra', 'infrastructure', 'cloud', 'terraform', 'k8s', 'kubernetes'}:
        return 'cloud'
    if token in {'agent', 'agents', 'workers', 'workforce'}:
        return 'agent'
    if token in {'tools', 'plugins', 'integrations', 'connectors'}:
        return 'tool'
    return 'component'


def _label(path: str) -> str:
    value = path.rstrip('/').split('/')[-1]
    return value.replace('_', ' ').replace('-', ' ').strip().title() or path


def build_repository_graph(*, owner: str, repo: str, branch: str, paths: list[str], title: str | None = None, truncated: bool = False) -> VisualGraph:
    repository_url = f'https://github.com/{owner}/{repo}'
    root = VisualNode(
        id='repository',
        label=title or repo,
        category='project',
        description=f'GitHub repository {owner}/{repo} on {branch}',
        evidence_level=EvidenceLevel.STRONG,
        evidence=[{'kind': 'repository', 'url': repository_url, 'ref': branch}],
        metadata={'repository': f'{owner}/{repo}', 'branch': branch},
    )
    nodes = [root]
    edges: list[VisualEdge] = []

    top_level: dict[str, int] = {}
    for raw in paths:
        clean = str(raw or '').strip('/')
        if not clean:
            continue
        first = clean.split('/', 1)[0]
        top_level[first] = top_level.get(first, 0) + 1

    ranked = sorted(top_level.items(), key=lambda item: (-item[1], item[0].casefold()))[:36]
    for index, (name, count) in enumerate(ranked, 1):
        node_id = f'repo-{index}'
        category = _category(name)
        node = VisualNode(
            id=node_id,
            label=_label(name),
            category=category,
            description=f'{count} repository path{"s" if count != 1 else ""} under {name}',
            evidence_level=EvidenceLevel.STRONG,
            evidence=[{
                'kind': 'repository_path',
                'repository': f'{owner}/{repo}',
                'ref': branch,
                'path': name,
                'url': f'{repository_url}/tree/{branch}/{name}' if count > 1 else f'{repository_url}/blob/{branch}/{name}',
            }],
            metadata={'path': name, 'path_count': count},
        )
        nodes.append(node)
        edges.append(VisualEdge(id=f'contains-{index}', source=root.id, target=node_id, kind='contains'))

    return VisualGraph(
        type=VisualType.ARCHITECTURE,
        title=title or f'{owner}/{repo} Architecture',
        nodes=nodes,
        edges=edges,
        metadata={
            'analysis': 'github-repository-tree',
            'repository': f'{owner}/{repo}',
            'repository_url': repository_url,
            'branch': branch,
            'path_count': len(paths),
            'tree_truncated': bool(truncated),
            'paths': paths[:5000],
        },
    )


@dataclass(slots=True)
class GitHubRepositoryAnalyzer:
    timeout_seconds: float = 12.0
    max_paths: int = 5000

    def analyze(self, url: str, *, title: str | None = None) -> VisualGraph:
        owner, repo = parse_github_repository_url(url)
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Vishnu-Visualize/1.0'}
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False, headers=headers) as client:
                meta_response = client.get(f'https://api.github.com/repos/{owner}/{repo}')
                if meta_response.status_code == 404:
                    raise ValueError('GitHub repository was not found or is not public')
                if meta_response.status_code == 403:
                    raise ValueError('GitHub API rate limit reached; try again after the limit resets')
                meta_response.raise_for_status()
                metadata = meta_response.json()
                branch = str(metadata.get('default_branch') or 'main')
                tree_response = client.get(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}', params={'recursive': '1'})
                if tree_response.status_code == 404:
                    raise ValueError('GitHub repository tree could not be read')
                if tree_response.status_code == 403:
                    raise ValueError('GitHub API rate limit reached; try again after the limit resets')
                tree_response.raise_for_status()
                tree_payload = tree_response.json()
        except ValueError:
            raise
        except httpx.HTTPError as exc:
            raise ValueError('GitHub repository could not be reached safely') from exc
        paths = [str(item.get('path') or '') for item in tree_payload.get('tree') or [] if item.get('path')]
        graph = build_repository_graph(
            owner=owner,
            repo=repo,
            branch=branch,
            paths=paths[: self.max_paths],
            title=title or str(metadata.get('name') or repo),
            truncated=bool(tree_payload.get('truncated')) or len(paths) > self.max_paths,
        )
        graph.metadata.update({
            'description': str(metadata.get('description') or ''),
            'language': metadata.get('language'),
            'visibility': metadata.get('visibility') or 'public',
            'stars': metadata.get('stargazers_count'),
        })
        return graph
