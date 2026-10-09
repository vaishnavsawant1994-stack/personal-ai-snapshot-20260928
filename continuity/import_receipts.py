from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from recovery.backup import NON_RESTORABLE_SECURITY_NAMES


IMPORT_RECEIPT_FILENAME = "continuity-import-receipts.sqlite3"
# Register the receipt ledger as target-local security authority. It must never
# be overwritten by a source checkpoint, otherwise a bundle replay could rewind
# the record that proves it was already imported.
NON_RESTORABLE_SECURITY_NAMES.add(IMPORT_RECEIPT_FILENAME)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bundle_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ContinuityImportRecoveryRequired(RuntimeError):
    pass


class ContinuityImportReceiptStore:
    """Target-local exactly-once fence around the destructive restore boundary."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS continuity_import_receipts(
                    grant_id TEXT PRIMARY KEY,
                    checkpoint_id TEXT NOT NULL,
                    bundle_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_type TEXT
                )
                """
            )

    def _con(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def claim(self, *, grant_id: str, checkpoint_id: str, bundle_hash: str) -> None:
        stamp = _now()
        with self._con() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM continuity_import_receipts WHERE grant_id=?",
                (str(grant_id),),
            ).fetchone()
            if row is not None:
                same = (
                    str(row["checkpoint_id"]) == str(checkpoint_id)
                    and str(row["bundle_sha256"]) == str(bundle_hash)
                )
                if not same:
                    raise ContinuityImportRecoveryRequired(
                        "continuity grant id is already bound to another import artifact"
                    )
                raise ContinuityImportRecoveryRequired(
                    f"continuity import is {row['status']}; manual recovery is required before replay"
                )
            connection.execute(
                """
                INSERT INTO continuity_import_receipts(
                    grant_id, checkpoint_id, bundle_sha256, status,
                    started_at, completed_at, error_type
                ) VALUES (?, ?, ?, 'in_progress', ?, NULL, NULL)
                """,
                (str(grant_id), str(checkpoint_id), str(bundle_hash), stamp),
            )
            connection.commit()

    def mark_completed(self, grant_id: str) -> None:
        stamp = _now()
        with self._con() as connection:
            cursor = connection.execute(
                """
                UPDATE continuity_import_receipts
                SET status='completed', completed_at=?, error_type=NULL
                WHERE grant_id=? AND status='in_progress'
                """,
                (stamp, str(grant_id)),
            )
            if cursor.rowcount != 1:
                raise ContinuityImportRecoveryRequired("continuity import receipt is not in progress")

    def mark_recovery_required(self, grant_id: str, *, error_type: str) -> None:
        with self._con() as connection:
            connection.execute(
                """
                UPDATE continuity_import_receipts
                SET status='recovery_required', error_type=?
                WHERE grant_id=? AND status='in_progress'
                """,
                (str(error_type)[:200], str(grant_id)),
            )

    def get(self, grant_id: str) -> dict | None:
        with self._con() as connection:
            row = connection.execute(
                "SELECT * FROM continuity_import_receipts WHERE grant_id=?",
                (str(grant_id),),
            ).fetchone()
        return dict(row) if row is not None else None
