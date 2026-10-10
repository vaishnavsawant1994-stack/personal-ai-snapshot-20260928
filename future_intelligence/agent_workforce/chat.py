from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AgentConversationStore:
    """Durable specialist-chat history bound to one Project and one agent version."""

    def __init__(self, connection: sqlite3.Connection, *, lock: threading.RLock | None = None):
        self.connection = connection
        self.lock = lock or threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self.lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_conversations(
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL REFERENCES agent_templates(id),
                    version_id TEXT NOT NULL REFERENCES agent_versions(id),
                    instance_id TEXT REFERENCES agent_instances(id),
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_messages(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT,
                    model_id TEXT,
                    request_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_conversations_project_agent
                    ON agent_conversations(project_id, template_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation_created
                    ON agent_messages(conversation_id, created_at, id);
                """
            )

    def create(
        self,
        *,
        template_id: str,
        version_id: str,
        project_id: str,
        instance_id: str | None = None,
        title: str = "New agent chat",
    ) -> dict:
        project_id = str(project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        conversation_id = _id("agentchat")
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO agent_conversations(
                    id,template_id,version_id,instance_id,project_id,title,state,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,'active',?,?)""",
                (
                    conversation_id,
                    template_id,
                    version_id,
                    instance_id,
                    project_id,
                    (str(title).strip() or "New agent chat")[:180],
                    now,
                    now,
                ),
            )
        return self.get(conversation_id)

    def get(self, conversation_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM agent_conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return dict(row)

    def list(self, *, template_id: str | None = None, project_id: str | None = None, limit: int = 100) -> list[dict]:
        clauses, args = [], []
        if template_id:
            clauses.append("template_id=?")
            args.append(template_id)
        if project_id:
            clauses.append("project_id=?")
            args.append(project_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        args.append(max(1, min(500, int(limit))))
        rows = self.connection.execute(
            "SELECT * FROM agent_conversations" + where + " ORDER BY updated_at DESC,id LIMIT ?",
            tuple(args),
        ).fetchall()
        return [dict(row) for row in rows]

    def append(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        provider: str | None = None,
        model_id: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("unsupported agent-chat role")
        content = str(content or "")
        if not content.strip():
            raise ValueError("message content is required")
        self.get(conversation_id)
        message_id = _id("agentmsg")
        now = _now()
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO agent_messages(
                    id,conversation_id,role,content,provider,model_id,request_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (message_id, conversation_id, role, content[:32000], provider, model_id, request_id, now),
            )
            self.connection.execute(
                "UPDATE agent_conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )
        return dict(
            self.connection.execute("SELECT * FROM agent_messages WHERE id=?", (message_id,)).fetchone()
        )

    def messages(self, conversation_id: str, *, limit: int = 100) -> list[dict]:
        self.get(conversation_id)
        limit = max(1, min(500, int(limit)))
        rows = self.connection.execute(
            """SELECT * FROM (
                SELECT * FROM agent_messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?
            ) ORDER BY created_at,id""",
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self, conversation_id: str) -> dict:
        self.get(conversation_id)
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE agent_conversations SET state='closed',updated_at=? WHERE id=?",
                (_now(), conversation_id),
            )
        return self.get(conversation_id)
