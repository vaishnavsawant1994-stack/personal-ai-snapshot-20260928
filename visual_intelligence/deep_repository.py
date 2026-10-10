from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from .github_repository import _category, _label, parse_github_repository_url
from .models import EvidenceLevel, VisualEdge, VisualGraph, VisualNode, VisualType


_SOURCE_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.java', '.go', '.rs', '.rb', '.php'}
_SKIP_PARTS = {'node_modules', 'vendor', 'dist', 'build', '.next', 'coverage', '__pycache__', '.venv', 'venv'}
_IMPORT_RE = re.compile(r"(?:from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\)|import\s+[^;]*?\s+from\s+['\"]([^'\"]+)['\"])")
_SYMBOL_RE = re.compile(r'^\s*(?:export\s+)?(?:async\s+)?(class|function)\s+([A-Za-z_$][\w$]*)', re.MULTILINE)
_ROUTE_RE = re.compile(r'\.(get|post|put|patch|delete|options|head)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')


def _safe_id(prefix: str, value: str) -> str:
    token = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')[:100] or 'item'
    return f'{prefix}-{token}'


def _source_category(path: str) -> str:
    category = _category(path)
    lowered = path.casefold()
    if category != 'component':
        return category
    if any(part in lowered for part in ('model', 'schema', 'migration', 'database', 'repository', 'store')):
        return 'database'
    if any(part in lowered for part in ('auth', 'security', 'permission', 'policy')):
        return 'security'
    if any(part in lowered for part in ('agent', 'worker', 'planner')):
        return 'agent'
    if any(part in lowered for part in ('tool', 'plugin', 'connector', 'integration')):
        return 'tool'
    return 'component'


