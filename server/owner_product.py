from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from io import BytesIO
from pathlib import Path
from typing import Literal
from io import BytesIO
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.background import BackgroundTask

from knowledge.store import KnowledgeError
from memory.second_brain import MemoryCandidate
from security.request_context import current_trusted_request


class MemoryCreateBody(BaseModel):
    type: str = Field(default='note', min_length=1, max_length=60)
    subject: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    source: str = Field(default='explicit-owner', max_length=240)
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = True
    sensitivity: Literal['normal', 'sensitive', 'secret', 'never_store'] = 'normal'
    tags: list[str] = Field(default_factory=list, max_length=50)
    importance: float = Field(default=.7, ge=0, le=1)
    occurred_at: str | None = None
    parent_id: str | None = None
    scope: Literal['personal', 'project'] = 'personal'
    project_id: str | None = None


class MemoryUpdateBody(BaseModel):
    type: str | None = Field(default=None, max_length=60)
    subject: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=20000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool | None = None
    sensitivity: Literal['normal', 'sensitive', 'secret', 'never_store'] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    importance: float | None = Field(default=None, ge=0, le=1)
    occurred_at: str | None = None
    parent_id: str | None = None
    scope: Literal['personal', 'project'] | None = None
    project_id: str | None = None


class RetentionBody(BaseModel):
    older_than_days: int = Field(ge=1, le=36500)
    sensitivity: Literal['normal', 'sensitive', 'secret'] | None = None
    confirm_delete: bool = False


class MemoryPreferencesBody(BaseModel):
    memory_enabled: bool | None = None
    review_before_saving: bool | None = None


class KnowledgeAvailabilityBody(BaseModel):
    available_to_vishnu: bool


class KnowledgeCollectionBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=500)


class KnowledgeCollectionUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class KnowledgeUploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    title: str | None = Field(default=None, max_length=240)
    media_type: str = Field(default='application/octet-stream', max_length=160)
    source: str = Field(default='owner-upload', max_length=500)
    access_class: Literal['owner', 'trusted-devices', 'private'] = 'owner'
    item_kind: Literal['document', 'note', 'link'] = 'document'
    collection_id: str | None = None
    link_url: str | None = Field(default=None, max_length=2048)
    content_base64: str | None = Field(default=None, max_length=14_000_000)
    text: str | None = Field(default=None, max_length=10_000_000)
    metadata: dict = Field(default_factory=dict)


class KnowledgeUpdateBody(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    source: str | None = Field(default=None, max_length=500)
    access_class: Literal['owner', 'trusted-devices', 'private'] | None = None
    collection_id: str | None = None
    metadata: dict | None = None


class DevicePermissionsBody(BaseModel):
    scopes: list[str] = Field(max_length=30)


class ConfirmBody(BaseModel):
    confirm: Literal[True]


class DeleteAccountBody(BaseModel):
    confirm: Literal['DELETE']


class QualificationSessionBody(BaseModel):
    stage: Literal['P3.2', 'P3.3', 'P3.4', 'P3.5', 'P3.6', 'P3.7', 'P3.8']
    evidence_class: Literal['real_device', 'production_like', 'competitive']
    environment: dict = Field(default_factory=dict)


class QualificationTrialBody(BaseModel):
    task: str = Field(min_length=1, max_length=240)
    passed: bool
    latency_ms: float | None = Field(default=None, ge=0)
    metrics: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class QualificationFinishBody(BaseModel):
    duration_seconds: float | None = Field(default=None, ge=0)


class WorkflowCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    trigger: dict = Field(default_factory=lambda: {'type': 'manual'})
    steps: list[dict] = Field(min_length=1, max_length=50)
    next_run_at: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)


class WorkflowPauseBody(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=200)
    paused: bool


class WorkflowRunBody(BaseModel):
    context: dict = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=16, max_length=160)


class EmergencyStopBody(BaseModel):
    enabled: bool


class UiPreferencesBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_display_name: str = Field(default='', max_length=80)
    continuous_voice: bool = True
    voice_rate: float = Field(default=1.0, ge=0.75, le=1.35)
    quiet_hours: bool = True
    privacy_memory_enabled: bool = True
    privacy_review_before_saving: bool = True
    privacy_allow_project_context_general: bool = False
    privacy_save_conversations: bool = True
    privacy_retention: Literal['until_deleted'] = 'until_deleted'
    privacy_share_anonymous_usage_data: bool = False
    appearance_theme: Literal['dark', 'light', 'system'] = 'dark'
    appearance_accent: Literal['blue', 'teal', 'violet', 'amber', 'rose'] = 'blue'
    appearance_density: Literal['comfortable', 'compact'] = 'comfortable'
    appearance_motion: Literal['standard', 'reduced'] = 'standard'
    appearance_text_size: Literal['small', 'default', 'large'] = 'default'
    chat_enter_sends: bool = True
    chat_keep_composer_visible: bool = True
    chat_response_detail: Literal['concise', 'balanced', 'detailed'] = 'detailed'
    chat_response_style: Literal['clear_step_by_step', 'warm_conversational', 'technical', 'direct'] = 'clear_step_by_step'
    chat_show_sources: bool = True
    chat_show_timestamps: bool = True
    chat_show_actions: bool = True
    chat_message_spacing: Literal['comfortable', 'compact'] = 'comfortable'
    chat_new_context: Literal['general', 'project'] = 'general'
    chat_project_context_enabled: bool = False
    locale_app_language: Literal['en'] = 'en'
    locale_region: Literal['IN', 'US', 'GB', 'CA', 'AU', 'DE', 'FR', 'JP'] = 'IN'
    locale_time_zone: str = Field(default='Asia/Kolkata', min_length=1, max_length=80)
    locale_use_device_time_zone: bool = False
    locale_date_format: Literal['day_month_year', 'month_day_year', 'numeric'] = 'day_month_year'
    locale_time_format: Literal['12h', '24h'] = '12h'
    locale_week_start: Literal['monday', 'sunday'] = 'monday'
    locale_number_format: Literal['indian', 'western'] = 'indian'
    locale_temperature: Literal['celsius', 'fahrenheit'] = 'celsius'
    locale_measurement: Literal['metric', 'imperial'] = 'metric'
    pinned_sidebar_items: list[str] = Field(default_factory=list, max_length=40)

    @field_validator('locale_time_zone')
    @classmethod
    def valid_iana_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Time zone must be a valid IANA identifier') from exc
        return value



