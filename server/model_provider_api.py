from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


class ProviderCredentialBody(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=16, max_length=4096)
    model: str | None = Field(default=None, max_length=200)


class ProviderModelBody(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class WorkProposalBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=16000)
    sensitivity: str = Field(default='internal', max_length=40)
    context: str = Field(default='', max_length=16000)
    execution_id: str | None = Field(default=None, max_length=200)
    attempt_id: str | None = Field(default=None, max_length=200)


def model_provider_router(runtime) -> APIRouter:
    router = APIRouter(prefix='/owner/ai', tags=['owner-ai'])

    def local_only(request: Request):
        host = request.client.host if request.client else ''
        if host not in {'127.0.0.1', '::1'}:
            raise HTTPException(403, 'Local owner operation')

    def models():
        value = runtime.get('models') if runtime else None
        if value is None:
            raise HTTPException(503, 'model router unavailable')
        return value

    @router.get('/status')
    def status(request: Request):
        local_only(request)
        return models().status()

    @router.get('/providers')
    def providers(request: Request):
        local_only(request)
        service = models()
        return {
            'providers': [provider.public() for provider in service.providers.values()],
            'default_provider': service.primary,
            'fallback_providers': list(service.fallbacks),
            'privacy_mode': getattr(service, 'owner_privacy', None),
            'policies': [policy.policy_id for policy in getattr(service, 'policies', ()).all()] if hasattr(service, 'policies') else [],
        }

    @router.post('/providers/test')
    def test_provider(body: ProviderCredentialBody, request: Request):
        local_only(request)
        try:
            return models().test_owner_provider(body.provider_id, body.api_key)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/providers/connect')
    def connect_provider(body: ProviderCredentialBody, request: Request):
        local_only(request)
        if not body.model:
            raise HTTPException(422, 'model is required when connecting a provider')
        try:
            return models().connect_owner_provider(body.provider_id, body.api_key, body.model)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/providers/{provider_id}/models')
    def provider_models(provider_id: str, request: Request):
        local_only(request)
        try:
            return models().owner_provider_models(provider_id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch('/providers/{provider_id}/model')
    def provider_model(provider_id: str, body: ProviderModelBody, request: Request):
        local_only(request)
        try:
            return models().set_owner_provider_model(provider_id, body.model)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/providers/{provider_id}/default')
    def provider_default(provider_id: str, request: Request):
        local_only(request)
        try:
            return models().set_default_provider(provider_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete('/providers/{provider_id}')
    def disconnect_provider(provider_id: str, request: Request):
        local_only(request)
        try:
            return models().disconnect_owner_provider(provider_id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/work/{work_order_id}/intelligence')
    def work_intelligence(work_order_id: str, request: Request):
        local_only(request)
        service = runtime.get('worker_intelligence') if runtime else None
        if service is None:
            raise HTTPException(503, 'worker intelligence unavailable')
        assignment = service.store.get_intelligence_assignment(work_order_id)
        if assignment is None:
            try:
                assignment = service.ensure_assignment(work_order_id)
            except KeyError as exc:
                raise HTTPException(404, 'work order not found') from exc
        return {
            'assignment': assignment,
            'handoffs': service.store.list_model_handoffs(work_order_id),
        }

    @router.post('/work/{work_order_id}/propose')
    def work_propose(work_order_id: str, body: WorkProposalBody, request: Request):
        local_only(request)
        service = runtime.get('worker_intelligence') if runtime else None
        if service is None:
            raise HTTPException(503, 'worker intelligence unavailable')
        try:
            response = service.invoke(
                work_order_id,
                body.prompt,
                execution_id=body.execution_id,
                attempt_id=body.attempt_id,
                sensitivity=body.sensitivity,
                context=body.context,
            )
        except KeyError as exc:
            raise HTTPException(404, 'work order not found') from exc
        return {
            'request_id': response.request_id,
            'provider': response.provider_id,
            'model': response.model_id,
            'content': response.content,
            'usage': response.usage.__dict__,
            'model_output_authority': False,
        }

    return router
