from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response


_VISUALIZE_HEAD = (
    '<link rel="stylesheet" href="/iphone/visualize-workspace.css" />'
    '<link rel="stylesheet" href="/iphone/visualize-sources.css" />'
    '<link rel="stylesheet" href="/iphone/visualize-advanced.css" />'
)
_VISUALIZE_SCRIPT = (
    '<script src="/iphone/visualize-workspace.js" defer></script>'
    '<script src="/iphone/visualize-sources.js" defer></script>'
    '<script src="/iphone/visualize-advanced.js" defer></script>'
)


class VisualizeUiMiddleware:
    """Inject the isolated Visualize bundle into only the canonical /iphone shell.

    The existing PWA remains authoritative. This middleware does not rewrite API,
    manifest, service-worker, or asset responses and therefore keeps navigation
    integration reversible and independently testable.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or scope.get('path') not in {'/iphone', '/iphone/'}:
            await self.app(scope, receive, send)
            return

        status = 200
        headers = []
        chunks: list[bytes] = []

        async def capture(message):
            nonlocal status, headers
            if message['type'] == 'http.response.start':
                status = int(message['status'])
                headers = list(message.get('headers') or [])
                return
            if message['type'] == 'http.response.body':
                chunks.append(message.get('body', b''))
                if not message.get('more_body', False):
                    body = b''.join(chunks)
                    content_type = ''
                    content_encoding = ''
                    for key, value in headers:
                        lowered = key.lower()
                        if lowered == b'content-type':
                            content_type = value.decode('latin-1').lower()
                        elif lowered == b'content-encoding':
                            content_encoding = value.decode('latin-1').lower()
                    if status == 200 and 'text/html' in content_type and not content_encoding:
                        text = body.decode('utf-8')
                        if '/iphone/visualize-workspace.css' not in text:
                            if '</head>' in text:
                                text = text.replace('</head>', f'{_VISUALIZE_HEAD}</head>', 1)
                            else:
                                text = _VISUALIZE_HEAD + text
                        elif '/iphone/visualize-advanced.css' not in text and '</head>' in text:
                            text = text.replace('</head>', '<link rel="stylesheet" href="/iphone/visualize-advanced.css" /></head>', 1)
                        if '/iphone/visualize-workspace.js' not in text:
                            if '</body>' in text:
                                text = text.replace('</body>', f'{_VISUALIZE_SCRIPT}</body>', 1)
                            else:
                                text += _VISUALIZE_SCRIPT
                        elif '/iphone/visualize-advanced.js' not in text and '</body>' in text:
                            text = text.replace('</body>', '<script src="/iphone/visualize-advanced.js" defer></script></body>', 1)
                        body = text.encode('utf-8')
                    filtered = [(key, value) for key, value in headers if key.lower() != b'content-length']
                    filtered.append((b'content-length', str(len(body)).encode('ascii')))
                    await send({'type': 'http.response.start', 'status': status, 'headers': filtered})
                    await send({'type': 'http.response.body', 'body': body, 'more_body': False})

        await self.app(scope, receive, capture)


def visualize_assets_router(settings):
    router = APIRouter(prefix='/iphone', tags=['visualize-ui'])
    web_dir = Path(settings.base_dir) / 'pwa'

    def asset(name: str, media_type: str):
        return Response((web_dir / name).read_text(encoding='utf-8'), media_type=media_type, headers={'Cache-Control': 'no-cache'})

    @router.get('/visualize-workspace.js', include_in_schema=False)
    def visualize_script(): return asset('visualize-workspace.js', 'application/javascript')

    @router.get('/visualize-workspace.css', include_in_schema=False)
    def visualize_styles(): return asset('visualize-workspace.css', 'text/css')

    @router.get('/visualize-sources.js', include_in_schema=False)
    def visualize_sources_script(): return asset('visualize-sources.js', 'application/javascript')

    @router.get('/visualize-sources.css', include_in_schema=False)
    def visualize_sources_styles(): return asset('visualize-sources.css', 'text/css')

    @router.get('/visualize-advanced.js', include_in_schema=False)
    def visualize_advanced_script(): return asset('visualize-advanced.js', 'application/javascript')

    @router.get('/visualize-advanced.css', include_in_schema=False)
    def visualize_advanced_styles(): return asset('visualize-advanced.css', 'text/css')

    return router