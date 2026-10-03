"""Canonical migration registry (Activation 1.3).

Single source of truth for *which* domain migration tuples exist and
in *what order* they must be applied. Before Activation 1.3 this list
was declared privately inside ``Core.doctor`` (``_MIGRATION_MODULES``)
purely for read-only diagnostics. Activation 1.3 needs the exact same
list for a second, write-capable purpose (``python main.py init``), so
it is moved here and both ``Core.doctor`` and ``Core.init_command``
import it -- per the Activation 1.3 audit rule ("AUDIT BEFORE
UNIFYING"), this is the "existing canonical migration abstraction",
extracted rather than re-declared, so there is exactly one place this
ordering is written down.

Ordering contract: ``MIGRATION_MODULES`` is declared in the domain
order established by the source audit (Sprint 3/4/5 STEPs, see each
``Database.migrations_<domain>.py`` module docstring for its reserved
version number). ``all_migrations()`` additionally sorts by
``Migration.version`` so version order is an enforced invariant, not
an accident of declaration order -- today the two orders coincide
(1, 2, 3, 4, 5, 10), but a future domain added out of declaration
order would still be applied in the correct version sequence.
"""

from __future__ import annotations

import importlib
from typing import List, Sequence, Tuple

from .migrations import Migration

#: domain label -> (module path, tuple-of-Migration attribute name).
#: Source: Database/migrations_watchlist.py, migrations_accounts.py,
#: migrations_positions.py, migrations_orders.py, migrations_trades.py,
#: migrations_snapshots.py -- six independent domains, each with its
#: own standalone MIGRATIONS tuple (see each module's own "Migration
#: version allocation" comment for the reserved version number).
MIGRATION_MODULES: Sequence[Tuple[str, str, str]] = (
    ("watchlist", "Database.migrations_watchlist", "WATCHLIST_MIGRATIONS"),
    ("accounts", "Database.migrations_accounts", "ACCOUNTS_MIGRATIONS"),
    ("positions", "Database.migrations_positions", "POSITIONS_MIGRATIONS"),
    ("orders", "Database.migrations_orders", "ORDERS_MIGRATIONS"),
    ("trades", "Database.migrations_trades", "TRADES_MIGRATIONS"),
    ("snapshots", "Database.migrations_snapshots", "SNAPSHOTS_MIGRATIONS"),
    ("idempotency", "Database.migrations_idempotency", "IDEMPOTENCY_MIGRATIONS"),
    ("portfolio_snapshots", "Database.migrations_portfolio_snapshots", "PORTFOLIO_SNAPSHOTS_MIGRATIONS"),
    ("order_approvals", "Database.migrations_order_approvals", "ORDER_APPROVALS_MIGRATIONS"),
)


def all_migrations() -> List[Tuple[Migration, str]]:
    """Return every declared :class:`Migration` across all domains as
    ``(Migration, domain)`` pairs, sorted by ``version`` ascending.

    This is the one canonical ordered migration plan every caller
    (``python main.py init``, ``python main.py doctor``) must use --
    never re-derive a different ordering elsewhere.
    """
    entries: List[Tuple[Migration, str]] = []
    for domain, module_path, attr_name in MIGRATION_MODULES:
        module = importlib.import_module(module_path)
        migrations = getattr(module, attr_name)
        for migration in migrations:
            entries.append((migration, domain))
    return sorted(entries, key=lambda pair: pair[0].version)


def expected_migrations() -> List[Tuple[int, str, str]]:
    """Return ``(version, name, domain)`` for every migration declared in
    source, across all domains, in canonical order.

    Preserves the exact shape ``Core.doctor`` consumed as
    ``_expected_migrations()`` prior to Activation 1.3.
    """
    return [(migration.version, migration.name, domain) for migration, domain in all_migrations()]