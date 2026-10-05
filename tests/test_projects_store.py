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

    def test_discussion_links_follow_pins_and_resolution_are_persisted_and_scoped(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.sqlite3'
            store = ProjectStore(path)
            project = store.create(name='Discussion workspace')
            other = store.create(name='Other workspace')
            task = store.add_task(project['id'], title='Review mobile layout')['tasks'][0]
            thread = store.add_thread(project['id'], title='Mobile layout', content='Check keyboard spacing.',
                                      linked_item_type='task', linked_item_id=task['id'])['threads'][0]
            reply_id = thread['replies'][0]['id']
            saved = store.update_thread(project['id'], thread['id'], {'followed': True, 'pinned_reply_id': reply_id})
            saved_thread = saved['threads'][0]
            self.assertTrue(saved_thread['followed'])
            self.assertEqual(saved_thread['pinned_reply']['content'], 'Check keyboard spacing.')
            self.assertEqual(saved_thread['linked_item_title'], 'Review mobile layout')
            resolved = store.update_thread(project['id'], thread['id'], {'status': 'resolved'})['threads'][0]
            self.assertEqual(resolved['status'], 'resolved')
            self.assertTrue(resolved['resolved_at'])
            self.assertIsNone(store.update_thread(other['id'], thread['id'], {'status': 'open'}))
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                store.add_thread(other['id'], title='Cross project', content='No.', linked_item_type='task', linked_item_id=task['id'])
            reopened = ProjectStore(path).get(project['id'])['threads'][0]
            self.assertEqual(reopened['status'], 'resolved')

    def test_files_can_be_pinned_only_within_their_project(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            first = store.create(name='First')
            second = store.create(name='Second')
            file_id = store.add_upload(first['id'], title='brief.md', media_type='text/markdown', content=b'Brief')['files'][0]['id']
            self.assertTrue(store.update_file(first['id'], file_id, {'is_pinned': True})['files'][0]['is_pinned'])
            self.assertIsNone(store.update_file(second['id'], file_id, {'is_pinned': False}))

    def test_walkthrough_is_explicit_persisted_and_idempotent(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'projects.sqlite3'
            store = ProjectStore(path)
            project = store.create_walkthrough()
            self.assertEqual(project['is_walkthrough'], 1)
            self.assertIn('illustrative', project['description'].lower())
            self.assertTrue(project['tasks'])
            self.assertTrue(project['milestones'])
            self.assertTrue(project['files'])
            self.assertTrue(project['threads'])
            self.assertEqual(store.create_walkthrough()['id'], project['id'])
            self.assertEqual(ProjectStore(path).get(project['id'])['is_walkthrough'], 1)


    def test_supported_uploads_are_indexed_and_search_is_project_scoped(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            first = store.create(name='Project one')
            second = store.create(name='Project two')
            file_id = store.add_upload(first['id'], title='brief.md', media_type='text/markdown',
                                       content=b'Private project launch schedule and milestones.')['files'][0]['id']
            self.assertEqual(store.get(first['id'])['files'][0]['indexing_state'], 'indexed')
            self.assertEqual([row['id'] for row in store.search_files(first['id'], 'launch schedule')], [file_id])
            self.assertEqual(store.search_files(second['id'], 'launch schedule'), [])
            self.assertEqual(store.search_files(first['id'], 'different phrase'), [])

    def test_deliverables_keep_immutable_versions_and_project_scoping(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            project = store.create(name='Deliverable project')
            other = store.create(name='Other project')
            project = store.save_deliverable(project['id'], title='Plan.md', content='# Draft one')
            deliverable = next(row for row in project['files'] if row['kind'] == 'deliverable')
            file_id = deliverable['id']
            self.assertEqual(deliverable['current_version'], 1)
            project = store.save_deliverable(project['id'], title='Plan.md', content='# Draft two', file_id=file_id)
            self.assertEqual(next(row for row in project['files'] if row['id'] == file_id)['version_count'], 2)
            self.assertEqual([row['version'] for row in store.file_versions(project['id'], file_id)], [2, 1])
            self.assertEqual(store.file_version_blob(project['id'], file_id, 1)['content'], b'# Draft one')
            self.assertIsNone(store.file_versions(other['id'], file_id))
            self.assertIsNone(store.file_version_blob(other['id'], file_id, 1))

    def test_drive_import_is_a_private_versioned_snapshot(self):
        with TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / 'projects.sqlite3')
            project = store.create(name='Drive import')
            project = store.add_drive_source(project['id'], title='reference.txt', media_type='text/plain',
                                             content=b'First imported revision', provider_file_id='drive-file-1', modified_at='v1')
            source = next(row for row in project['files'] if row['source_provider'] == 'google_drive')
            file_id = source['id']
            self.assertEqual(source['indexing_state'], 'indexed')
            project = store.add_drive_source(project['id'], title='reference.txt', media_type='text/plain',
                                             content=b'Updated imported revision', provider_file_id='drive-file-1', modified_at='v2')
            refreshed = next(row for row in project['files'] if row['id'] == file_id)
            self.assertEqual(refreshed['version_count'], 2)
            self.assertEqual(refreshed['source_modified_at'], 'v2')
            self.assertEqual(store.file_blob(project['id'], file_id)['content'], b'Updated imported revision')
            self.assertEqual([row['version'] for row in store.file_versions(project['id'], file_id)], [2, 1])


if __name__ == '__main__':
    unittest.main()
