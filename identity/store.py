from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .body import BodyManifest, BodyRevisionStatus
from .migrations import migrate_identity_schema
from .self_model import SelfProfile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class IdentityStore:
    """Durable identity persistence with append-only Self history and Body lineage."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if connection is not None and db_path is not None:
            raise ValueError("provide db_path or connection, not both")
        self._owns_connection = connection is None
        self.connection = connection or sqlite3.connect(str(db_path or ":memory:"))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        migrate_identity_schema(self.connection)

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "IdentityStore":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def append_self_version(self, profile: SelfProfile, *, created_by: str) -> int:
        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("created_by is required")
        now = _now()
        payload = profile.to_dict()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO identity_self_versions(
                    payload_json, payload_hash, created_at, created_by
                ) VALUES (?, ?, ?, ?)
                """,
                (_json(payload), profile.payload_hash, now, actor),
            )
            version = int(cursor.lastrowid)
            self._append_event_locked(
                "self.version.created",
                {"version": version, "payload_hash": profile.payload_hash, "created_by": actor},
                now=now,
            )
        return version

    def get_self_version(self, version: int) -> SelfProfile | None:
        row = self.connection.execute(
            "SELECT payload_json FROM identity_self_versions WHERE version = ?", (version,)
        ).fetchone()
        return SelfProfile.from_dict(json.loads(row[0])) if row else None

    def latest_self_version(self) -> tuple[int, SelfProfile] | None:
        row = self.connection.execute(
            """
            SELECT version, payload_json
            FROM identity_self_versions
            ORDER BY version DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return int(row["version"]), SelfProfile.from_dict(json.loads(row["payload_json"]))

    def record_body_revision(
        self,
        manifest: BodyManifest,
        *,
        git_revision: str,
        status: BodyRevisionStatus = BodyRevisionStatus.CANDIDATE,
    ) -> str:
        git_revision = str(git_revision or "").strip()
        if not git_revision:
            raise ValueError("git_revision is required")
        revision_id = manifest.revision_id_for(git_revision)
        existing = self.connection.execute(
            """
            SELECT git_revision, manifest_hash
            FROM software_body_revisions
            WHERE revision_id = ?
            """,
            (revision_id,),
        ).fetchone()
        if existing is not None:
            if existing["git_revision"] != git_revision or existing["manifest_hash"] != manifest.manifest_hash:
                raise ValueError("body revision identity collision")
            return revision_id

        now = _now()
        contracts = manifest.contracts
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO software_body_revisions(
                    revision_id, git_revision, body_version,
                    work_contract_version, evidence_contract_version,
                    evolution_contract_version, continuity_contract_version,
                    extension_contract_version, manifest_hash, manifest_json,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    git_revision,
                    manifest.body_version,
                    contracts.get("work"),
                    contracts.get("evidence"),
                    contracts.get("evolution"),
                    contracts.get("continuity"),
                    contracts.get("extension"),
                    manifest.manifest_hash,
                    _json(manifest.to_dict()),
                    status.value,
                    now,
                ),
            )
            self._append_event_locked(
                "body.revision.recorded",
                {"revision_id": revision_id, "git_revision": git_revision, "status": status.value},
                now=now,
            )
        return revision_id

    def get_body_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM software_body_revisions WHERE revision_id = ?", (revision_id,)
        ).fetchone()
        return dict(row) if row else None

    def active_body_revision(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM software_body_revisions
            WHERE status = ?
            ORDER BY activated_at DESC, created_at DESC
            LIMIT 1
            """,
            (BodyRevisionStatus.ACTIVE.value,),
        ).fetchone()
        return dict(row) if row else None

    def activate_body_revision(self, revision_id: str, *, actor: str) -> None:
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        now = _now()
        with self.connection:
            target = self.connection.execute(
                "SELECT revision_id, status FROM software_body_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
            if target is None:
                raise KeyError(revision_id)
            if target["status"] == BodyRevisionStatus.REJECTED.value:
                raise ValueError("rejected body revision cannot be activated")
            if target["status"] == BodyRevisionStatus.ACTIVE.value:
                return
            self.connection.execute(
                """
                UPDATE software_body_revisions
                SET status = ?, superseded_at = ?
                WHERE status = ? AND revision_id <> ?
                """,
                (
                    BodyRevisionStatus.SUPERSEDED.value,
                    now,
                    BodyRevisionStatus.ACTIVE.value,
                    revision_id,
                ),
            )
            self.connection.execute(
                """
                UPDATE software_body_revisions
                SET status = ?, activated_at = ?, superseded_at = NULL
                WHERE revision_id = ?
                """,
                (BodyRevisionStatus.ACTIVE.value, now, revision_id),
            )
            self._append_event_locked(
                "body.revision.activated",
                {"revision_id": revision_id, "actor": actor},
                now=now,
            )

    def set_state(self, key: str, value: Any) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            raise ValueError("state key is required")
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO identity_state(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (normalized, _json(value), now),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute(
            "SELECT value_json FROM identity_state WHERE key = ?", (str(key),)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def list_events(self, *, event_type: str | None = None) -> list[dict[str, Any]]:
        if event_type is None:
            rows = self.connection.execute(
                "SELECT id, event_type, payload_json, created_at FROM identity_events ORDER BY id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM identity_events
                WHERE event_type = ?
                ORDER BY id
                """,
                (event_type,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _append_event_locked(self, event_type: str, payload: dict[str, Any], *, now: str) -> None:
        self.connection.execute(
            "INSERT INTO identity_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
            (event_type, _json(payload), now),
        )