class ProfileAvatarBody(BaseModel):
    media_type: Literal['image/jpeg', 'image/png', 'image/webp']
    data_base64: str = Field(min_length=1, max_length=2_800_000)


class ProfileUpdateBody(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator('first_name', 'last_name', 'display_name')
    @classmethod
    def non_blank_profile_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Name fields cannot be blank')
        return value


class NotificationEventPreference(BaseModel):
    enabled: bool
    channels: list[Literal['in_app', 'push', 'email']] = Field(max_length=3)


class NotificationQuietHours(BaseModel):
    enabled: bool
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    timezone: str = Field(min_length=1, max_length=80)


class NotificationSummaryPreference(BaseModel):
    enabled: bool
    time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')


class WeeklySummaryPreference(NotificationSummaryPreference):
    weekday: int = Field(ge=0, le=6)


class NotificationPreferencesBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    events: dict[Literal['task_reminders', 'work_completed', 'needs_review', 'blocked_work', 'workflow_updates', 'product_updates'], NotificationEventPreference]
    quiet_hours: NotificationQuietHours
    allow_urgent_reviews: bool
    daily_summary: NotificationSummaryPreference
    weekly_summary: WeeklySummaryPreference

    @classmethod
    def _check_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Choose a valid time zone') from exc
        return value

    @field_validator('quiet_hours')
    @classmethod
    def valid_timezone(cls, value):
        cls._check_timezone(value.timezone)
        return value

    @field_validator('events')
    @classmethod
    def reject_duplicate_channels(cls, value):
        for event in value.values():
            if len(event.channels) != len(set(event.channels)):
                raise ValueError('Notification channels cannot be duplicated')
        return value


def stage_owner_data_deletion(data_dir: Path) -> Path:
    """Atomically detach this single-owner installation's complete data directory."""
    target = Path(data_dir)
    if target.is_symlink() or not target.exists() or not target.is_dir():
        raise ValueError('Owner data directory is unavailable')
    resolved = target.resolve(strict=True)
    if resolved in {Path('/'), Path.home(), Path.cwd().resolve()}:
        raise ValueError('Refusing to delete an unsafe data directory')
    tombstone = resolved.with_name(f'.{resolved.name}.deleted-{uuid.uuid4().hex}')
    os.replace(resolved, tombstone)
    return tombstone



def stage_owner_data_deletion(data_dir: Path) -> Path:
    """Atomically detach this single-owner installation's complete data directory."""
    target = Path(data_dir)
    if target.is_symlink() or not target.exists() or not target.is_dir():
        raise ValueError('Owner data directory is unavailable')
    resolved = target.resolve(strict=True)
    if resolved in {Path('/'), Path.home(), Path.cwd().resolve()}:
        raise ValueError('Refusing to delete an unsafe data directory')
    tombstone = resolved.with_name(f'.{resolved.name}.deleted-{uuid.uuid4().hex}')
    os.replace(resolved, tombstone)
    return tombstone


def _bounded_mapping(value, *, max_bytes=65536, max_depth=8, max_items=256, max_string=12000):
    if not isinstance(value, dict):
        raise HTTPException(422, 'Expected a JSON object')
    nodes = 0
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise HTTPException(413, 'JSON object nesting exceeds limit')
        if isinstance(current, dict):
            if len(current) > max_items:
                raise HTTPException(413, 'JSON object contains too many fields')
            for key, child in current.items():
                if len(str(key)) > 256:
                    raise HTTPException(413, 'JSON object key is too long')
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > max_items:
                raise HTTPException(413, 'JSON collection contains too many items')
            for child in current:
                stack.append((child, depth + 1))
        elif isinstance(current, str) and len(current) > max_string:
            raise HTTPException(413, 'JSON string exceeds limit')
        nodes += 1
        if nodes > 4096:
            raise HTTPException(413, 'JSON object is too complex')
    try:
        encoded = json.dumps(value, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, 'JSON object contains unsupported values') from exc
    if len(encoded) > max_bytes:
        raise HTTPException(413, 'JSON object exceeds maximum size')
    return value


def owner_product_router(runtime):
    router = APIRouter(prefix='/iphone/api', tags=['owner-product'])
    registry = runtime['device_registry']
    memory = runtime['memory']
    second_brain = runtime['second_brain']
    knowledge = runtime['knowledge']

    def authenticate(device_id: str | None, token: str | None, scope: str):
        if not device_id or not token or not registry.authenticate(device_id, token):
            raise HTTPException(401, 'This browser is not trusted or its session was revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return device_id

    def audit(action: str, *, device_id: str, **payload):
        memory.audit('owner-product', action, {'device_id': device_id, **payload})

    def require_fresh_reauthentication():
        context = current_trusted_request()
        ttl = int(getattr(runtime.get('agent_executor'), 'reauth_ttl_seconds', 300) or 300)
        ttl = max(30, min(ttl, 900))
        stamp = getattr(context, 'reauthenticated_at', None) if context is not None else None
        try:
            age = time.time() - float(stamp)
        except (TypeError, ValueError):
            age = ttl + 1
        if context is None or age < 0 or age > ttl:
            raise HTTPException(401, {
                'code': 'reauthentication_required',
                'message': 'Fresh owner verification is required for this security-sensitive action.',
            })
        return context

    def workflow_authority(device_id: str):
        context = current_trusted_request()
        if context is not None and context.device_id != device_id:
            raise HTTPException(403, 'Authenticated browser session does not match this device')
        return {
            'owner_id': 'owner',
            'device_id': device_id,
            'session_id': context.session_id if context is not None else None,
            'reauthenticated_at': context.reauthenticated_at if context is not None else None,
        }

    def workflow_binding_matches(engine, run_id: str, auth: dict) -> bool:
        reader = getattr(engine, 'run_binding', None)
        if not callable(reader):
            return False
        binding = reader(run_id)
        if not binding:
            return False
        return (
            binding.get('owner_id') in (None, auth['owner_id'])
            and binding.get('device_id') in (None, auth['device_id'])
            and binding.get('session_id') in (None, auth['session_id'])
        )

    def knowledge_access(device_id: str):
        classes = {'owner', 'trusted-devices'}
        if not hasattr(registry, 'authorize') or registry.authorize(device_id, 'knowledge:private'):
            classes.add('private')
        return classes

    def ui_preferences(device_id: str):
        defaults = UiPreferencesBody().model_dump()
        try:
            stored = json.loads(registry.metadata(device_id).get('ui.preferences', '{}'))
        except (TypeError, ValueError, json.JSONDecodeError):
            stored = {}
        app_preferences = runtime.get('preferences')
        if app_preferences is not None:
            stored = {**stored, 'privacy_memory_enabled': bool(app_preferences.get('memory_enabled', True)), 'profile_display_name': str(app_preferences.get('preferred_name', '') or '')}
        try:
            return UiPreferencesBody(**{**defaults, **stored}).model_dump()
        except (TypeError, ValueError):
            return defaults

    @router.get('/preferences')
    def preferences_get(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        return ui_preferences(device_id)

    @router.put('/preferences')
    def preferences_update(
        body: UiPreferencesBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        value = body.model_dump()
        if value['privacy_allow_project_context_general'] or value['chat_project_context_enabled'] or value['chat_new_context'] == 'project':
            raise HTTPException(422, 'Project context is not available for general chats in this installation')
        if not registry.set_metadata(device_id, 'ui.preferences', json.dumps(value, separators=(',', ':'))):
            raise HTTPException(404, 'Active device not found')
        app_preferences = runtime.get('preferences')
        if app_preferences is not None:
            app_preferences.set('memory_enabled', value['privacy_memory_enabled'])
            app_preferences.set('preferred_name', value['profile_display_name'].strip())
        audit('device.preferences.updated', device_id=device_id)
        return value

    @router.get('/notifications/preferences')
    def notification_preferences_get(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        service = runtime.get('notifications')
        if service is None:
            raise HTTPException(503, 'Notification preferences are unavailable')
        return {'preferences': service.preferences(device_id), 'availability': service.status(device_id)}

    @router.put('/notifications/preferences')
    def notification_preferences_update(body: NotificationPreferencesBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        service = runtime.get('notifications')
        if service is None:
            raise HTTPException(503, 'Notification preferences are unavailable')
        value = body.model_dump()
        # Reject channels that cannot actually deliver in this installation.
        supported_events = set(service.status(device_id).get('supported_events', []))
        for category, rule in value['events'].items():
            if category not in supported_events and (rule['enabled'] or rule['channels']):
                raise HTTPException(422, f'{category.replace("_", " ").title()} events are not available in this installation')
        for rule in value['events'].values():
            if 'email' in rule['channels']:
                raise HTTPException(422, 'Email delivery is not configured on this installation')
        if not service.status(device_id)['push'] and any('push' in rule['channels'] for rule in value['events'].values()):
            raise HTTPException(422, 'Push delivery is not configured for this trusted device')
        try:
            saved = service.save_preferences(device_id, value)
        except KeyError as exc:
            raise HTTPException(404, 'Active device not found') from exc
        audit('notifications.preferences.updated', device_id=device_id)
        return {'preferences': saved, 'availability': service.status(device_id)}

    @router.get('/notifications/inbox')
    def notification_inbox(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        service = runtime.get('notifications')
        if service is None:
            raise HTTPException(503, 'Notification inbox is unavailable')
        items = service.list(device_id)
        return {'notifications': items, 'unread_count': sum(1 for item in items if not item['read_at'])}

    @router.post('/notifications/inbox/{notification_id}/read')
    def notification_mark_read(notification_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        service = runtime.get('notifications')
        if service is None:
            raise HTTPException(503, 'Notification inbox is unavailable')
        if not service.mark_read(device_id, notification_id):
            raise HTTPException(404, 'Notification not found')
        return {'marked_read': True}

    def profile_avatar_path():
        preferences = runtime.get('preferences')
        if preferences is None:
            raise HTTPException(503, 'Profile storage is unavailable')
        directory = Path(preferences.path).parent / 'profile'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        return directory / 'owner-avatar'

    @router.get('/profile/metadata')
    def profile_metadata(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        preferences = runtime.get('preferences')
        if preferences is None:
            raise HTTPException(503, 'Owner profile metadata is unavailable')
        account_id = str(preferences.get('owner_account_id', '') or '')
        if not account_id:
            raise HTTPException(503, 'Owner account identifier is unavailable')
        settings = runtime.get('settings')
        email = str(getattr(settings, 'owner_google_email', '') or '').strip()
        verified = bool(email and getattr(settings, 'google_signin_client_id', ''))
        avatar = profile_avatar_path()
        return {
            'display_name': str(preferences.get('preferred_name', '') or ''),
            'first_name': str(preferences.get('profile_first_name', '') or ''),
            'last_name': str(preferences.get('profile_last_name', '') or ''),
            'email': email if verified else '',
            'email_verified': verified,
            'account_created_at': preferences.get('owner_account_created_at'),
            'account_id_masked': '•••• ' + account_id[-4:],
            'avatar_available': any(avatar.parent.glob('owner-avatar.*')),
        }

    @router.put('/profile')
    def profile_update(body: ProfileUpdateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        preferences = runtime.get('preferences')
        if preferences is None:
            raise HTTPException(503, 'Owner profile storage is unavailable')
        preferences.update(profile_first_name=body.first_name, profile_last_name=body.last_name, preferred_name=body.display_name)
        audit('profile.updated', device_id=device_id)
        return {'saved': True, 'first_name': body.first_name, 'last_name': body.last_name, 'display_name': body.display_name}

    @router.post('/profile/account-id/copy')
    def profile_account_id_copy(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        preferences = runtime.get('preferences')
        account_id = str(preferences.get('owner_account_id', '') or '') if preferences else ''
        if not account_id:
            raise HTTPException(503, 'Owner account identifier is unavailable')
        audit('profile.account_id_copied', device_id=device_id)
        return {'account_id': account_id}

    @router.get('/profile/avatar')
    def profile_avatar(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'ai:chat')
        base = profile_avatar_path()
        path = next((base.parent / f'owner-avatar{suffix}' for suffix in ('.png', '.jpeg', '.webp') if (base.parent / f'owner-avatar{suffix}').is_file()), None)
        if path is None:
            raise HTTPException(404, 'No profile photo has been uploaded')
        media_type = {'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}.get(path.suffix.lstrip('.'), 'application/octet-stream')
        return Response(content=path.read_bytes(), media_type=media_type, headers={'Cache-Control': 'no-store, private'})

    @router.put('/profile/avatar')
    def profile_avatar_upload(body: ProfileAvatarBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        try:
            image = base64.b64decode(body.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, 'Profile image must be valid base64 data') from exc
        if len(image) > 2 * 1024 * 1024:
            raise HTTPException(413, 'Profile images must be 2 MB or smaller')
        signatures = {
            'image/png': image.startswith(b'\x89PNG\r\n\x1a\n'),
            'image/jpeg': image.startswith(b'\xff\xd8\xff'),
            'image/webp': len(image) >= 12 and image[:4] == b'RIFF' and image[8:12] == b'WEBP',
        }
        if not signatures.get(body.media_type, False):
            raise HTTPException(415, 'The selected file does not match a supported image type')
        try:
            from PIL import Image
            with Image.open(BytesIO(image)) as decoded:
                if decoded.format not in {'PNG', 'JPEG', 'WEBP'} or decoded.width < 1 or decoded.height < 1 or decoded.width * decoded.height > 16_000_000:
                    raise HTTPException(415, 'The selected image dimensions or format are not supported')
                decoded.verify()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(415, 'The selected file is not a valid supported image') from exc
        base = profile_avatar_path()
        extension = {'image/png': '.png', 'image/jpeg': '.jpeg', 'image/webp': '.webp'}[body.media_type]
        path = base.with_suffix(extension)
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_bytes(image)
        os.chmod(temp, 0o600)
        temp.replace(path)
        for old in base.parent.glob('owner-avatar.*'):
            if old != path and old.is_file():
                old.unlink(missing_ok=True)
        audit('profile.avatar_updated', device_id=device_id)
        return {'saved': True, 'avatar_available': True}

    @router.delete('/profile/avatar')
    def profile_avatar_delete(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        base = profile_avatar_path()
        for path in base.parent.glob('owner-avatar.*'):
            if path.is_file():
                path.unlink(missing_ok=True)
        audit('profile.avatar_removed', device_id=device_id)
        return {'saved': True, 'avatar_available': False}

    @router.get('/privacy/export')
    def privacy_export(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'ai:chat'):
            raise HTTPException(403, 'This device cannot export conversation history')
        if hasattr(registry, 'authorize') and not registry.authorize(device_id, 'knowledge:read'):
            raise HTTPException(403, 'This device cannot export Knowledge data')
        if not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot export sensitive memory')
        continuity = runtime.get('continuity')
        conversations = []
        if continuity:
            for conversation_id in continuity.all_thread_ids(include_closed=True):
                try:
                    conversations.append(continuity.export_thread(conversation_id))
                except KeyError:
                    continue
        export = {
            'format': 'vishnu-account-data-v1',
            'exported_at': time.time(),
            'preferences': ui_preferences(device_id),
            'memories': memory.export(include_sensitive=True),
            'knowledge': knowledge.export(access_classes=knowledge_access(device_id)),
            'conversations': conversations,
        }
        audit('privacy.exported', device_id=device_id, conversation_count=len(conversations))
        return export

    def can_read_sensitive_memory(device_id: str):
        return not hasattr(registry, 'authorize') or registry.authorize(device_id, 'memory:sensitive')

    def filter_memories(rows, device_id: str):
        if can_read_sensitive_memory(device_id):
            return rows
        return [row for row in rows if str(row.get('sensitivity', 'normal')) not in {'sensitive', 'secret'}]

    def filter_tree(rows, device_id: str):
        output = []
        for row in rows:
            children = filter_tree(row.get('children', []), device_id)
            if can_read_sensitive_memory(device_id) or str(row.get('sensitivity', 'normal')) not in {'sensitive', 'secret'}:
                output.append({**row, 'children': children})
            else:
                output.extend(children)
        return output

    @router.get('/memory')
    def memory_list(
        q: str = '',
        limit: int = 100,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        rows = memory.temporal_search(q=q.strip(), limit=min(limit, 100))
        return {'memories': filter_memories(rows, device_id)}

    @router.get('/memory/preferences')
    def memory_preferences_get(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        return memory.preferences()

    @router.patch('/memory/preferences')
    def memory_preferences_update(body: MemoryPreferencesBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        changes = body.model_dump(exclude_none=True)
        if not changes:
            raise HTTPException(422, 'Provide at least one memory preference')
        result = memory.update_preferences(**changes)
        audit('memory.preferences.updated', device_id=device_id, preferences=changes)
        return result

    @router.get('/memory/removed')
    def memory_removed(limit: int = 100, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        return {'memories': filter_memories(memory.recently_removed(limit), device_id)}

    @router.post('/memory/{memory_id}/restore')
    def memory_restore(memory_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        existing = memory.get(memory_id, include_removed=True)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Removed memory not found')
        if not memory.restore(memory_id):
            raise HTTPException(404, 'Removed memory not found')
        audit('memory.restored', device_id=device_id, memory_id=memory_id)
        return {'ok': True, 'memory': second_brain.memory_detail(memory_id)}

    @router.delete('/memory/{memory_id}/permanent')
    def memory_permanent_delete(memory_id: str, confirm: bool = False, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if not confirm:
            raise HTTPException(409, 'Permanent deletion requires confirm=true')
        existing = memory.get(memory_id, include_removed=True)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Memory not found')
        if not second_brain.delete(memory_id):
            raise HTTPException(404, 'Memory not found')
        audit('memory.permanently_deleted', device_id=device_id, memory_id=memory_id)
        return {'ok': True, 'memory_id': memory_id}

    @router.get('/memory/graph')
    def memory_graph(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        graph = second_brain.graph()
        nodes = filter_memories(graph.get('nodes', []), device_id)
        ids = {row['id'] for row in nodes}
        return {'nodes': nodes, 'edges': [edge for edge in graph.get('edges', []) if edge['source_id'] in ids and edge['target_id'] in ids]}

    @router.get('/memory/tree')
    def memory_tree(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        return {'roots': filter_tree(memory.tree(), device_id)}

    @router.get('/memory/export')
    def memory_export(
        include_sensitive: bool = True,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        if include_sensitive and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot export sensitive memory')
        audit('memory.exported', device_id=device_id, include_sensitive=include_sensitive)
        return memory.export(include_sensitive=include_sensitive)

    @router.post('/memory/retention')
    def memory_retention(
        body: RetentionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot create sensitive memory')
        result = second_brain.apply_retention(
            older_than_days=body.older_than_days,
            sensitivity=body.sensitivity,
            dry_run=not body.confirm_delete,
        )
        audit('memory.retention', device_id=device_id, matched=result['matched'], deleted=body.confirm_delete)
        return result

    @router.post('/memory')
    def memory_create(
        body: MemoryCreateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if body.sensitivity == 'never_store':
            raise HTTPException(409, 'NEVER_STORE content cannot be written to durable memory')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot create sensitive memory')
        if body.scope == 'project':
            project_store = runtime.get('project_store')
            if not body.project_id or project_store is None or not project_store.get(body.project_id):
                raise HTTPException(404, 'Authorized project not found')
        elif body.project_id:
            raise HTTPException(422, 'Personal memories cannot include a project ID')
        memory_id = second_brain.remember(MemoryCandidate(
            type=body.type,
            subject=body.subject,
            content=body.content,
            confidence=body.confidence,
            source=body.source,
            verified=body.verified,
            tags=body.tags,
            importance=body.importance,
            sensitivity=body.sensitivity,
            occurred_at=body.occurred_at,
            metadata={'scope': body.scope, **({'project_id': body.project_id} if body.project_id else {})},
        ))
        if body.parent_id:
            memory.update_memory(memory_id, parent_id=body.parent_id)
        audit('memory.created', device_id=device_id, memory_id=memory_id)
        return second_brain.memory_detail(memory_id)

    @router.get('/memory/{memory_id}')
    def memory_detail(memory_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'memory:read')
        detail = second_brain.memory_detail(memory_id)
        if not detail or not filter_memories([detail], device_id):
            raise HTTPException(404, 'Memory not found')
        return detail

    @router.patch('/memory/{memory_id}')
    def memory_update(
        memory_id: str,
        body: MemoryUpdateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        existing = memory.get(memory_id)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Memory not found')
        if body.sensitivity == 'never_store':
            raise HTTPException(409, 'Delete this memory instead of marking durable content NEVER_STORE')
        if body.sensitivity in {'sensitive', 'secret'} and not can_read_sensitive_memory(device_id):
            raise HTTPException(403, 'This device cannot mark memory sensitive')
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        if 'scope' in changes or 'project_id' in changes:
            metadata_raw = existing.get('metadata_json') or '{}'
            try:
                metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            scope = changes.pop('scope', metadata.get('scope') or ('project' if metadata.get('project_id') else 'personal'))
            project_id = changes.pop('project_id', metadata.get('project_id'))
            if scope == 'project':
                project_store = runtime.get('project_store')
                if not project_id or project_store is None or not project_store.get(project_id):
                    raise HTTPException(404, 'Authorized project not found')
                metadata.update({'scope': 'project', 'project_id': project_id})
            else:
                metadata.update({'scope': 'personal'})
                metadata.pop('project_id', None)
            changes['metadata'] = metadata
        if not memory.update_memory(memory_id, **changes):
            raise HTTPException(404, 'Memory not found or no supported changes supplied')
        audit('memory.corrected', device_id=device_id, memory_id=memory_id, fields=sorted(changes))
        return second_brain.memory_detail(memory_id)

    @router.delete('/memory/{memory_id}')
    def memory_delete(
        memory_id: str,
        confirm: bool = False,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'memory:write')
        if not confirm:
            raise HTTPException(409, 'Memory deletion requires confirm=true')
        existing = memory.get(memory_id)
        if not existing or not filter_memories([existing], device_id):
            raise HTTPException(404, 'Memory not found')
        if not memory.soft_delete(memory_id):
            raise HTTPException(404, 'Memory not found')
        audit('memory.removed', device_id=device_id, memory_id=memory_id)
        return {'ok': True, 'memory_id': memory_id}

    @router.get('/knowledge/collections')
    def knowledge_collections(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'knowledge:read')
        return {'collections': knowledge.collections()}

    @router.get('/knowledge/sources')
    def knowledge_sources(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        sources = knowledge.sources(limit=100)
        return {'sources': [{key: item.get(key) for key in ('id', 'source_type', 'display_name', 'status', 'sync_status', 'last_sync_at', 'last_error_code', 'project_id')} for item in sources]}

    @router.post('/knowledge/collections', status_code=201)
    def knowledge_collection_create(body: KnowledgeCollectionBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        try:
            item = knowledge.create_collection(body.title, body.description)
        except KnowledgeError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit('knowledge.collection.created', device_id=device_id, collection_id=item['id'])
        return item

    @router.patch('/knowledge/collections/{collection_id}')
    def knowledge_collection_update(collection_id: str, body: KnowledgeCollectionUpdateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        changes = body.model_dump(exclude_none=True)
        if not changes:
            raise HTTPException(422, 'Provide a collection name or description')
        try:
            item = knowledge.update_collection(collection_id, **changes)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except KnowledgeError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit('knowledge.collection.updated', device_id=device_id, collection_id=collection_id)
        return item

    @router.delete('/knowledge/collections/{collection_id}')
    def knowledge_collection_delete(collection_id: str, confirm: bool = False, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if not confirm:
            raise HTTPException(409, 'Deleting a collection requires confirm=true')
        if not knowledge.delete_collection(collection_id):
            raise HTTPException(404, 'Knowledge collection not found')
        audit('knowledge.collection.deleted', device_id=device_id, collection_id=collection_id)
        return {'ok': True, 'collection_id': collection_id, 'items_retained': True}

    @router.get('/knowledge')
    def knowledge_list(
        q: str = '',
        limit: int = 100,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        return {'documents': knowledge.list(q, limit=min(limit, 100), access_classes=knowledge_access(device_id))}

    @router.get('/knowledge/search')
    def knowledge_search(
        q: str,
        limit: int = 12,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        return {'results': knowledge.search(q, limit=min(limit, 50), access_classes=knowledge_access(device_id))}

    @router.get('/knowledge/export')
    def knowledge_export(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        audit('knowledge.exported', device_id=device_id)
        return knowledge.export(access_classes=knowledge_access(device_id))

    @router.post('/knowledge')
    def knowledge_upload(
        body: KnowledgeUploadBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if body.access_class == 'private' and 'private' not in knowledge_access(device_id):
            raise HTTPException(403, 'This device cannot create private knowledge')
        try:
            if body.collection_id and not knowledge.collection(body.collection_id):
                raise KnowledgeError('Knowledge collection not found')
            if body.item_kind == 'link':
                parsed = urlparse(str(body.link_url or '').strip())
                if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                    raise KnowledgeError('Enter a valid http or https link')
                body.filename = (body.filename or 'Saved link.txt')
                body.title = body.title or parsed.netloc
                data = f'Saved link (not fetched): {parsed.geturl()}'.encode('utf-8')
            elif body.content_base64 is not None:
                data = base64.b64decode(body.content_base64, validate=True)
            elif body.text is not None:
                data = body.text.encode('utf-8')
            else:
                raise KnowledgeError('File content is required')
            metadata = _bounded_mapping(body.metadata)
            metadata.update({
                'knowledge_kind': body.item_kind,
                'available_to_vishnu': body.item_kind != 'link',
                'link_url': urlparse(body.link_url).geturl() if body.item_kind == 'link' and body.link_url else None,
                'link_status': 'saved_only' if body.item_kind == 'link' else None,
                'collection_id': body.collection_id or None,
            })
            document = knowledge.ingest(
                filename=body.filename,
                data=data,
                title=body.title,
                media_type=body.media_type,
                source=body.source,
                access_class=body.access_class,
                metadata={key: value for key, value in metadata.items() if value is not None},
            )
        except (KnowledgeError, binascii.Error) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('knowledge.ingested', device_id=device_id, document_id=document['id'], checksum=document['checksum'])
        return document

    @router.get('/knowledge/{document_id}')
    def knowledge_detail(document_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:read')
        document = knowledge.detail(document_id)
        if not document or document['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        return document

    @router.patch('/knowledge/{document_id}')
    def knowledge_update(
        document_id: str,
        body: KnowledgeUpdateBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        if body.access_class == 'private' and 'private' not in knowledge_access(device_id):
            raise HTTPException(403, 'This device cannot mark knowledge private')
        try:
            changes = body.model_dump(exclude_none=True)
            collection_id = changes.pop('collection_id', None)
            if 'metadata' in changes:
                changes['metadata'] = _bounded_mapping(changes['metadata'])
            if collection_id is not None:
                if collection_id and not knowledge.collection(collection_id):
                    raise KnowledgeError('Knowledge collection not found')
                metadata = dict(existing.get('metadata') or {})
                if collection_id:
                    metadata['collection_id'] = collection_id
                else:
                    metadata.pop('collection_id', None)
                changes['metadata'] = metadata
            document = knowledge.update(document_id, **changes)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except KnowledgeError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('knowledge.updated', device_id=device_id, document_id=document_id)
        return document

    @router.patch('/knowledge/{document_id}/availability')
    def knowledge_availability(document_id: str, body: KnowledgeAvailabilityBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        metadata = dict(existing.get('metadata') or {})
        if body.available_to_vishnu and metadata.get('link_status') == 'saved_only':
            raise HTTPException(409, 'This saved link has not been fetched or indexed; it cannot be used by Vishnu yet')
        metadata['available_to_vishnu'] = body.available_to_vishnu
        result = knowledge.update(document_id, metadata=metadata)
        audit('knowledge.availability.updated', device_id=device_id, document_id=document_id, available_to_vishnu=body.available_to_vishnu)
        return result

    @router.delete('/knowledge/{document_id}')
    def knowledge_delete(
        document_id: str,
        confirm: bool = False,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'knowledge:write')
        if not confirm:
            raise HTTPException(409, 'Knowledge deletion requires confirm=true')
        existing = knowledge.detail(document_id)
        if not existing or existing['access_class'] not in knowledge_access(device_id):
            raise HTTPException(404, 'Knowledge document not found')
        if not knowledge.delete(document_id):
            raise HTTPException(404, 'Knowledge document not found')
        audit('knowledge.deleted', device_id=device_id, document_id=document_id)
        return {'ok': True, 'document_id': document_id}

    @router.get('/activities')
    def activities(
        category: str | None = None,
        limit: int = 200,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        authenticate(pa_device, pa_token, 'activities:read')
        bounded = max(1, min(limit, 500))
        rows = memory.audit_entries(category, bounded)
        project_store = runtime.get('project_store')
        if project_store is not None and (category is None or category in {'project', 'projects'}):
            for item in project_store.activity_feed(limit=bounded):
                payload = {
                    'project_id': item['project_id'],
                    'project_name': item['project_name'],
                    'target_type': item['target_type'],
                    'target_id': item.get('target_id'),
                }
                if item['target_type'] == 'task' and item.get('target_id'):
                    payload['task_id'] = item['target_id']
                rows.append({
                    'id': item['id'], 'category': 'project', 'action': item['action'],
                    'actor': item['actor'], 'created_at': item['created_at'],
                    'payload': payload, 'status': 'recorded',
                })
        rows.sort(key=lambda item: str(item.get('created_at') or ''), reverse=True)
        return {'activities': rows[:bounded]}

    @router.get('/devices')
    def devices(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'device:read')
        return {'current_device_id': device_id, 'devices': registry.list()}

    @router.patch('/devices/{target_device_id}/permissions')
    def device_permissions(
        target_device_id: str,
        body: DevicePermissionsBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        require_fresh_reauthentication()
        try:
            result = registry.set_permissions(target_device_id, body.scopes)
            cancelled_turns = cancelled_workflows = 0
            granted_scopes = set(result.get('scopes') or ())
            if 'ai:chat' not in granted_scopes:
                executor = runtime.get('executor')
                cancel_device_turns = getattr(executor, 'cancel_device_turns', None)
                if callable(cancel_device_turns):
                    cancelled_turns = int(cancel_device_turns(target_device_id, reason='device_permission_revoked'))
            if 'workflow:write' not in granted_scopes:
                automations = runtime.get('automations')
                cancel_device_runs = getattr(automations, 'cancel_device_runs', None)
                if callable(cancel_device_runs):
                    cancelled_workflows = int(cancel_device_runs(target_device_id, reason='workflow_permission_revoked'))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('device.permissions.updated', device_id=device_id, target_device_id=target_device_id, scopes=result['scopes'], cancelled_turns=cancelled_turns, cancelled_workflows=cancelled_workflows)
        return {**result, 'cancelled_turns': cancelled_turns, 'cancelled_workflows': cancelled_workflows}

    @router.post('/devices/{target_device_id}/revoke')
    def device_revoke(
        target_device_id: str,
        body: ConfirmBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        require_fresh_reauthentication()
        if not registry.revoke(target_device_id):
            raise HTTPException(404, 'Device not found')
        revoked_sessions = {}
        for key in ('pwa_sessions', 'cloud_sessions'):
            store = runtime.get(key)
            revoke_device = getattr(store, 'revoke_device', None)
            if callable(revoke_device):
                revoked_sessions[key] = int(revoke_device(target_device_id))
        gateway = runtime.get('device_gateway')
        if gateway is not None:
            gateway.disconnect(target_device_id)
        executor = runtime.get('executor')
        cancel_device_turns = getattr(executor, 'cancel_device_turns', None)
        cancelled_turns = int(cancel_device_turns(target_device_id, reason='device_revoked')) if callable(cancel_device_turns) else 0
        automations = runtime.get('automations')
        cancel_device_runs = getattr(automations, 'cancel_device_runs', None)
        cancelled_workflows = int(cancel_device_runs(target_device_id, reason='device_revoked')) if callable(cancel_device_runs) else 0
        audit(
            'device.revoked',
            device_id=device_id,
            target_device_id=target_device_id,
            revoked_sessions=revoked_sessions,
            cancelled_turns=cancelled_turns,
            cancelled_workflows=cancelled_workflows,
        )
        return {
            'ok': True,
            'revoked_device_id': target_device_id,
            'current_device_revoked': target_device_id == device_id,
            'revoked_sessions': revoked_sessions,
            'cancelled_turns': cancelled_turns,
            'cancelled_workflows': cancelled_workflows,
        }

    @router.delete('/privacy/account')
    def delete_owner_account(body: DeleteAccountBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'ai:chat')
        require_fresh_reauthentication()
        settings = runtime.get('settings')
        data_dir = getattr(settings, 'data_dir', None) if settings is not None else None
        if data_dir is None:
            raise HTTPException(503, 'This installation cannot delete owner data')
        try:
            tombstone = stage_owner_data_deletion(Path(data_dir))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, 'Owner data could not be safely deleted') from exc
        # Stop background writers after the atomic rename; any already-open DB
        # handles now point at detached files and the trusted-device database is
        # no longer reachable at its configured location.
        try:
            if runtime.get('notifications'):
                runtime['notifications'].close()
            if runtime.get('automations'):
                runtime['automations'].stop()
            if runtime.get('apns'):
                runtime['apns'].close()
        except Exception:
            pass
        return JSONResponse(
            {'deleted': True},
            background=BackgroundTask(shutil.rmtree, tombstone, ignore_errors=True),
            headers={'Cache-Control': 'no-store'},
        )

    @router.get('/workflows')
    def workflows(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:read')
        engine = runtime['automations']
        auth = workflow_authority(device_id)
        runs = [
            row for row in engine.runs(limit=100)
            if workflow_binding_matches(engine, row.get('id'), auth)
        ]
        return {'workflows': engine.workflows(), 'runs': runs}

    @router.post('/workflows')
    def workflow_create(body: WorkflowCreateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            trigger = _bounded_mapping(body.trigger)
            steps = [_bounded_mapping(step, max_bytes=32768) for step in body.steps]
            embedded_policy = trigger.pop('policy', None)
            workflow_id = runtime['automations'].create_workflow(
                body.title, trigger, steps,
                next_run_at=body.next_run_at, interval_seconds=body.interval_seconds,
                policy=_bounded_mapping(embedded_policy) if embedded_policy is not None else None,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('workflow.created', device_id=device_id, workflow_id=workflow_id)
        return runtime['automations'].workflow(workflow_id)

    @router.put('/workflows/{workflow_id}')
    def workflow_update(workflow_id: str, body: WorkflowCreateBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            trigger = _bounded_mapping(body.trigger)
            steps = [_bounded_mapping(step, max_bytes=32768) for step in body.steps]
            result = runtime['automations'].update_workflow(
                workflow_id, title=body.title, trigger=trigger, steps=steps,
                next_run_at=body.next_run_at, interval_seconds=body.interval_seconds,
            )
        except KeyError as exc:
            raise HTTPException(404, 'Workflow not found') from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('workflow.updated', device_id=device_id, workflow_id=workflow_id)
        return result

    @router.post('/workflows/pause')
    def workflow_pause(body: WorkflowPauseBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            result = runtime['automations'].pause_workflow(body.workflow_id, body.paused)
        except KeyError as exc:
            raise HTTPException(404, 'Workflow not found') from exc
        audit('workflow.paused' if body.paused else 'workflow.resumed', device_id=device_id, workflow_id=body.workflow_id)
        return result

    @router.post('/workflows/{workflow_id}/run')
    def workflow_run(workflow_id: str, body: WorkflowRunBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            context = _bounded_mapping(body.context)
            run_id = runtime['automations'].run_workflow(
                workflow_id,
                context=context,
                background=True,
                idempotency_key=body.idempotency_key,
                **workflow_authority(device_id),
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.started', device_id=device_id, workflow_id=workflow_id, run_id=run_id)
        return {'workflow_id': workflow_id, 'run_id': run_id, 'status': 'queued'}

    @router.post('/workflows/runs/{run_id}/cancel')
    def workflow_cancel(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            authority = workflow_authority(device_id)
            authority.pop('reauthenticated_at', None)
            result = runtime['automations'].cancel_run(run_id, **authority)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        audit('workflow.cancelled', device_id=device_id, run_id=run_id)
        return result

    @router.post('/workflows/runs/{run_id}/recovery/link')
    def workflow_recovery_link(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        try: result = runtime['automations'].link_recovery(run_id, **workflow_authority(device_id))
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc
        except (RuntimeError, PermissionError) as exc: raise HTTPException(409, str(exc)) from exc
        audit('workflow.recovery_linked', device_id=device_id, run_id=run_id, recovery_transaction_id=result['recovery_transaction_id'])
        return result

    @router.post('/workflows/runs/{run_id}/recovery/refresh')
    def workflow_recovery_refresh(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        try: return runtime['automations'].refresh_recovery(run_id, **workflow_authority(device_id))
        except KeyError as exc: raise HTTPException(404, 'Workflow run not found') from exc
        except (RuntimeError, PermissionError) as exc: raise HTTPException(409, str(exc)) from exc

    @router.post('/workflows/runs/{run_id}/resume')
    def workflow_resume(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:write')
        try:
            authority = workflow_authority(device_id)
            authority.pop('reauthenticated_at', None)
            result = runtime['automations'].resume_run(run_id, **authority)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.resumed', device_id=device_id, run_id=run_id)
        return result

    @router.post('/workflows/runs/{run_id}/approve')
    def workflow_approve(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        engine = runtime['automations']
        auth = workflow_authority(device_id)
        if not workflow_binding_matches(engine, run_id, auth):
            raise HTTPException(403, 'Workflow authority mismatch')
        try:
            run = engine._run(run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        approval_id = run.get('pending_approval_id')
        if not approval_id:
            raise HTTPException(409, 'Workflow is not waiting for approval')
        try:
            result = engine.approve_run(
                run_id,
                approval_id,
                **auth,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.approved', device_id=device_id, run_id=run_id, approval_id=approval_id)
        return result

    @router.post('/workflows/runs/{run_id}/reject')
    def workflow_reject(run_id: str, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'workflow:approve')
        engine = runtime['automations']
        authority = workflow_authority(device_id)
        if not workflow_binding_matches(engine, run_id, authority):
            raise HTTPException(403, 'Workflow authority mismatch')
        try:
            run = engine._run(run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        approval_id = run.get('pending_approval_id')
        if not approval_id:
            raise HTTPException(409, 'Workflow is not waiting for approval')
        try:
            authority.pop('reauthenticated_at', None)
            result = engine.reject_run(run_id, approval_id, **authority)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        audit('workflow.rejected', device_id=device_id, run_id=run_id, approval_id=approval_id)
        return result

    @router.post('/system/emergency-stop')
    def emergency_stop(body: EmergencyStopBody, pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        device_id = authenticate(pa_device, pa_token, 'device:admin')
        if not body.enabled:
            require_fresh_reauthentication()
        runtime['tools'].set_emergency_stop(body.enabled)
        # ToolRegistry is the canonical E-stop authority and advances the
        # security epoch. Also cancel active canonical turns so this owner
        # surface converges with the cloud owner E-stop semantics.
        executor = runtime.get('executor')
        if body.enabled and executor is not None and hasattr(executor, 'cancel_active_turns'):
            executor.cancel_active_turns(reason='emergency_stop')
        events = runtime.get('events')
        if events is not None:
            events.emit('emergency.stop', enabled=body.enabled)
        autonomy = runtime.get('advanced_autonomy')
        if autonomy is not None:
            autonomy.emergency_stop('owner requested from trusted device') if body.enabled else autonomy.clear_emergency_stop()
        audit('system.emergency_stop', device_id=device_id, enabled=body.enabled)
        return {'enabled': body.enabled, 'message': 'All tool actions stopped' if body.enabled else 'Tool actions enabled'}

    @router.get('/qualification')
    def qualification_status(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'qualification:read')
        return runtime['p3_qualification'].status()

    @router.post('/qualification/stages')
    def qualification_start(
        body: QualificationSessionBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        environment = {**_bounded_mapping(body.environment), 'device_id': device_id, 'surface': 'ios-pwa'}
        try:
            session_id = runtime['p3_qualification'].start_session(
                body.stage,
                evidence_class=body.evidence_class,
                environment=environment,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('qualification.session.started', device_id=device_id, session_id=session_id, stage=body.stage)
        return {'session_id': session_id, 'stage': body.stage, 'evidence_class': body.evidence_class}

    @router.post('/qualification/sessions/{session_id}/trials')
    def qualification_trial(
        session_id: str,
        body: QualificationTrialBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        evidence = {**_bounded_mapping(body.evidence), 'device_id': device_id}
        metrics = _bounded_mapping(body.metrics)
        try:
            trial = runtime['p3_qualification'].record_trial(
                session_id,
                body.task,
                passed=body.passed,
                latency_ms=body.latency_ms,
                metrics=metrics,
                evidence=evidence,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'trial': trial, 'session_id': session_id}

    @router.post('/qualification/sessions/{session_id}/finish')
    def qualification_finish(
        session_id: str,
        body: QualificationFinishBody,
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        try:
            result = runtime['p3_qualification'].finish_session(session_id, duration_seconds=body.duration_seconds)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit('qualification.session.finished', device_id=device_id, session_id=session_id)
        return result

    @router.get('/system/status')
    def system_status(pa_device: str | None = Cookie(default=None), pa_token: str | None = Cookie(default=None)):
        authenticate(pa_device, pa_token, 'activities:read')
        return {
            'model': runtime['models'].status(),
            'tools': [
                {'name': tool.name, 'description': tool.description, 'risk': tool.risk.name}
                for tool in runtime['tools'].all()
            ],
            'integrations': runtime['integrations'].list(),
            'future_intelligence': runtime['future_intelligence'].status(),
            'emergency_stop': bool(getattr(runtime['tools'], 'emergency_stop', False)),
            'model_evaluation': runtime['model_evaluation'].latest(),
        }

    @router.post('/system/model-evaluation')
    def run_model_evaluation(
        pa_device: str | None = Cookie(default=None),
        pa_token: str | None = Cookie(default=None),
    ):
        device_id = authenticate(pa_device, pa_token, 'qualification:record')
        result = runtime['model_evaluation'].run()
        audit('model.evaluation.requested', device_id=device_id, run_id=result['id'])
        return result

    return router
