from __future__ import annotations

import sqlite3
from pathlib import Path

from .durability import WorkDurabilityMixin
from .durability_migrations import migrate_work_durability_schema
from .store import WorkStore


class DurableWorkStore(WorkDurabilityMixin, WorkStore):
    """Canonical WorkStore plus additive execution durability primitives."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        super().__init__(db_path, connection=connection)
        migrate_work_durability_schema(self.connection)