def _python_facts(text: str) -> tuple[list[dict], list[dict]]:
    symbols: list[dict] = []
    imports: list[dict] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators = []
            routes = []
            for dec in getattr(node, 'decorator_list', []):
                try:
                    rendered = ast.unparse(dec)
                except Exception:
                    rendered = ''
                if rendered:
                    decorators.append(rendered)
                    match = re.search(r'\.(get|post|put|patch|delete)\([\'\"]([^\'\"]+)', rendered)
                    if match:
                        routes.append({'method': match.group(1).upper(), 'path': match.group(2)})
            symbols.append({
                'name': node.name,
                'kind': 'class' if isinstance(node, ast.ClassDef) else 'function',
                'line_start': int(getattr(node, 'lineno', 1)),
                'line_end': int(getattr(node, 'end_lineno', getattr(node, 'lineno', 1))),
                'decorators': decorators[:8],
                'routes': routes,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({'module': alias.name, 'line': int(getattr(node, 'lineno', 1))})
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or '')
            if module:
                imports.append({'module': ('.' * int(node.level or 0)) + module, 'line': int(getattr(node, 'lineno', 1))})
    return symbols[:40], imports[:120]


def _script_facts(text: str) -> tuple[list[dict], list[dict]]:
    symbols: list[dict] = []
    for match in _SYMBOL_RE.finditer(text):
        line = text.count('\n', 0, match.start()) + 1
        symbols.append({'name': match.group(2), 'kind': match.group(1), 'line_start': line, 'line_end': line, 'routes': []})
    for match in _ROUTE_RE.finditer(text):
        line = text.count('\n', 0, match.start()) + 1
        symbols.append({'name': f'{match.group(1).upper()} {match.group(2)}', 'kind': 'route', 'line_start': line, 'line_end': line, 'routes': [{'method': match.group(1).upper(), 'path': match.group(2)}]})
    imports: list[dict] = []
    for match in _IMPORT_RE.finditer(text):
        module = next((group for group in match.groups() if group), '')
        if module:
            imports.append({'module': module, 'line': text.count('\n', 0, match.start()) + 1})
    return symbols[:40], imports[:120]


def _resolve_import(source_path: str, module: str, known_paths: set[str]) -> str | None:
    if not module:
        return None
    source = PurePosixPath(source_path)
    candidates: list[str] = []
    if source.suffix == '.py':
        dots = len(module) - len(module.lstrip('.'))
        clean = module.lstrip('.').replace('.', '/')
        base = source.parent
        for _ in range(max(0, dots - 1)):
            base = base.parent
        if clean:
            base = base / clean
        candidates.extend([str(base.with_suffix('.py')), str(base / '__init__.py')])
    elif module.startswith('.'):
        base = source.parent / module
        for suffix in ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'):
            candidates.append(str(base) + suffix)
        for suffix in ('/index.ts', '/index.tsx', '/index.js', '/index.jsx'):
            candidates.append(str(base) + suffix)
    normalized = {str(PurePosixPath(item)) for item in candidates}
    return next((item for item in normalized if item in known_paths), None)


@dataclass(slots=True)
class DeepGitHubRepositoryAnalyzer:
    timeout_seconds: float = 14.0
    max_paths: int = 5000
    max_source_files: int = 28
    max_file_bytes: int = 220_000

    def analyze(self, url: str, *, title: str | None = None) -> VisualGraph:
        owner, repo = parse_github_repository_url(url)
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Vishnu-Visualize/2.0'}
        repository_url = f'https://github.com/{owner}/{repo}'
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False, headers=headers) as client:
                meta = client.get(f'https://api.github.com/repos/{owner}/{repo}')
                if meta.status_code == 404:
                    raise ValueError('GitHub repository was not found or is not public')
                if meta.status_code == 403:
                    raise ValueError('GitHub API rate limit reached; try again after the limit resets')
                meta.raise_for_status()
                metadata = meta.json()
                branch = str(metadata.get('default_branch') or 'main')

                branch_response = client.get(f'https://api.github.com/repos/{owner}/{repo}/branches/{quote(branch, safe="")}')
                if branch_response.status_code in {403, 404}:
                    raise ValueError('GitHub default branch could not be resolved')
                branch_response.raise_for_status()
                branch_payload = branch_response.json()
                commit_payload = branch_payload.get('commit') or {}
                commit_sha = str(commit_payload.get('sha') or '').strip()
                if not re.fullmatch(r'[0-9a-fA-F]{40}', commit_sha):
                    raise ValueError('GitHub default branch did not resolve to an immutable commit')
                tree_sha = str((((commit_payload.get('commit') or {}).get('tree') or {}).get('sha')) or '').strip()
                if not re.fullmatch(r'[0-9a-fA-F]{40}', tree_sha):
                    commit_response = client.get(f'https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}')
                    commit_response.raise_for_status()
                    tree_sha = str(((commit_response.json().get('tree') or {}).get('sha')) or '').strip()
                if not re.fullmatch(r'[0-9a-fA-F]{40}', tree_sha):
                    raise ValueError('GitHub commit did not resolve to an immutable source tree')

                tree_response = client.get(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}', params={'recursive': '1'})
                if tree_response.status_code in {403, 404}:
                    raise ValueError('GitHub repository source tree could not be read')
                tree_response.raise_for_status()
                tree_payload = tree_response.json()
                all_items = list(tree_payload.get('tree') or [])[: self.max_paths]
                source_items = [
                    item for item in all_items
                    if item.get('type') == 'blob'
                    and PurePosixPath(str(item.get('path') or '')).suffix.lower() in _SOURCE_EXTENSIONS
                    and not any(part in _SKIP_PARTS for part in PurePosixPath(str(item.get('path') or '')).parts)
                    and int(item.get('size') or 0) <= self.max_file_bytes
                ]
                source_items.sort(key=lambda item: (str(item.get('path') or '').count('/'), int(item.get('size') or 0), str(item.get('path') or '').casefold()))
                selected = source_items[: self.max_source_files]
                files: dict[str, dict] = {}
                for item in selected:
                    path = str(item.get('path') or '')
                    encoded = quote(path, safe='/')
                    response = client.get(f'https://api.github.com/repos/{owner}/{repo}/contents/{encoded}', params={'ref': commit_sha}, headers={**headers, 'Accept': 'application/vnd.github.raw+json'})
                    if response.status_code != 200:
                        continue
                    text = response.text
                    if len(text.encode('utf-8', errors='ignore')) > self.max_file_bytes:
                        continue
                    suffix = PurePosixPath(path).suffix.lower()
                    symbols, imports = _python_facts(text) if suffix == '.py' else _script_facts(text)
                    files[path] = {'text': text, 'symbols': symbols, 'imports': imports, 'sha': str(item.get('sha') or ''), 'size': int(item.get('size') or len(text))}
        except ValueError:
            raise
        except httpx.HTTPError as exc:
            raise ValueError('GitHub repository could not be analyzed safely') from exc

        root = VisualNode(
            id='repository', label=title or str(metadata.get('name') or repo), category='project',
            description=f'Public GitHub repository {owner}/{repo} at {commit_sha[:12]}', evidence_level=EvidenceLevel.STRONG,
            evidence=[{'kind': 'repository', 'url': repository_url, 'branch': branch, 'ref': commit_sha, 'tree_sha': tree_sha}],
            metadata={'repository': f'{owner}/{repo}', 'branch': branch, 'commit_sha': commit_sha, 'tree_sha': tree_sha},
        )
        nodes = [root]
        edges: list[VisualEdge] = []
        file_ids: dict[str, str] = {}
        for index, (path, facts) in enumerate(files.items(), 1):
            node_id = _safe_id('file', path)
            if node_id in file_ids.values():
                node_id = f'{node_id}-{index}'
            file_ids[path] = node_id
            line_count = max(1, facts['text'].count('\n') + 1)
            evidence = {'kind': 'source_lines', 'repository': f'{owner}/{repo}', 'branch': branch, 'ref': commit_sha, 'path': path, 'line_start': 1, 'line_end': line_count, 'blob_sha': facts['sha'], 'url': f'{repository_url}/blob/{commit_sha}/{path}'}
            node = VisualNode(
                id=node_id, label=_label(path), category=_source_category(path), description=path,
                evidence_level=EvidenceLevel.VERIFIED, evidence=[evidence],
                metadata={'path': path, 'blob_sha': facts['sha'], 'commit_sha': commit_sha, 'size': facts['size'], 'symbols': facts['symbols'][:16]},
            )
            nodes.append(node)
            edges.append(VisualEdge(id=f'contains-{index}', source='repository', target=node_id, kind='contains', metadata={'evidence': [evidence]}))

            for sym_index, symbol in enumerate(facts['symbols'][:4], 1):
                symbol_id = _safe_id('symbol', f'{path}-{symbol["name"]}')
                symbol_evidence = {'kind': 'source_lines', 'repository': f'{owner}/{repo}', 'branch': branch, 'ref': commit_sha, 'path': path, 'line_start': symbol['line_start'], 'line_end': symbol['line_end'], 'blob_sha': facts['sha'], 'url': f'{repository_url}/blob/{commit_sha}/{path}#L{symbol["line_start"]}-L{symbol["line_end"]}'}
                nodes.append(VisualNode(
                    id=symbol_id, label=symbol['name'], category='api' if symbol.get('routes') or symbol['kind'] == 'route' else 'symbol',
                    description=f"{symbol['kind'].title()} in {path}", evidence_level=EvidenceLevel.VERIFIED,
                    evidence=[symbol_evidence], metadata={'path': path, 'commit_sha': commit_sha, 'symbol_kind': symbol['kind'], 'routes': symbol.get('routes') or []},
                ))
                edges.append(VisualEdge(id=f'defines-{index}-{sym_index}', source=node_id, target=symbol_id, kind='defines', metadata={'evidence': [symbol_evidence]}))

        known_paths = set(files)
        edge_index = 0
        for source_path, facts in files.items():
            source_id = file_ids[source_path]
            seen_targets: set[str] = set()
            for imported in facts['imports']:
                target_path = _resolve_import(source_path, str(imported.get('module') or ''), known_paths)
                if not target_path or target_path == source_path or target_path in seen_targets:
                    continue
                seen_targets.add(target_path)
                edge_index += 1
                line = int(imported.get('line') or 1)
                evidence = {'kind': 'source_lines', 'repository': f'{owner}/{repo}', 'branch': branch, 'ref': commit_sha, 'path': source_path, 'line_start': line, 'line_end': line, 'blob_sha': files[source_path]['sha'], 'url': f'{repository_url}/blob/{commit_sha}/{source_path}#L{line}'}
                edges.append(VisualEdge(id=f'import-{edge_index}', source=source_id, target=file_ids[target_path], label='imports', kind='imports', metadata={'evidence_level': EvidenceLevel.VERIFIED.value, 'evidence': [evidence]}))

        return VisualGraph(
            type=VisualType.ARCHITECTURE,
            title=title or f'{owner}/{repo} Architecture',
            nodes=nodes,
            edges=edges,
            metadata={
                'analysis': 'github-source-code', 'repository': f'{owner}/{repo}', 'repository_url': repository_url,
                'branch': branch, 'commit_sha': commit_sha, 'tree_sha': tree_sha, 'tree_truncated': bool(tree_payload.get('truncated')),
                'path_count': len(all_items), 'source_candidates': len(source_items), 'source_files_analyzed': len(files),
                'evidence_policy': 'verified means exact fetched source lines pinned to the recorded immutable commit SHA',
            },
        )
