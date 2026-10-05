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
              CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
              CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, created_at);
              CREATE INDEX IF NOT EXISTS idx_project_activity_project ON project_activity(project_id, created_at DESC);
            ''')

    @staticmethod
    def _dict(row):
        return dict(row) if row else None

    def _activity(self, con, project_id, action, target_type, target_id=None, detail='', actor='owner'):
        con.execute('INSERT INTO project_activity VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()), project_id, actor, action, target_type, target_id, detail[:1000], _now()))
        con.execute('UPDATE projects SET updated_at=? WHERE id=?', (_now(), project_id))

    def list(self, query=''):
        query = f'%{query.strip()}%'
        with self.con() as con:
            rows = con.execute('''SELECT p.*,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id) task_count,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id AND t.status='done') done_count,
                    (SELECT count(*) FROM project_milestones m WHERE m.project_id=p.id) milestone_count
                FROM projects p WHERE p.status!='archived' AND (p.name LIKE ? OR p.goal LIKE ?)
                ORDER BY p.updated_at DESC''', (query, query)).fetchall()
        return [dict(row) for row in rows]

    def create(self, *, name, goal='', description='', target_date=None):
        project_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            con.execute('INSERT INTO projects(id,name,goal,description,target_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (project_id, name.strip(), goal.strip(), description.strip(), target_date, stamp, stamp))
            self._activity(con, project_id, 'created project', 'project', project_id, name.strip())
        return self.get(project_id)

    def get(self, project_id):
        with self.con() as con:
            project = self._dict(con.execute('''SELECT p.*,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id) task_count,
                    (SELECT count(*) FROM project_tasks t WHERE t.project_id=p.id AND t.status='done') done_count,
                    (SELECT count(*) FROM project_milestones m WHERE m.project_id=p.id) milestone_count
                FROM projects p WHERE p.id=? AND p.status!='archived' ''', (project_id,)).fetchone())
            if not project:
                return None
            for key, table, order in [
                ('tasks', 'project_tasks', 'created_at'), ('milestones', 'project_milestones', 'target_date'),
                ('threads', 'project_threads', 'updated_at'), ('files', 'project_files', 'created_at'),
                ('activity', 'project_activity', 'created_at DESC')]:
                project[key] = [dict(row) for row in con.execute(
                    f'SELECT * FROM {table} WHERE project_id=? ORDER BY {order}', (project_id,)).fetchall()]
            for thread in project['threads']:
                thread['replies'] = [dict(row) for row in con.execute(
                    'SELECT * FROM project_replies WHERE thread_id=? ORDER BY created_at', (thread['id'],)).fetchall()]
        return project

    def update(self, project_id, fields):
        allowed = {'name', 'goal', 'description', 'target_date', 'conversation_id'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        if not fields:
            return self.get(project_id)
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
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

    def add_task(self, project_id, *, title, description='', priority='medium', owner='vishnu', due_date=None, milestone_id=None):
        task_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            if milestone_id and not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (milestone_id, project_id)).fetchone():
                raise ValueError('Milestone does not belong to this project')
            con.execute('''INSERT INTO project_tasks(id,project_id,title,description,priority,owner,due_date,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?)''', (task_id, project_id, title.strip(), description.strip(), priority, owner, due_date, stamp, stamp))
            self._activity(con, project_id, 'created task', 'task', task_id, title.strip())
        return self.get(project_id)

    def update_task(self, project_id, task_id, fields):
        allowed = {'title', 'description', 'status', 'priority', 'owner', 'due_date', 'milestone_id'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM project_tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone():
                return None
            if fields.get('milestone_id') and not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (fields['milestone_id'], project_id)).fetchone():
                raise ValueError('Milestone does not belong to this project')
            if fields:
                con.execute('UPDATE project_tasks SET '+','.join(f'{key}=?' for key in fields)+',updated_at=? WHERE id=? AND project_id=?',
                            (*fields.values(), _now(), task_id, project_id))
                self._activity(con, project_id, 'updated task', 'task', task_id, ', '.join(fields))
        return self.get(project_id)

    def add_milestone(self, project_id, *, title, outcome='', target_date=None):
        item_id, stamp = str(uuid.uuid4()), _now()
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM projects WHERE id=? AND status!=\'archived\'', (project_id,)).fetchone():
                return None
            con.execute('INSERT INTO project_milestones(id,project_id,title,outcome,target_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (item_id, project_id, title.strip(), outcome.strip(), target_date, stamp, stamp))
            self._activity(con, project_id, 'created milestone', 'milestone', item_id, title.strip())
        return self.get(project_id)

    def update_milestone(self, project_id, milestone_id, fields):
        allowed = {'title', 'outcome', 'status', 'target_date'}
        fields = {key: (value.strip() if isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
        with self.lock, self.con() as con:
            if not con.execute('SELECT 1 FROM project_milestones WHERE id=? AND project_id=?', (milestone_id, project_id)).fetchone():
                return None
            if fields:
                con.execute('UPDATE project_milestones SET '+','.join(f'{key}=?' for key in fields)+',updated_at=? WHERE id=? AND project_id=?',
                            (*fields.values(), _now(), milestone_id, project_id))
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
