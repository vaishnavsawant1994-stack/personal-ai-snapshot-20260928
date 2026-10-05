from __future__ import annotations

import base64
import binascii
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from pydantic import BaseModel, Field

from projects.store import ProjectStore
from security.request_context import current_trusted_request


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default='', max_length=2000)
    description: str = Field(default='', max_length=4000)
    target_date: str | None = Field(default=None, max_length=40)


class ProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    target_date: str | None = Field(default=None, max_length=40)


class TaskCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=4000)
    priority: str = Field(default='medium', pattern='^(low|medium|high)$')
    owner: str = Field(default='vishnu', pattern='^(owner|vishnu)$')
    due_date: str | None = Field(default=None, max_length=40)
    milestone_id: str | None = Field(default=None, max_length=80)


class TaskUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern='^(planned|in_progress|blocked|done)$')
    priority: str | None = Field(default=None, pattern='^(low|medium|high)$')
    owner: str | None = Field(default=None, pattern='^(owner|vishnu)$')
    due_date: str | None = Field(default=None, max_length=40)
    milestone_id: str | None = Field(default=None, max_length=80)


class MilestoneCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    outcome: str = Field(default='', max_length=2000)
    target_date: str | None = Field(default=None, max_length=40)


class MilestoneUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    outcome: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern='^(planned|in_progress|blocked|done)$')
    target_date: str | None = Field(default=None, max_length=40)


class FileLinkBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    url: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default='link', pattern='^(link|knowledge|upload)$')
    knowledge_id: str | None = Field(default=None, max_length=100)


class ProjectFileUploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    media_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1, max_length=16_800_000)


class DiscussionCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=4000)


class DiscussionReplyBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


def projects_router(runtime, store: ProjectStore):
    router = APIRouter(prefix='/iphone/api/projects', tags=['projects-workspace'])
    registry = runtime['device_registry']
    continuity = runtime.get('continuity')

    def authenticate(device_id: str | None, token: str | None, *, write=False):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'ai:chat'):
            raise HTTPException(403, 'This device is not permitted to use the project workspace')
        context = current_trusted_request()
        if write and (context is None or context.device_id != device_id):
            raise HTTPException(401, 'A current trusted owner session is required to change project data')
        return device_id

    def project_or_404(project_id):
        value = store.get(project_id)
        if not value:
            raise HTTPException(404, 'Project not found')
        return value

    @router.get('')
    def list_projects(q: str = Query(default='', max_length=120),
                      pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        return {'projects': store.list(q)}

    @router.post('', status_code=201)
    def create_project(body: ProjectCreateBody,
                       pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        name = body.name.strip()
        if not name:
            raise HTTPException(422, 'A project name is required')
        return {'project': store.create(name=name, goal=body.goal, description=body.description, target_date=body.target_date)}

    @router.get('/{project_id}')
    def get_project(project_id: str,
                    pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        return {'project': project_or_404(project_id)}

    @router.patch('/{project_id}')
    def update_project(project_id: str, body: ProjectUpdateBody,
                       pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.update(project_id, body.model_dump(exclude_unset=True, exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.delete('/{project_id}', status_code=204)
    def archive_project(project_id: str,
                        pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        if not store.archive(project_id):
            raise HTTPException(404, 'Project not found')

    @router.post('/{project_id}/tasks', status_code=201)
    def add_task(project_id: str, body: TaskCreateBody,
                 pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.add_task(project_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.patch('/{project_id}/tasks/{task_id}')
    def update_task(project_id: str, task_id: str, body: TaskUpdateBody,
                    pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.update_task(project_id, task_id, body.model_dump(exclude_unset=True, exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Task or project not found')
        return {'project': value}

    @router.post('/{project_id}/milestones', status_code=201)
    def add_milestone(project_id: str, body: MilestoneCreateBody,
                      pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        value = store.add_milestone(project_id, **body.model_dump())
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.patch('/{project_id}/milestones/{milestone_id}')
    def update_milestone(project_id: str, milestone_id: str, body: MilestoneUpdateBody,
                         pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        value = store.update_milestone(project_id, milestone_id, body.model_dump(exclude_unset=True, exclude_none=True))
        if not value:
            raise HTTPException(404, 'Milestone or project not found')
        return {'project': value}

    @router.post('/{project_id}/files', status_code=201)
    def add_file(project_id: str, body: FileLinkBody,
                 pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        parsed = urlparse(body.url)
        if body.kind == 'link' and parsed.scheme not in {'https', 'http'}:
            raise HTTPException(422, 'Project links must use http or https')
        if body.kind == 'knowledge' and not body.knowledge_id:
            raise HTTPException(422, 'A Knowledge document id is required')
        value = store.add_file(project_id, **body.model_dump())
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.post('/{project_id}/files/upload', status_code=201)
    def upload_project_file(project_id: str, body: ProjectFileUploadBody,
                            pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, 'The uploaded file is not valid base64 data') from exc
        if not content or len(content) > 12 * 1024 * 1024:
            raise HTTPException(413, 'Project files must be smaller than 12 MB')
        suffix = body.filename.rsplit('.', 1)[-1].lower() if '.' in body.filename else ''
        supported = {'pdf', 'docx', 'xlsx', 'csv', 'txt', 'md', 'png', 'jpg', 'jpeg', 'webp'}
        if suffix not in supported:
            raise HTTPException(415, 'Supported files: PDF, DOCX, XLSX, CSV, TXT, Markdown, PNG, JPG and WebP')
        value = store.add_upload(project_id, title=body.filename, media_type=body.media_type, content=content)
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.get('/{project_id}/files/{file_id}/download')
    def download_project_file(project_id: str, file_id: str,
                              pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        blob = store.file_blob(project_id, file_id)
        if not blob:
            raise HTTPException(404, 'Project file not found')
        filename = blob['title'].replace('"', '')
        return Response(blob['content'], media_type=blob['media_type'], headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(blob['size_bytes']),
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store',
        })

    @router.post('/{project_id}/discussions', status_code=201)
    def add_discussion(project_id: str, body: DiscussionCreateBody,
                       pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        value = store.add_thread(project_id, **body.model_dump())
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.post('/{project_id}/discussions/{thread_id}/replies', status_code=201)
    def add_discussion_reply(project_id: str, thread_id: str, body: DiscussionReplyBody,
                             pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, write=True)
        author = 'owner'
        if not store.add_reply(project_id, thread_id, author=author, content=body.content):
            raise HTTPException(404, 'Discussion not found')
        return {'project': project_or_404(project_id)}

    @router.post('/{project_id}/conversation', status_code=201)
    def project_conversation(project_id: str,
                             pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, write=True)
        project = project_or_404(project_id)
        if continuity is None:
            raise HTTPException(503, 'Conversation service is unavailable')
        conversation_id = project.get('conversation_id')
        if not conversation_id or not continuity.thread(conversation_id):
            conversation_id = continuity.create_thread(f"Project · {project['name']} · Vishnu", device_id=device_id)
            store.update(project_id, {'conversation_id': conversation_id})
        return {'conversation_id': conversation_id, 'project': project_or_404(project_id)}

    @router.post('/{project_id}/activity', status_code=201)
    def record_project_activity(project_id: str, body: DiscussionReplyBody,
                                pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        if not store.record(project_id, actor='owner', action='asked Vishnu', target_type='conversation', detail=body.content):
            raise HTTPException(404, 'Project not found')
        return {'project': project_or_404(project_id)}

    return router
