from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import VisualGraph, VisualMode, VisualType


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VisualStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self):
        with self._lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS visualizations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    project_id TEXT,
                    conversation_id TEXT,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'description',
                    source_ref TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    graph_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_visualizations_owner_updated
                    ON visualizations(owner_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_visualizations_project
                    ON visualizations(owner_id, project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS visualization_revisions (
                    id TEXT PRIMARY KEY,
                    visualization_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    graph_json TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'update',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(visualization_id) REFERENCES visualizations(id) ON DELETE CASCADE,
                    UNIQUE(visualization_id, revision)
                );
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item['graph'] = json.loads(item.pop('graph_json'))
        return item

    def create(
        self,
        *,
        owner_id: str,
        title: str,
        visual_type: VisualType,
        mode: VisualMode,
        graph: VisualGraph,
        project_id: str | None = None,
        conversation_id: str | None = None,
        source_kind: str = 'description',
        source_ref: str | None = None,
        description: str = '',
    ) -> dict[str, Any]:
        visual_id = uuid.uuid4().hex
        stamp = _now()
        encoded = json.dumps(graph.to_dict(), ensure_ascii=False, separators=(',', ':'))
        with self._lock, self.connection:
            self.connection.execute(
                """INSERT INTO visualizations
                (id,owner_id,project_id,conversation_id,title,type,mode,source_kind,source_ref,description,graph_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (visual_id, owner_id, project_id, conversation_id, title, visual_type.value, mode.value, source_kind, source_ref, description, encoded, stamp, stamp),
            )
            self.connection.execute(
                "INSERT INTO visualization_revisions(id,visualization_id,owner_id,revision,graph_json,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, visual_id, owner_id, 1, encoded, 'created', stamp),
            )
        return self.get(owner_id, visual_id)

    def get(self, owner_id: str, visual_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                'SELECT * FROM visualizations WHERE id=? AND owner_id=?', (visual_id, owner_id)
            ).fetchone()
        return self._decode(row) if row else None

    def list(self, owner_id: str, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = 'SELECT * FROM visualizations WHERE owner_id=?'
        args: list[Any] = [owner_id]
        if project_id is not None:
            sql += ' AND project_id=?'; args.append(project_id)
        sql += ' ORDER BY updated_at DESC LIMIT ?'; args.append(max(1, min(int(limit), 250)))
        with self._lock:
            rows = self.connection.execute(sql, args).fetchall()
        return [self._decode(row) for row in rows]

    def update_graph(self, owner_id: str, visual_id: str, graph: VisualGraph, *, reason: str = 'update', title: str | None = None) -> dict[str, Any]:
        current = self.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        encoded = json.dumps(graph.to_dict(), ensure_ascii=False, separators=(',', ':'))
        stamp = _now()
        with self._lock, self.connection:
            revision = int(self.connection.execute(
                'SELECT COALESCE(MAX(revision),0)+1 FROM visualization_revisions WHERE visualization_id=? AND owner_id=?',
                (visual_id, owner_id),
            ).fetchone()[0])
            self.connection.execute(
                'UPDATE visualizations SET graph_json=?,title=?,updated_at=? WHERE id=? AND owner_id=?',
                (encoded, title or current['title'], stamp, visual_id, owner_id),
            )
            self.connection.execute(
                'INSERT INTO visualization_revisions(id,visualization_id,owner_id,revision,graph_json,reason,created_at) VALUES(?,?,?,?,?,?,?)',
                (uuid.uuid4().hex, visual_id, owner_id, revision, encoded, reason[:120], stamp),
            )
        return self.get(owner_id, visual_id)

    def patch(self, owner_id: str, visual_id: str, *, title: str | None = None, mode: VisualMode | None = None) -> dict[str, Any]:
        current = self.get(owner_id, visual_id)
        if current is None:
            raise KeyError(visual_id)
        with self._lock, self.connection:
            self.connection.execute(
                'UPDATE visualizations SET title=?,mode=?,updated_at=? WHERE id=? AND owner_id=?',
                (title or current['title'], (mode or VisualMode(current['mode'])).value, _now(), visual_id, owner_id),
            )
        return self.get(owner_id, visual_id)

    def revisions(self, owner_id: str, visual_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                'SELECT revision,reason,created_at,graph_json FROM visualization_revisions WHERE visualization_id=? AND owner_id=? ORDER BY revision DESC',
                (visual_id, owner_id),
            ).fetchall()
        return [
            {'revision': row['revision'], 'reason': row['reason'], 'created_at': row['created_at'], 'graph': json.loads(row['graph_json'])}
            for row in rows
        ]

    def delete(self, owner_id: str, visual_id: str) -> bool:
        with self._lock, self.connection:
            self.connection.execute('DELETE FROM visualization_revisions WHERE visualization_id=? AND owner_id=?', (visual_id, owner_id))
            result = self.connection.execute('DELETE FROM visualizations WHERE id=? AND owner_id=?', (visual_id, owner_id))
        return result.rowcount > 0

    def close(self):
        with self._lock:
            self.connection.close()
