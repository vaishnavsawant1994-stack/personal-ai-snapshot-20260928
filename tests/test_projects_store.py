from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projects.store import ProjectStore


class ProjectStoreTests(unittest.TestCase):
    def test_project_plan_discussion_and_file_data_persist(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.sqlite3'
            store = ProjectStore(path)
            project = store.create(name='Workspace redesign', goal='Ship a responsive project space')
            project_id = project['id']
            project = store.add_milestone(project_id, title='Design approved', target_date='2026-11-01')
            milestone_id = project['milestones'][0]['id']
            project = store.add_task(project_id, title='Build the project list', priority='high',
                                     owner='vishnu', milestone_id=milestone_id)
            task_id = project['tasks'][0]['id']
            project = store.update_task(project_id, task_id, {'status': 'in_progress'})
            project = store.add_thread(project_id, title='Scope question', content='Which device sizes are in scope?')
            thread_id = project['threads'][0]['id']
            project = store.add_reply(project_id, thread_id, author='owner', content='Phone and desktop.')
            project = store.add_upload(project_id, title='brief.md', media_type='text/markdown', content=b'Project brief')

            reopened = ProjectStore(path).get(project_id)
            self.assertEqual(reopened['tasks'][0]['owner'], 'vishnu')
            self.assertEqual(reopened['tasks'][0]['status'], 'in_progress')
            self.assertEqual(reopened['milestones'][0]['title'], 'Design approved')
            self.assertEqual([reply['content'] for reply in reopened['threads'][0]['replies']],
                             ['Which device sizes are in scope?', 'Phone and desktop.'])
            file_id = next(item['id'] for item in reopened['files'] if item['title'] == 'brief.md')
            self.assertEqual(store.file_blob(project_id, file_id)['content'], b'Project brief')
            self.assertGreaterEqual(len(reopened['activity']), 5)

    def test_relations_are_scoped_and_archive_hides_project(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            first = store.create(name='First')
            second = store.create(name='Second')
            milestone = store.add_milestone(first['id'], title='First milestone')['milestones'][0]
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                store.add_task(second['id'], title='Invalid relation', milestone_id=milestone['id'])
            self.assertTrue(store.archive(first['id']))
            self.assertIsNone(store.get(first['id']))
            self.assertEqual([item['name'] for item in store.list()], ['Second'])


if __name__ == '__main__':
    unittest.main()
