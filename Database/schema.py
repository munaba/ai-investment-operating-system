from __future__ import annotations

from typing import Tuple

SCHEMA_MIGRATIONS_TABLE: str = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
)
"""

BOOTSTRAP_STATEMENTS: Tuple[str, ...] = (SCHEMA_MIGRATIONS_TABLE,)