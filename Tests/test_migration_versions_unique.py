"""Guard: migration versions must be globally unique across all Database/migrations_* modules.

The schema_migrations table uses a SINGLE shared version sequence across
every domain module. If two modules declare the same version number the
second one is silently skipped by MigrationRunner._pending() on every
database that already has the first one applied -- production bug, not
a test failure (see: v12 collision between idempotency and snapshots).
"""
from __future__ import annotations

import importlib
import pkgutil
from collections import Counter

import Database
import pytest


def _all_migration_versions():
    versions = []
    for mod_info in pkgutil.iter_modules(Database.__path__):
        if not mod_info.name.startswith("migrations_"):
            continue
        mod = importlib.import_module(f"Database.{mod_info.name}")
        for attr in dir(mod):
            if not attr.endswith("MIGRATIONS"):
                continue
            tup = getattr(mod, attr)
            if not isinstance(tup, tuple):
                continue
            for m in tup:
                versions.append((m.version, mod_info.name, getattr(m, "name", "?")))
    return versions


def test_migration_versions_globally_unique():
    versions = _all_migration_versions()
    counts = Counter(v for v, _, _ in versions)
    dupes = {v: c for v, c in counts.items() if c > 1}
    assert not dupes, (
        "Duplicate migration versions found (global schema_migrations sequence): "
        + repr(dupes)
        + " :: "
        + repr([(v, m, n) for v, m, n in versions if v in dupes])
    )