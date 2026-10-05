from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.store import ProjectStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.projects_api import projects_router


class FakeRegistry:
    def authenticate(self, device_id, token):
        return device_id == 'device-1' and token == 'test-token'

    def authorize(self, device_id, scope):
        return device_id == 'device-1' and scope == 'ai:chat'


class OwnerContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        cookies = {}
        for part in headers.get(b'cookie', b'').decode().split(';'):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                cookies[key] = value
        token = None
        if cookies.get('pa_device') == 'device-1':
            token = set_trusted_request(TrustedRequestContext('device-1', 'session-1'))
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                reset_trusted_request(token)


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / 'projects.sqlite3')
        self.runtime = {'device_registry': FakeRegistry(), 'continuity': None}
        app = FastAPI()
        app.add_middleware(OwnerContextMiddleware)
        app.include_router(projects_router(self.runtime, self.store))
        self.client = TestClient(app)
        self.client.cookies.set('pa_device', 'device-1')
        self.client.cookies.set('pa_token', 'test-token')

    def test_owner_auth_project_crud_and_scoped_task_validation(self):
        anonymous = TestClient(self.client.app)
        self.assertEqual(anonymous.get('/iphone/api/projects').status_code, 401)
        created = self.client.post('/iphone/api/projects', json={
            'name': 'Workspace build', 'goal': 'Build project workspaces'
        })
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()['project']
        project_id = project['id']
        milestone_response = self.client.post(f'/iphone/api/projects/{project_id}/milestones', json={
            'title': 'Core flow', 'outcome': 'Plan and execute project work',
            'target_date': '2026-11-01', 'completion_criteria': 'The owner has reviewed the core flow.'
        })
        self.assertEqual(milestone_response.status_code, 201, milestone_response.text)
        milestone_id = milestone_response.json()['project']['milestones'][0]['id']
        task_response = self.client.post(f'/iphone/api/projects/{project_id}/tasks', json={
            'title': 'Create workspace', 'owner': 'vishnu', 'milestone_id': milestone_id
        })
        self.assertEqual(task_response.status_code, 201, task_response.text)
        task = task_response.json()['project']['tasks'][0]
        self.assertEqual(task['owner'], 'vishnu')
        changed = self.client.patch(f'/iphone/api/projects/{project_id}/tasks/{task["id"]}',
                                    json={'status': 'in_progress'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['project']['tasks'][0]['status'], 'in_progress')
        self.assertEqual(self.client.get(f'/iphone/api/projects/{project_id}').json()['project']['goal'],
                         'Build project workspaces')

    def test_project_wizard_saves_metadata_plan_and_searchable_archive(self):
        created = self.client.post('/iphone/api/projects', json={
            'name': 'Responsive Projects', 'goal': 'Organize work', 'project_type': 'software',
            'success_criteria': 'The owner can review each step.', 'instructions': 'Ask before external actions.',
            'context_notes': 'Keep this scoped.',
            'milestones': [{'client_id': 'phase-1', 'title': 'Design', 'outcome': 'Review the design',
                            'completion_criteria': 'Design reviewed', 'target_date': '2026-11-01'}],
            'tasks': [{'client_id': 'task-1', 'title': 'Build list', 'description': 'Implement saved cards',
                       'owner': 'owner', 'priority': 'high', 'milestone_client_id': 'phase-1'}],
        })
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()['project']
        self.assertEqual(project['success_criteria'], 'The owner can review each step.')
        self.assertEqual(project['tasks'][0]['status'], 'planned')
        self.assertEqual(project['tasks'][0]['milestone_id'], project['milestones'][0]['id'])
        self.assertEqual(project['milestones'][0]['task_ids'], [project['tasks'][0]['id']])
        project_id = project['id']
        self.assertEqual(self.client.get('/iphone/api/projects?q=responsive').json()['projects'][0]['id'], project_id)
        self.client.delete(f'/iphone/api/projects/{project_id}')
        self.assertEqual(self.client.get('/iphone/api/projects').json()['projects'], [])
        archived = self.client.get('/iphone/api/projects?status=archived').json()['projects']
        self.assertEqual(archived[0]['id'], project_id)
        restored = self.client.post(f'/iphone/api/projects/{project_id}/restore', json={})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['project']['status'], 'active')

    def test_milestone_link_rejects_task_from_another_project(self):
        first = self.store.create(name='First')
        second = self.store.create(name='Second')
        task = self.store.add_task(second['id'], title='Private task')['tasks'][0]
        response = self.client.post(f"/iphone/api/projects/{first['id']}/milestones", json={
            'title': 'Phase', 'outcome': 'An outcome', 'target_date': '2026-11-01',
            'completion_criteria': 'Approved', 'task_ids': [task['id']],
        })
        self.assertEqual(response.status_code, 422)

    def test_project_file_upload_is_owner_authenticated_and_project_scoped(self):
        project_id = self.store.create(name='Files test')['id']
        response = self.client.post(f'/iphone/api/projects/{project_id}/files/upload', json={
            'filename': 'notes.md', 'media_type': 'text/markdown', 'content_base64': 'UHJvamVjdCBub3Rlcw=='
        })
        self.assertEqual(response.status_code, 201, response.text)
        file_id = response.json()['project']['files'][0]['id']
        download = self.client.get(f'/iphone/api/projects/{project_id}/files/{file_id}/download')
        self.assertEqual(download.content, b'Project notes')
        self.assertEqual(download.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(f'/iphone/api/projects/not-this-project/files/{file_id}/download').status_code, 404)

    def test_task_file_links_and_project_approval_comments_use_owner_scoped_routes(self):
        project = self.store.create(name='Scoped approval')
        project_id = project['id']
        other_id = self.store.create(name='Other project')['id']
        uploaded = self.client.post(f'/iphone/api/projects/{project_id}/files/upload', json={
            'filename': 'scope.md', 'media_type': 'text/markdown', 'content_base64': 'c2NvcGU='
        })
        file_id = uploaded.json()['project']['files'][0]['id']
        task = self.client.post(f'/iphone/api/projects/{project_id}/tasks', json={
            'title': 'Review scope', 'file_ids': [file_id]
        }).json()['project']['tasks'][0]
        self.assertEqual(task['file_ids'], [file_id])
        wrong_scope = self.client.post(f'/iphone/api/projects/{other_id}/tasks', json={
            'title': 'Cannot link foreign source', 'file_ids': [file_id]
        })
        self.assertEqual(wrong_scope.status_code, 422)
        response = self.client.post(f'/iphone/api/projects/{project_id}/approvals', json={
            'title': 'Review exact change', 'summary': 'A bounded proposal',
            'impact_summary': 'One project setting', 'scope_summary': 'This project only',
            'task_ids': [task['id']], 'file_ids': [file_id]
        })
        self.assertEqual(response.status_code, 201, response.text)
        approval = response.json()['project']['approvals'][0]
        missing_comments = self.client.post(f"/iphone/api/projects/{project_id}/approvals/{approval['id']}/decision", json={
            'decision': 'changes_requested'
        })
        self.assertEqual(missing_comments.status_code, 422)
        decision = self.client.post(f"/iphone/api/projects/{project_id}/approvals/{approval['id']}/decision", json={
            'decision': 'changes_requested', 'comments': 'Clarify the impact.'
        })
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertFalse(decision.json()['execution_started'])
        self.assertEqual(decision.json()['project']['approvals'][0]['reviewer_comments'], 'Clarify the impact.')


if __name__ == '__main__':
    unittest.main()
