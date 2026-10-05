from __future__ import annotations

import base64
import binascii
from datetime import date
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_iso_date(value):
    if value is None or value == '':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Dates must use the YYYY-MM-DD format')
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Dates must use the YYYY-MM-DD format') from exc
    return value

from projects.store import ProjectStore
from security.request_context import current_trusted_request


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default='', max_length=500)
    description: str = Field(default='', max_length=4000)
    target_date: str | None = Field(default=None, max_length=40)
    project_type: str = Field(default='software', pattern='^(software|business|research|writing|personal)$')
    success_criteria: str = Field(default='', max_length=500)
    instructions: str = Field(default='', max_length=500)
    context_notes: str = Field(default='', max_length=4000)
    tasks: list['ProjectTaskDraft'] = Field(default_factory=list, max_length=30)
    milestones: list['ProjectMilestoneDraft'] = Field(default_factory=list, max_length=15)

    @field_validator('target_date')
    @classmethod
    def valid_target_date(cls, value):
        return _validate_iso_date(value)

    @model_validator(mode='after')
    def validate_plan_links(self):
        milestone_ids = [item.client_id for item in self.milestones]
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ValueError('Milestone identifiers in the proposed plan must be unique')
        task_ids = [item.client_id for item in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError('Task identifiers in the proposed plan must be unique')
        allowed = set(milestone_ids)
        if any(task.milestone_client_id and task.milestone_client_id not in allowed for task in self.tasks):
            raise ValueError('A proposed task links to a missing milestone')
        return self


class ProjectTaskDraft(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=4000)
    context_notes: str = Field(default='', max_length=2000)
    priority: str = Field(default='medium', pattern='^(low|medium|high)$')
    owner: str = Field(default='owner', pattern='^(owner|vishnu)$')
    due_date: str | None = Field(default=None, max_length=40)
    milestone_client_id: str | None = Field(default=None, max_length=80)

    @field_validator('due_date')
    @classmethod
    def valid_due_date(cls, value):
        return _validate_iso_date(value)


class ProjectMilestoneDraft(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    outcome: str = Field(min_length=1, max_length=2000)
    completion_criteria: str = Field(min_length=1, max_length=2000)
    target_date: str = Field(min_length=1, max_length=40)

    @field_validator('target_date')
    @classmethod
    def valid_target_date(cls, value):
        return _validate_iso_date(value)


ProjectCreateBody.model_rebuild()


class ProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    target_date: str | None = Field(default=None, max_length=40)
    project_type: str | None = Field(default=None, pattern='^(software|business|research|writing|personal)$')
    success_criteria: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=500)
    context_notes: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern='^(active|paused|completed|archived)$')

    @field_validator('target_date')
    @classmethod
    def valid_target_date(cls, value):
        return _validate_iso_date(value)


class TaskCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=4000)
    context_notes: str = Field(default='', max_length=2000)
    priority: str = Field(default='medium', pattern='^(low|medium|high)$')
    status: str = Field(default='planned', pattern='^(planned|in_progress|blocked|needs_review|paused|done|failed)$')
    owner: str = Field(default='vishnu', pattern='^(owner|vishnu)$')
    due_date: str | None = Field(default=None, max_length=40)
    milestone_id: str | None = Field(default=None, max_length=80)
    file_ids: list[str] = Field(default_factory=list, max_length=30)

    @field_validator('due_date')
    @classmethod
    def valid_due_date(cls, value):
        return _validate_iso_date(value)


class TaskUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    context_notes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern='^(planned|in_progress|blocked|needs_review|paused|done|failed)$')
    priority: str | None = Field(default=None, pattern='^(low|medium|high)$')
    owner: str | None = Field(default=None, pattern='^(owner|vishnu)$')
    due_date: str | None = Field(default=None, max_length=40)
    milestone_id: str | None = Field(default=None, max_length=80)
    file_ids: list[str] | None = Field(default=None, max_length=30)

    @field_validator('due_date')
    @classmethod
    def valid_due_date(cls, value):
        return _validate_iso_date(value)


class MilestoneCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    outcome: str = Field(min_length=1, max_length=2000)
    target_date: str = Field(min_length=1, max_length=40)
    completion_criteria: str = Field(min_length=1, max_length=2000)
    task_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator('target_date')
    @classmethod
    def valid_target_date(cls, value):
        return _validate_iso_date(value)


class MilestoneUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    outcome: str | None = Field(default=None, min_length=1, max_length=2000)
    status: str | None = Field(default=None, pattern='^(planned|in_progress|blocked|done)$')
    target_date: str | None = Field(default=None, min_length=1, max_length=40)
    completion_criteria: str | None = Field(default=None, min_length=1, max_length=2000)
    task_ids: list[str] | None = Field(default=None, max_length=100)

    @field_validator('target_date')
    @classmethod
    def valid_target_date(cls, value):
        return _validate_iso_date(value)


class FileLinkBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    url: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default='link', pattern='^(link|knowledge|upload)$')
    knowledge_id: str | None = Field(default=None, max_length=100)


class ProjectFileUploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    media_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1, max_length=16_800_000)


class ProjectFileUpdateBody(BaseModel):
    is_pinned: bool


class DiscussionCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=4000)
    linked_item_type: str = Field(default='', pattern='^(|project_brief|task|file|milestone|proposal)$')
    linked_item_id: str | None = Field(default=None, max_length=100)


class DiscussionUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    status: str | None = Field(default=None, pattern='^(open|resolved)$')
    linked_item_type: str | None = Field(default=None, pattern='^(|project_brief|task|file|milestone|proposal)$')
    linked_item_id: str | None = Field(default=None, max_length=100)
    pinned_reply_id: str | None = Field(default=None, max_length=100)
    followed: bool | None = None


class DiscussionReplyBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ProjectApprovalBody(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=4000)
    impact_summary: str = Field(min_length=1, max_length=2000)
    scope_summary: str = Field(min_length=1, max_length=2000)
    task_ids: list[str] = Field(default_factory=list, max_length=100)
    file_ids: list[str] = Field(default_factory=list, max_length=100)


class ProjectApprovalDecisionBody(BaseModel):
    decision: str = Field(pattern='^(approved|changes_requested)$')
    comments: str = Field(default='', max_length=4000)


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
                      status: str = Query(default='all', pattern='^(all|active|paused|needs_review|completed|archived)$'),
                      sort: str = Query(default='recent', pattern='^(recent|name|created)$'),
                      pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token)
        return {'projects': store.list(q, status=status, sort=sort)}

    @router.post('', status_code=201)
    def create_project(body: ProjectCreateBody,
                       pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        name = body.name.strip()
        if not name:
            raise HTTPException(422, 'A project name is required')
        draft = body.model_dump()
        draft['tasks'] = [item.model_dump() for item in body.tasks]
        draft['milestones'] = [item.model_dump() for item in body.milestones]
        return {'project': store.create(**draft)}

    @router.post('/walkthrough', status_code=201)
    def create_walkthrough_project(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        return {'project': store.create_walkthrough()}

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
            fields = body.model_dump(exclude_unset=True)
            fields = {key: value for key, value in fields.items() if value is not None or key == 'target_date'}
            value = store.update(project_id, fields)
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

    @router.post('/{project_id}/restore')
    def restore_project(project_id: str,
                        pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        if not store.restore(project_id):
            raise HTTPException(404, 'Archived project not found')
        return {'project': project_or_404(project_id)}

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
            fields = body.model_dump(exclude_unset=True)
            fields = {key: value for key, value in fields.items() if value is not None or key in {'milestone_id', 'due_date'}}
            value = store.update_task(project_id, task_id, fields)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Task or project not found')
        return {'project': value}

    @router.post('/{project_id}/milestones', status_code=201)
    def add_milestone(project_id: str, body: MilestoneCreateBody,
                      pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.add_milestone(project_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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

    @router.post('/{project_id}/approvals', status_code=201)
    def create_project_approval(project_id: str, body: ProjectApprovalBody,
                                pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.add_approval(project_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Project not found')
        return {'project': value}

    @router.post('/{project_id}/approvals/{approval_id}/decision')
    def decide_project_approval(project_id: str, approval_id: str, body: ProjectApprovalDecisionBody,
                                pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.decide_approval(project_id, approval_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(409 if 'already' in str(exc) else 422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Proposal not found')
        return {'project': value, 'execution_started': False}

    @router.post('/{project_id}/approvals/{approval_id}/resubmit')
    def resubmit_project_approval(project_id: str, approval_id: str, body: ProjectApprovalBody,
                                  pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        try:
            value = store.revise_approval(project_id, approval_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(409 if 'Only proposals' in str(exc) else 422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Proposal not found')
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

    @router.patch('/{project_id}/files/{file_id}')
    def update_project_file(project_id: str, file_id: str, body: ProjectFileUpdateBody,
                            pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        value = store.update_file(project_id, file_id, body.model_dump())
        if not value:
            raise HTTPException(404, 'Project file not found')
        return {'project': value}

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

    @router.patch('/{project_id}/discussions/{thread_id}')
    def update_discussion(project_id: str, thread_id: str, body: DiscussionUpdateBody,
                          pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, write=True)
        project_or_404(project_id)
        try:
            value = store.update_thread(project_id, thread_id, body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not value:
            raise HTTPException(404, 'Discussion not found')
        return {'project': value}

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
