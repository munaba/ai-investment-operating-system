from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from Core.config import config

_DEFAULT_DB_PATH: str = "data/investment_platform.db"
_DEFAULT_TIMEOUT: float = 30.0
_DEFAULT_JOURNAL_MODE: str = "WAL"
_DEFAULT_SYNCHRONOUS: str = "NORMAL"
_DEFAULT_FOREIGN_KEYS: bool = True
_DEFAULT_URI_MODE: bool = False


@dataclass
class DatabaseConfig:
    """Connection and pragma configuration for a database backend.

    Attributes:
        db_path: Filesystem path to the database file (for file-based
            backends such as SQLite). Ignored by network-based backends
            (e.g. a future Cloud SQL/PostgreSQL config would use a
            connection string instead, via ``extra_pragmas`` or a
            subclass -- not needed for this stage).
        timeout: Seconds to wait for a locked database before raising.
        journal_mode: SQLite journal mode (e.g. ``"WAL"``, ``"DELETE"``).
            Ignored by backends that don't have this concept.
        synchronous: SQLite ``synchronous`` pragma value (e.g.
            ``"NORMAL"``, ``"FULL"``).
        foreign_keys: Whether to enforce foreign key constraints.
        extra_pragmas: Additional backend-specific pragmas/options not
            covered by the named fields above, applied as-is by the
            concrete backend.
        uri_mode: SQLite-specific. When ``True``, ``db_path`` is treated
            as a ``sqlite3`` URI (passed with ``uri=True``) rather than a
            plain filesystem path. This is the supported way to opt into
            a shared-cache in-memory database (e.g.
            ``db_path="file::memory:?cache=shared"``) so that multiple
            threads see the same data. Bare ``":memory:"`` is intentionally
            rejected without this flag -- see
            :class:`Database.sqlite_database.SQLiteDatabase` and
            ``Database/ARCHITECTURE.md`` for why. Ignored by backends
            that don't have this concept.
    """

    db_path: Path = field(default_factory=lambda: Path(_DEFAULT_DB_PATH))
    timeout: float = _DEFAULT_TIMEOUT
    journal_mode: str = _DEFAULT_JOURNAL_MODE
    synchronous: str = _DEFAULT_SYNCHRONOUS
    foreign_keys: bool = _DEFAULT_FOREIGN_KEYS
    extra_pragmas: Dict[str, Any] = field(default_factory=dict)
    uri_mode: bool = _DEFAULT_URI_MODE

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Build a :class:`DatabaseConfig` from environment variables.

        Reads ``DB_PATH``, ``DB_TIMEOUT``, ``DB_JOURNAL_MODE``,
        ``DB_SYNCHRONOUS``, and ``DB_FOREIGN_KEYS`` via ``Core.config``,
        falling back to this class's defaults for any variable that is
        not set. Never raises for missing variables (mirrors how
        ``Core.request_defaults`` values are consumed elsewhere in this
        framework).

        Returns:
            A populated :class:`DatabaseConfig`.
        """
        return cls(
            db_path=Path(config.get_str("DB_PATH", _DEFAULT_DB_PATH)),
            timeout=config.get_float("DB_TIMEOUT", _DEFAULT_TIMEOUT),
            journal_mode=config.get_str("DB_JOURNAL_MODE", _DEFAULT_JOURNAL_MODE),
            synchronous=config.get_str("DB_SYNCHRONOUS", _DEFAULT_SYNCHRONOUS),
            foreign_keys=config.get_bool("DB_FOREIGN_KEYS", _DEFAULT_FOREIGN_KEYS),
            uri_mode=config.get_bool("DB_URI_MODE", _DEFAULT_URI_MODE),
        )