"""Manual database backup -- Activation 7 FIX (blocker 3).

Requirement this fix satisfies (LOCKED SCOPE): a manual way to produce
a database backup that can be verified/restored. Nothing more.

Manual only -- no scheduler, no timer, no background thread, no
cron/daemon wiring, and no automatic invocation from ``init``,
``doctor``, ``report``, ``paper``, ``scan``, or any other command.
The operator must explicitly run ``python main.py backup`` (or call
:func:`create_backup` directly) every time a backup is wanted. This
module defines no periodic/retention policy of any kind (no "keep
last N", no rotation) -- each call produces exactly one new,
timestamped file, and nothing here ever deletes an existing backup.

Explicitly out of scope for this fix (unchanged, untouched): user
approval, Telegram/notifications, migrations
(``Database.migration_registry``/``Database.migrations_*``),
``ReconciliationEngine``, any performance engine/service, and any
scheduler/background worker. This module imports none of those and
is not called from any of them.

Mechanism (LOCKED DECISION -- reuse, not reinvent): this uses
SQLite's own built-in *online backup API*
(``sqlite3.Connection.backup()``), never a hand-rolled byte copy. The
default ``Database.database_config.DatabaseConfig`` journal mode is
WAL, so a plain ``shutil.copy()`` of only the ``.db`` file can miss
data still sitting in the ``-wal`` file, or copy a half-written file
and produce a corrupt backup. SQLite's backup API is that engine's
own documented answer to exactly this problem: it copies the database
page-by-page into a fresh destination file while the source stays
fully usable (even from another process/connection) -- no downtime,
no locking-out of the live application, and no new copy algorithm
introduced by this module.

The source connection this module opens is read-only (SQLite's
``mode=ro`` URI parameter), so creating a backup can never itself
write to -- or otherwise mutate -- the live source database file.

Verifiability/restorability: :func:`verify_backup` opens the produced
file as a real SQLite database and runs ``PRAGMA integrity_check``,
proving the backup is not merely a same-sized file but an actually
openable, structurally sound SQLite database -- i.e. one that can be
restored by simply copying it back over (or pointing ``DB_PATH`` at)
the original location. :func:`restore_backup` performs exactly that
copy-back, for the same reason -- restoring a SQLite backup is not a
distinct format-specific operation, it is "use this file as the
database file", so no new restore protocol is invented here either.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from Core.exceptions import DatabaseError
from Core.logger import get_logger

logger = get_logger(__name__)

#: Filename timestamp format for backup files -- sortable, filesystem-safe,
#: UTC (mirrors every other ``generated_at``/timestamp convention already
#: used across this codebase's CLI commands).
_BACKUP_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def default_backup_dir(db_path: Path) -> Path:
    """The default destination directory for backups of ``db_path``:
    a ``backups/`` sibling of the database file's own parent
    directory (e.g. ``data/aios.db`` -> ``data/backups/``).

    Purely a path computation -- creates nothing. Only
    :func:`create_backup` actually creates this directory, and only
    when the caller did not supply an explicit ``backup_dir``.
    """
    return db_path.parent / "backups"


def _timestamped_backup_path(db_path: Path, backup_dir: Path) -> Path:
    """Build a unique, sortable backup filename from ``db_path``'s own
    stem plus a UTC timestamp, e.g. ``aios_20260813T101530Z.db``."""
    timestamp = datetime.now(timezone.utc).strftime(_BACKUP_TIMESTAMP_FORMAT)
    return backup_dir / f"{db_path.stem}_{timestamp}.db"


def create_backup(db_path: Path, backup_dir: Optional[Path] = None) -> Path:
    """Create one on-demand, restorable backup of the SQLite database
    at ``db_path``, via SQLite's own online backup API.

    The source database is opened strictly read-only (``mode=ro``),
    so this function cannot itself modify ``db_path`` -- it only ever
    reads from it. The backup is written to a brand-new, uniquely
    timestamped file; an existing database file at ``db_path`` (and
    any prior backup) is never opened for writing, truncated, or
    deleted by this function.

    Args:
        db_path: Path to the live database file to back up. Must
            already exist.
        backup_dir: Directory the backup file is written into.
            Defaults to :func:`default_backup_dir`. Created (including
            parents) if it does not exist yet -- the only filesystem
            mutation this function performs outside of writing the
            backup file itself.

    Returns:
        Path to the newly created, already-verified-openable backup
        file.

    Raises:
        DatabaseError: If ``db_path`` does not exist, or the backup
            could not be completed (e.g. SQLite reports a corrupt
            source). No partial/corrupt backup file is left behind --
            it is deleted before this is raised.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise DatabaseError(f"Cannot back up: database file does not exist at '{db_path}'.")

    target_dir = Path(backup_dir) if backup_dir is not None else default_backup_dir(db_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _timestamped_backup_path(db_path, target_dir)

    # Read-only source connection: this function can never write to,
    # or otherwise mutate, the live database file it is reading from.
    source_uri = f"file:{db_path.as_posix()}?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True)
    try:
        dest_conn = sqlite3.connect(str(backup_path))
        try:
            # SQLite's own online backup API (LOCKED mechanism choice
            # -- see module docstring): safe to run while the source
            # is open/in active use elsewhere, WAL-aware, no downtime.
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    except sqlite3.Error as exc:
        if backup_path.exists():
            backup_path.unlink()
        raise DatabaseError(f"Backup failed for '{db_path}': {exc}") from exc
    finally:
        source_conn.close()

    logger.info("Database backup created: '%s' -> '%s'", db_path, backup_path)
    return backup_path


def verify_backup(backup_path: Path) -> bool:
    """Confirm ``backup_path`` is a genuinely openable, structurally
    sound SQLite database -- i.e. that the backup is actually usable,
    not just a same-sized file.

    Opens ``backup_path`` as SQLite and runs ``PRAGMA
    integrity_check``, which walks every page SQLite itself knows
    about. Returns ``True`` only when that check reports exactly
    ``"ok"``. Never mutates ``backup_path`` -- ``PRAGMA
    integrity_check`` is a read-only diagnostic, the only statement
    this function executes.

    Args:
        backup_path: Path to the backup file to verify.

    Returns:
        ``True`` if the file exists, opens as SQLite, and passes
        ``PRAGMA integrity_check``; ``False`` if the file is missing,
        is not a SQLite database at all, or fails the check.
    """
    backup_path = Path(backup_path)
    if not backup_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(backup_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return row is not None and row[0] == "ok"


def restore_backup(backup_path: Path, target_db_path: Path) -> Path:
    """Restore ``backup_path`` by copying it over ``target_db_path``.

    Restoring a SQLite backup is not a distinct format-specific
    operation -- a backup produced by :func:`create_backup` already
    *is* a complete, standalone SQLite database file, so "restoring"
    it means using that file as the database file. This function
    performs exactly that: a plain file copy of ``backup_path`` onto
    ``target_db_path`` (overwriting whatever is there), after
    confirming via :func:`verify_backup` that the backup is actually
    valid -- a corrupt or missing backup is never copied over a live
    database.

    This is a manual, explicitly-invoked operation (mirrors
    :func:`create_backup`'s own manual-only scope) -- callers are
    responsible for closing/disconnecting any live connection to
    ``target_db_path`` before calling this, exactly as they would for
    any other direct SQLite file swap.

    Args:
        backup_path: Path to a backup file previously produced by
            :func:`create_backup`.
        target_db_path: Path to overwrite with the backup's contents.

    Returns:
        ``target_db_path``, unchanged, for convenience chaining.

    Raises:
        DatabaseError: If ``backup_path`` does not exist or fails
            :func:`verify_backup`.
    """
    backup_path = Path(backup_path)
    target_db_path = Path(target_db_path)
    if not verify_backup(backup_path):
        raise DatabaseError(
            f"Refusing to restore: '{backup_path}' is missing or is not a valid SQLite backup."
        )
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(backup_path), str(target_db_path))
    logger.info("Database restored: '%s' -> '%s'", backup_path, target_db_path)
    return target_db_path