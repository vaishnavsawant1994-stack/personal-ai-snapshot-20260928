from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStore:
    """Small SQLite repository for the single-owner project workspace."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self._init()

    def con(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def _init(self):
        with self.con() as con:
            con.executescript('''
              CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
                target_date TEXT, conversation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_tasks(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'planned',
                priority TEXT NOT NULL DEFAULT 'medium', owner TEXT NOT NULL DEFAULT 'owner', due_date TEXT,
                milestone_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_milestones(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'planned',
                target_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_threads(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_replies(
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES project_threads(id) ON DELETE CASCADE,
                author TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_files(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'link', url TEXT NOT NULL,
                knowledge_id TEXT, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_file_blobs(
                file_id TEXT PRIMARY KEY REFERENCES project_files(id) ON DELETE CASCADE,
                media_type TEXT NOT NULL, content BLOB NOT NULL, size_bytes INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS project_activity(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT,
                detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_task_files(
                task_id TEXT NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
                file_id TEXT NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                PRIMARY KEY(task_id,file_id));
              CREATE TABLE IF NOT EXISTS project_approvals(
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL, summary TEXT NOT NULL, impact_summary TEXT NOT NULL DEFAULT '',
                scope_summary TEXT NOT NULL DEFAULT '', proposed_by TEXT NOT NULL DEFAULT 'owner',
                proposed_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                reviewer TEXT, reviewed_at TEXT, decision TEXT, reviewer_comments TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS project_approval_tasks(
                approval_id TEXT NOT NULL REFERENCES project_approvals(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
                PRIMARY KEY(approval_id,task_id));
              CREATE TABLE IF NOT EXISTS project_approval_files(
                approval_id TEXT NOT NULL REFERENCES project_approvals(id) ON DELETE CASCADE,
                file_id TEXT NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
                PRIMARY KEY(approval_id,file_id));
              CREATE TABLE IF NOT EXISTS project_approval_history(
                id TEXT PRIMARY KEY, approval_id TEXT NOT NULL REFERENCES project_approvals(id) ON DELETE CASCADE,
                actor TEXT NOT NULL, decision TEXT NOT NULL, comments TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
              CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, created_at);
              CREATE INDEX IF NOT EXISTS idx_project_activity_project ON project_activity(project_id, created_at DESC);
            ''')
            # Additive migrations keep existing owner workspaces intact.
            additions = {
                'projects': {
                    'project_type': "TEXT NOT NULL DEFAULT 'software'",
                    'success_criteria': "TEXT NOT NULL DEFAULT ''",
                    'instructions': "TEXT NOT NULL DEFAULT ''",
                    'context_notes': "TEXT NOT NULL DEFAULT ''",
                },
                'project_milestones': {
                    'completion_criteria': "TEXT NOT NULL DEFAULT ''",
                },
                'project_tasks': {
                    'context_notes': "TEXT NOT NULL DEFAULT ''",
                },
            }
            for table, columns in additions.items():
                present = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
                for name, declaration in columns.items():
                    if name not in present:
                        con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
            con.execute('''CREATE TABLE IF NOT EXISTS project_milestone_tasks(
                milestone_id TEXT NOT NULL REFERENCES project_milestones(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                PRIMARY KEY(milestone_id, task_id))''')
            con.execute('''INSERT OR IGNORE INTO project_milestone_tasks(milestone_id,task_id,project_id)
                SELECT milestone_id,id,project_id FROM project_tasks WHERE milestone_id IS NOT NULL''')

    @staticmethod
    def _dict(row):
        return dict(row) if row else None

    def _activity(self, con, project_id, action, target_type, target_id=None, detail='', actor='owner'):
        con.execute('INSERT INTO project_activity VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()), project_id, actor, action, target_type, target_id, detail[:1000], _now()))
        con.execute('UPDATE projects SET updated_at=? WHERE id=?', (_now(), project_id))

    def list(self, query='', status='all', sort='recent'):
        query = f'%{query.strip()}%'
        clauses = ['(p.name LIKE ? OR p.goal LIKE ? OR p.description LIKE ?)']
        values = [query, query, query]
        if status == 'all':
            clauses.append("p.status!='archived'")
        elif status != 'all':
            if status == 'needs_review':
                clauses.append("EXISTS (SELECT 1 FROM project_tasks r WHERE r.project_id=p.id AND r.status='needs_review')")
            elif status == 'completed':
                clauses.append("(p.status='completed' OR (EXISTS (SELECT 1 FROM project_tasks c WHERE c.project_id=p.id) AND NOT EXISTS (SELECT 1 FROM project_tasks c WHERE c.project_id=p.id AND c.status!='done')))")
            else:
                clauses.append('p.status=?')
                values.append(status)
        order = 'p.updated_at DESC' if sort == 'recent' else 'p.name COLLATE NOCASE ASC' if sort == 'name' else 'p.created_at DESC'
        with self.con() as con:
            rows = con.execute('''SELECT p.*,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id) task_count,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id AND t.status='done') done_count,
                    (SELECT count(*) FROM project_milestones m WHERE m.project_id=p.id) milestone_count,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id AND t.status='needs_review') review_count,
                    (SELECT title FROM project_tasks t WHERE t.project_id=p.id AND t.status IN ('in_progress','needs_review','blocked') ORDER BY t.updated_at DESC LIMIT 1) current_task
                FROM projects p WHERE '''+' AND '.join(clauses)+f' ORDER BY {order}', values).fetchall()
        return [dict(row) for row in rows]

    def create(self, *, name, goal='', description='', target_date=None, project_type='software', success_criteria='', instructions='', context_notes='', tasks=None, milestones=None):
        project_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            con.execute('''INSERT INTO projects(id,name,goal,description,target_date,project_type,success_criteria,instructions,context_notes,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (project_id, name.strip(), goal.strip(), description.strip(), target_date, project_type, success_criteria.strip(), instructions.strip(), context_notes.strip(), stamp, stamp))
            self._activity(con, project_id, 'created project', 'project', project_id, name.strip())
            milestone_ids = {}
            for item in milestones or []:
                milestone_id = str(uuid.uuid4())
                milestone_ids[item.get('client_id')] = milestone_id
                con.execute('''INSERT INTO project_milestones(id,project_id,title,outcome,target_date,completion_criteria,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)''', (milestone_id, project_id, item['title'].strip(), item.get('outcome','').strip(), item.get('target_date'), item.get('completion_criteria','').strip(), stamp, stamp))
            for item in tasks or []:
                milestone_id = milestone_ids.get(item.get('milestone_client_id'))
                task_id = str(uuid.uuid4())
                con.execute('''INSERT INTO project_tasks(id,project_id,title,description,context_notes,status,priority,owner,due_date,milestone_id,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (task_id, project_id, item['title'].strip(), item.get('description','').strip(), item.get('context_notes','').strip(), 'planned', item.get('priority','medium'), item.get('owner','owner'), item.get('due_date'), milestone_id, stamp, stamp))
                if milestone_id:
                    con.execute('INSERT INTO project_milestone_tasks VALUES(?,?,?)', (milestone_id, task_id, project_id))
        return self.get(project_id)

    def get(self, project_id, *, include_archived=False):
        with self.con() as con:
            project = self._dict(con.execute('''SELECT p.*,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id) task_count,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id AND t.status='done') done_count,
                    (SELECT count(*) FROM project_milestones m WHERE m.project_id=p.id) milestone_count
                FROM projects p WHERE p.id=? AND (? OR p.status!='archived') ''', (project_id, int(include_archived))).fetchone())
            if not project:
                return None
            for key, table, order in [
                ('tasks', 'project_tasks', 'created_at'), ('milestones', 'project_milestones', 'target_date'),
                ('threads', 'project_threads', 'updated_at'), ('activity', 'project_activity', 'created_at DESC')]:
                project[key] = [dict(row) for row in con.execute(
                    f'SELECT * FROM {table} WHERE project_id=? ORDER BY {order}', (project_id,)).fetchall()]
            for task in project['tasks']:
                task['file_ids'] = [row['file_id'] for row in con.execute(
                    'SELECT file_id FROM project_task_files WHERE task_id=? ORDER BY file_id', (task['id'],)).fetchall()]
            project['files'] = [dict(row) for row in con.execute('''SELECT f.*,
                    (SELECT size_bytes FROM project_file_blobs b WHERE b.file_id=f.id) size_bytes
                FROM project_files f WHERE f.project_id=? ORDER BY f.created_at''', (project_id,)).fetchall()]
            for thread in project['threads']:
                thread['replies'] = [dict(row) for row in con.execute(
                    'SELECT * FROM project_replies WHERE thread_id=? ORDER BY created_at', (thread['id'],)).fetchall()]
            for milestone in project['milestones']:
                milestone['task_ids'] = [row['task_id'] for row in con.execute(
                    'SELECT task_id FROM project_milestone_tasks WHERE milestone_id=? ORDER BY task_id', (milestone['id'],)).fetchall()]
            project['approvals'] = [dict(row) for row in con.execute(
                'SELECT * FROM project_approvals WHERE project_id=? ORDER BY proposed_at DESC', (project_id,)).fetchall()]
            for approval in project['approvals']:
                approval['task_ids'] = [row['task_id'] for row in con.execute('SELECT task_id FROM project_approval_tasks WHERE approval_id=?', (approval['id'],)).fetchall()]
                approval['file_ids'] = [row['file_id'] for row in con.execute('SELECT file_id FROM project_approval_files WHERE approval_id=?', (approval['id'],)).fetchall()]
                approval['history'] = [dict(row) for row in con.execute('SELECT actor,decision,comments,created_at FROM project_approval_history WHERE approval_id=? ORDER BY created_at', (approval['id'],)).fetchall()]
        return project

    def update(self, project_id, fields):
        allowed = {'name', 'goal', 'description', 'target_date', 'conversation_id', 'project_type', 'success_criteria', 'instructions', 'context_notes', 'status'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        if not fields:
            return self.get(project_id)
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                return None
            con.execute('UPDATE projects SET '+','.join(f'{key}=?' for key in fields)+',updated_at=? WHERE id=?',
                        (*fields.values(), _now(), project_id))
            self._activity(con, project_id, 'updated project', 'project', project_id, ', '.join(fields))
        return self.get(project_id)

    def archive(self, project_id):
        with self.lock, self.con() as con:
            row = con.execute('SELECT id FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone()
            if not row:
                return False
            self._activity(con, project_id, 'archived project', 'project', project_id)
            con.execute('UPDATE projects SET status=\'archived\',updated_at=? WHERE id=?', (_now(), project_id))
        return True

    def restore(self, project_id):
        with self.lock, self.con() as con:
            row = con.execute("SELECT id FROM projects WHERE id=? AND status='archived'", (project_id,)).fetchone()
            if not row:
                return False
            con.execute("UPDATE projects SET status='active',updated_at=? WHERE id=?", (_now(), project_id))
            self._activity(con, project_id, 'restored project', 'project', project_id)
        return True

    def add_task(self, project_id, *, title, description='', context_notes='', status='planned', priority='medium', owner='vishnu', due_date=None, milestone_id=None, file_ids=None):
        task_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            if milestone_id and not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (milestone_id, project_id)).fetchone():
                raise ValueError('Milestone does not belong to this project')
            self._validate_project_files(con, project_id, file_ids or [])
            con.execute('''INSERT INTO project_tasks(id,project_id,title,description,context_notes,status,priority,owner,due_date,milestone_id,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (task_id, project_id, title.strip(), description.strip(), context_notes.strip(), status, priority, owner, due_date, milestone_id, stamp, stamp))
            if milestone_id:
                con.execute('INSERT OR IGNORE INTO project_milestone_tasks VALUES(?,?,?)', (milestone_id, task_id, project_id))
            for file_id in file_ids or []:
                con.execute('INSERT INTO project_task_files VALUES(?,?,?)', (task_id, file_id, project_id))
            self._activity(con, project_id, 'created task', 'task', task_id, title.strip())
        return self.get(project_id)

    def update_task(self, project_id, task_id, fields):
        allowed = {'title', 'description', 'context_notes', 'status', 'priority', 'owner', 'due_date', 'milestone_id', 'file_ids'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM project_tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone():
                return None
            if fields.get('milestone_id') and not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (fields['milestone_id'], project_id)).fetchone():
                raise ValueError('Milestone does not belong to this project')
            if fields:
                file_ids = fields.pop('file_ids', None)
                if file_ids is not None:
                    self._validate_project_files(con, project_id, file_ids)
                    con.execute('DELETE FROM project_task_files WHERE task_id=?', (task_id,))
                    for file_id in file_ids:
                        con.execute('INSERT INTO project_task_files VALUES(?,?,?)', (task_id, file_id, project_id))
                    con.execute('UPDATE project_tasks SET updated_at=? WHERE id=? AND project_id=?', (_now(), task_id, project_id))
                if fields:
                    con.execute('UPDATE project_tasks SET '+','.join(f'{key}=?' for key in fields)+',updated_at=? WHERE id=? AND project_id=?',
                                (*fields.values(), _now(), task_id, project_id))
                self._activity(con, project_id, 'updated task', 'task', task_id, ', '.join(fields))
                if 'milestone_id' in fields:
                    con.execute('DELETE FROM project_milestone_tasks WHERE task_id=? AND project_id=?', (task_id, project_id))
                    if fields['milestone_id']:
                        con.execute('INSERT OR IGNORE INTO project_milestone_tasks VALUES(?,?,?)', (fields['milestone_id'], task_id, project_id))
        return self.get(project_id)

    @staticmethod
    def _validate_project_files(con, project_id, file_ids):
        if not isinstance(file_ids, list) or len(file_ids) > 30 or len(file_ids) != len(set(file_ids)):
            raise ValueError('Choose up to 30 unique project files')
        for file_id in file_ids:
            if not con.execute('SELECT 1 FROM project_files WHERE id=? AND project_id=?', (file_id, project_id)).fetchone():
                raise ValueError('An attached file does not belong to this project')

    def add_approval(self, project_id, *, title, summary, impact_summary='', scope_summary='', task_ids=None, file_ids=None):
        approval_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute("SELECT 1 FROM projects WHERE id=? AND status!='archived'", (project_id,)).fetchone():
                return None
            self._validate_project_relations(con, project_id, task_ids or [], file_ids or [])
            con.execute('INSERT INTO project_approvals(id,project_id,title,summary,impact_summary,scope_summary,proposed_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                        (approval_id, project_id, title.strip(), summary.strip(), impact_summary.strip(), scope_summary.strip(), stamp, stamp))
            for task_id in task_ids or []: con.execute('INSERT INTO project_approval_tasks VALUES(?,?)', (approval_id, task_id))
            for file_id in file_ids or []: con.execute('INSERT INTO project_approval_files VALUES(?,?)', (approval_id, file_id))
            self._activity(con, project_id, 'submitted proposal for review', 'proposal', approval_id, title.strip())
        return self.get(project_id)

    @staticmethod
    def _validate_project_relations(con, project_id, task_ids, file_ids):
        if len(task_ids) > 100 or len(task_ids) != len(set(task_ids)) or len(file_ids) > 100 or len(file_ids) != len(set(file_ids)):
            raise ValueError('Proposal links must be unique and within the supported limit')
        for task_id in task_ids:
            if not con.execute('SELECT 1 FROM project_tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone():
                raise ValueError('A linked task does not belong to this project')
        ProjectStore._validate_project_files(con, project_id, file_ids)

    def revise_approval(self, project_id, approval_id, *, title, summary, impact_summary='', scope_summary='', task_ids=None, file_ids=None):
        stamp = _now()
        with self.lock, self.con() as con:
            row = con.execute("SELECT status FROM project_approvals WHERE id=? AND project_id=?", (approval_id, project_id)).fetchone()
            if not row: return None
            if row['status'] != 'changes_requested': raise ValueError('Only proposals with requested changes can be resubmitted')
            self._validate_project_relations(con, project_id, task_ids or [], file_ids or [])
            con.execute("UPDATE project_approvals SET title=?,summary=?,impact_summary=?,scope_summary=?,status='pending',reviewer=NULL,reviewed_at=NULL,decision=NULL,reviewer_comments='',updated_at=? WHERE id=?", (title.strip(), summary.strip(), impact_summary.strip(), scope_summary.strip(), stamp, approval_id))
            con.execute('DELETE FROM project_approval_tasks WHERE approval_id=?', (approval_id,)); con.execute('DELETE FROM project_approval_files WHERE approval_id=?', (approval_id,))
            for task_id in task_ids or []: con.execute('INSERT INTO project_approval_tasks VALUES(?,?)', (approval_id, task_id))
            for file_id in file_ids or []: con.execute('INSERT INTO project_approval_files VALUES(?,?)', (approval_id, file_id))
            con.execute('INSERT INTO project_approval_history VALUES(?,?,?,?,?,?)', (str(uuid.uuid4()), approval_id, 'owner', 'resubmitted', '', stamp))
            self._activity(con, project_id, 'resubmitted proposal', 'proposal', approval_id, title.strip())
        return self.get(project_id)

    def decide_approval(self, project_id, approval_id, *, decision, comments=''):
        if decision not in {'approved', 'changes_requested'}: raise ValueError('Choose approve or request changes')
        if decision == 'changes_requested' and not comments.strip(): raise ValueError('Add reviewer comments when requesting changes')
        stamp = _now()
        with self.lock, self.con() as con:
            row = con.execute("SELECT status,title FROM project_approvals WHERE id=? AND project_id=?", (approval_id, project_id)).fetchone()
            if not row: return None
            if row['status'] != 'pending': raise ValueError('This proposal has already been reviewed')
            con.execute('UPDATE project_approvals SET status=?,reviewer=?,reviewed_at=?,decision=?,reviewer_comments=?,updated_at=? WHERE id=?',
                        (decision, 'owner', stamp, decision, comments.strip(), stamp, approval_id))
            con.execute('INSERT INTO project_approval_history VALUES(?,?,?,?,?,?)', (str(uuid.uuid4()), approval_id, 'owner', decision, comments.strip(), stamp))
            self._activity(con, project_id, 'reviewed proposal', 'proposal', approval_id, decision)
        return self.get(project_id)

    def add_milestone(self, project_id, *, title, outcome='', target_date=None, completion_criteria='', task_ids=None):
        item_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            con.execute('INSERT INTO project_milestones(id,project_id,title,outcome,target_date,completion_criteria,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                        (item_id, project_id, title.strip(), outcome.strip(), target_date, completion_criteria.strip(), stamp, stamp))
            for task_id in task_ids or []:
                if not con.execute('SELECT 1 FROM project_tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone():
                    raise ValueError('A linked task does not belong to this project')
                con.execute('DELETE FROM project_milestone_tasks WHERE task_id=? AND project_id=?', (task_id, project_id))
                con.execute('UPDATE project_tasks SET milestone_id=? WHERE id=? AND project_id=?', (item_id, task_id, project_id))
                con.execute('INSERT OR IGNORE INTO project_milestone_tasks VALUES(?,?,?)', (item_id, task_id, project_id))
            self._activity(con, project_id, 'created milestone', 'milestone', item_id, title.strip())
        return self.get(project_id)

    def update_milestone(self, project_id, milestone_id, fields):
        allowed = {'title', 'outcome', 'status', 'target_date', 'completion_criteria', 'task_ids'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (milestone_id, project_id)).fetchone():
                return None
            if fields:
                task_ids = fields.pop('task_ids', None)
                if fields:
                    con.execute('UPDATE project_milestones SET '+','.join(f'{key}=?' for key in fields)+',updated_at=? WHERE id=? AND project_id=?',
                                (*fields.values(), _now(), milestone_id, project_id))
                if task_ids is not None:
                    for task_id in task_ids:
                        if not con.execute('SELECT 1 FROM project_tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone():
                            raise ValueError('A linked task does not belong to this project')
                    con.execute('DELETE FROM project_milestone_tasks WHERE milestone_id=?', (milestone_id,))
                    con.execute('UPDATE project_tasks SET milestone_id=NULL WHERE milestone_id=? AND project_id=?', (milestone_id, project_id))
                    for task_id in task_ids:
                        con.execute('DELETE FROM project_milestone_tasks WHERE task_id=? AND project_id=?', (task_id, project_id))
                        con.execute('UPDATE project_tasks SET milestone_id=? WHERE id=? AND project_id=?', (milestone_id, task_id, project_id))
                        con.execute('INSERT INTO project_milestone_tasks VALUES(?,?,?)', (milestone_id, task_id, project_id))
                self._activity(con, project_id, 'updated milestone', 'milestone', milestone_id, ', '.join(fields))
        return self.get(project_id)

    def add_file(self, project_id, *, title, url, kind='link', knowledge_id=None):
        file_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            con.execute('INSERT INTO project_files(id,project_id,title,kind,url,knowledge_id,created_at) VALUES(?,?,?,?,?,?,?)',
                        (file_id, project_id, title.strip(), kind, url.strip(), knowledge_id, stamp))
            self._activity(con, project_id, 'added project source', 'file', file_id, title.strip())
        return self.get(project_id)

    def add_upload(self, project_id, *, title, media_type, content):
        file_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            con.execute('INSERT INTO project_files(id,project_id,title,kind,url,created_at) VALUES(?,?,?,?,?,?)',
                        (file_id, project_id, title.strip(), 'upload', '', stamp))
            con.execute('INSERT INTO project_file_blobs VALUES(?,?,?,?)', (file_id, media_type, sqlite3.Binary(content), len(content)))
            self._activity(con, project_id, 'uploaded project file', 'file', file_id, title.strip())
        return self.get(project_id)

    def file_blob(self, project_id, file_id):
        with self.con() as con:
            row = con.execute('''SELECT f.title,b.media_type,b.content,b.size_bytes FROM project_files f
                JOIN project_file_blobs b ON b.file_id=f.id WHERE f.id=? AND f.project_id=?''', (file_id, project_id)).fetchone()
        return dict(row) if row else None

    def add_thread(self, project_id, *, title, content):
        thread_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            con.execute('INSERT INTO project_threads VALUES(?,?,?,?,?,?)', (thread_id, project_id, title.strip(), 'open', stamp, stamp))
            con.execute('INSERT INTO project_replies VALUES(?,?,?,?,?)', (str(uuid.uuid4()), thread_id, 'owner', content.strip(), stamp))
            self._activity(con, project_id, 'started discussion', 'discussion', thread_id, title.strip())
        return self.get(project_id)

    def add_reply(self, project_id, thread_id, *, author, content):
        stamp = _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM project_threads WHERE id=? AND project_id=?', (thread_id, project_id)).fetchone():
                return None
            con.execute('INSERT INTO project_replies VALUES(?,?,?,?,?)', (str(uuid.uuid4()), thread_id, author, content.strip(), stamp))
            con.execute('UPDATE project_threads SET updated_at=? WHERE id=?', (stamp, thread_id))
            self._activity(con, project_id, 'replied to discussion', 'discussion', thread_id, content.strip()[:160], actor=author)
        return self.get(project_id)

    def record(self, project_id, *, actor, action, target_type='project', target_id=None, detail=''):
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return False
            self._activity(con, project_id, action, target_type, target_id, detail, actor=actor)
        return True
