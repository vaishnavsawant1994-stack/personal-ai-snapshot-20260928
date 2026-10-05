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
                                     owner='vishnu', milestone_id=milestone_id,
                                     context_notes='Review the shared project design brief.')
            task_id = project['tasks'][0]['id']
            project = store.update_task(project_id, task_id, {'status': 'in_progress'})
            project = store.add_thread(project_id, title='Scope question', content='Which device sizes are in scope?')
            thread_id = project['threads'][0]['id']
            project = store.add_reply(project_id, thread_id, author='owner', content='Phone and desktop.')
            project = store.add_upload(project_id, title='brief.md', media_type='text/markdown', content=b'Project brief')

            reopened = ProjectStore(path).get(project_id)
            self.assertEqual(reopened['tasks'][0]['owner'], 'vishnu')
            self.assertEqual(reopened['tasks'][0]['context_notes'], 'Review the shared project design brief.')
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

    def test_milestone_task_links_stay_consistent_when_moved_or_cleared(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            project = store.create(name='Milestone links')
            project_id = project['id']
            project = store.add_milestone(project_id, title='First', target_date='2026-11-01')
            first_id = project['milestones'][0]['id']
            project = store.add_milestone(project_id, title='Second', target_date='2026-11-02')
            second_id = project['milestones'][1]['id']
            project = store.add_task(project_id, title='One task', milestone_id=first_id)
            task_id = project['tasks'][0]['id']
            project = store.update_milestone(project_id, second_id, {'task_ids': [task_id]})
            by_id = {item['id']: item for item in project['milestones']}
            self.assertEqual(by_id[first_id]['task_ids'], [])
            self.assertEqual(by_id[second_id]['task_ids'], [task_id])
            project = store.update_task(project_id, task_id, {'milestone_id': None})
            self.assertEqual({item['id']: item['task_ids'] for item in project['milestones']},
                             {first_id: [], second_id: []})

    def test_task_file_links_are_project_scoped_editable_and_persistent(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            first = store.create(name='First')
            second = store.create(name='Second')
            file_id = store.add_upload(first['id'], title='task-notes.md', media_type='text/markdown', content=b'Notes')['files'][0]['id']
            task = store.add_task(first['id'], title='Use notes', file_ids=[file_id])['tasks'][0]
            self.assertEqual(task['file_ids'], [file_id])
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                store.add_task(second['id'], title='Invalid link', file_ids=[file_id])
            task = store.update_task(first['id'], task['id'], {'file_ids': []})['tasks'][0]
            self.assertEqual(task['file_ids'], [])
            task = store.update_task(first['id'], task['id'], {'file_ids': [file_id]})['tasks'][0]
            self.assertEqual(ProjectStore(Path(folder) / 'projects.sqlite3').get(first['id'])['tasks'][0]['file_ids'], [file_id])

    def test_project_proposal_decisions_comments_and_resubmission_are_audited(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.sqlite3'
            store = ProjectStore(path)
            project = store.create(name='Approval scope')
            task = store.add_task(project['id'], title='Implement option')['tasks'][0]
            file_id = store.add_upload(project['id'], title='proposal.md', media_type='text/markdown', content=b'Proposal')['files'][0]['id']
            project = store.add_approval(project['id'], title='Enable option', summary='Enable a scoped option',
                                         impact_summary='Changes one setting', scope_summary='This project only',
                                         task_ids=[task['id']], file_ids=[file_id])
            approval = project['approvals'][0]
            self.assertEqual(approval['task_ids'], [task['id']])
            self.assertEqual(approval['file_ids'], [file_id])
            with self.assertRaisesRegex(ValueError, 'comments'):
                store.decide_approval(project['id'], approval['id'], decision='changes_requested')
            project = store.decide_approval(project['id'], approval['id'], decision='changes_requested', comments='Clarify rollback plan.')
            self.assertEqual(project['approvals'][0]['reviewer_comments'], 'Clarify rollback plan.')
            project = store.revise_approval(project['id'], approval['id'], title='Enable option v2', summary='Revised scope',
                                            impact_summary='Changes one setting', scope_summary='This project only',
                                            task_ids=[task['id']], file_ids=[file_id])
            self.assertEqual(project['approvals'][0]['status'], 'pending')
            self.assertEqual([row['decision'] for row in project['approvals'][0]['history']], ['changes_requested', 'resubmitted'])
            project = store.decide_approval(project['id'], approval['id'], decision='approved', comments='Reviewed.')
            self.assertEqual(project['approvals'][0]['status'], 'approved')
            self.assertEqual(project['approvals'][0]['reviewer'], 'owner')
            self.assertEqual(ProjectStore(path).get(project['id'])['approvals'][0]['decision'], 'approved')
            with self.assertRaisesRegex(ValueError, 'already been reviewed'):
                store.decide_approval(project['id'], approval['id'], decision='approved')


if __name__ == '__main__':
    unittest.main()
