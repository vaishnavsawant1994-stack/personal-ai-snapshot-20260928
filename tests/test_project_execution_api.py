import json
from pathlib import Path

from projects.store import ProjectStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.projects_api import projects_router


class Registry:
    def authenticate(self, device, token):
        return device == 'device-1' and token == 'token-1'

    def authorize(self, device, scope):
        return device == 'device-1'


class WorkflowRuntime:
    def __init__(self):
        self.steps = []
        self.run = None

    def create_workflow(self, title, trigger, steps):
        self.steps = steps
        return 'workflow-1'

    def run_workflow(self, workflow_id, **kwargs):
        self.run = {'workflow_id': workflow_id, **kwargs}
        return 'run-1'

    def run_binding(self, run_id):
        return {'owner_id': 'owner', 'device_id': 'device-1', 'session_id': 'session-1'}

    def runs(self, workflow_id, limit):
        return [{'id': 'run-1', 'status': 'completed', 'current_step': 1,
                 'result_json': json.dumps({'completed_steps': [{'result': {'reply': 'Reviewed the attached brief.'}}]}),
                 'started_at': '2026-10-06T00:00:00+00:00', 'updated_at': '2026-10-06T00:01:00+00:00'}]


def endpoint(router, path, method):
    return next(route.endpoint for route in router.routes if route.path == path and method in route.methods)


def test_task_run_starts_durable_work_and_returns_saved_review_result(tmp_path: Path):
    store = ProjectStore(tmp_path / 'projects.sqlite3')
    project = store.create(name='Runtime scope', goal='Use only project sources')
    brief = store.add_upload(project['id'], title='brief.md', media_type='text/markdown',
                             content=b'Only this project may use this confidential brief.')['files'][0]
    task = store.add_task(project['id'], title='Review project brief', owner='vishnu', file_ids=[brief['id']])['tasks'][0]
    workflow = WorkflowRuntime()
    router = projects_router({'device_registry': Registry(), 'continuity': None,
                              'automations': workflow, 'executor': object()}, store)
    token = set_trusted_request(TrustedRequestContext('device-1', 'session-1'))
    try:
        started = endpoint(router, '/iphone/api/projects/{project_id}/tasks/{task_id}/execution', 'POST')(
            project['id'], task['id'], 'device-1', 'token-1')
        assert started['status'] == 'queued'
        assert started['run_id'] == 'run-1'
        assert workflow.run['background'] is True
        assert workflow.run['session_id'] == 'session-1'
        prompt = workflow.steps[0]['prompt']
        assert 'Only this project may use this confidential brief.' in prompt
        assert store.get(project['id'])['tasks'][0]['status'] == 'in_progress'
        status = endpoint(router, '/iphone/api/projects/{project_id}/tasks/{task_id}/execution', 'GET')(
            project['id'], task['id'], 'device-1', 'token-1')
        assert status['status'] == 'completed'
        assert status['task']['status'] == 'needs_review'
        assert status['result'] == 'Reviewed the attached brief.'
    finally:
        reset_trusted_request(token)


def test_task_run_cannot_read_another_project_task(tmp_path: Path):
    store = ProjectStore(tmp_path / 'projects.sqlite3')
    first = store.create(name='First')
    second = store.create(name='Second')
    task = store.add_task(second['id'], title='Foreign task', owner='vishnu')['tasks'][0]
    router = projects_router({'device_registry': Registry(), 'continuity': None,
                              'automations': WorkflowRuntime(), 'executor': object()}, store)
    token = set_trusted_request(TrustedRequestContext('device-1', 'session-1'))
    try:
        try:
            endpoint(router, '/iphone/api/projects/{project_id}/tasks/{task_id}/execution', 'POST')(
                first['id'], task['id'], 'device-1', 'token-1')
        except Exception as exc:
            assert getattr(exc, 'status_code', None) == 404
        else:
            raise AssertionError('cross-project task execution should be denied')
    finally:
        reset_trusted_request(token)
