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
#: Every ``Database/migrations_<domain>.py`` module must be listed here
#: (enforced by Tests/test_migration_registry_complete.py); otherwise
#: ``python main.py init`` silently skips its tables and ``doctor``
#: reports READY without checking them. See each module's own "Migration
#: version allocation" comment for its reserved version numbers.
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
    ("daily_performance", "Database.migrations_daily_performance", "DAILY_PERFORMANCE_MIGRATIONS"),
    ("decision_briefs", "Database.migrations_decision_briefs", "DECISION_BRIEFS_MIGRATIONS"),
    ("risk_ledger", "Database.migrations_risk_ledger", "RISK_LEDGER_MIGRATIONS"),
    ("scheduler", "Database.migrations_scheduler", "SCHEDULER_MIGRATIONS"),
    ("telegram_control", "Database.migrations_telegram_control", "TELEGRAM_CONTROL_MIGRATIONS"),
    ("brief_approvals", "Database.migrations_brief_approvals", "BRIEF_APPROVALS_MIGRATIONS"),
    ("valuation_observations", "Database.migrations_valuation_observations", "VALUATION_OBSERVATIONS_MIGRATIONS"),
    (
        "portfolio_snapshot_valuation_status",
        "Database.migrations_portfolio_snapshot_valuation_status",
        "PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS",
    ),
    ("observation_window", "Database.migrations_observation_window", "OBSERVATION_WINDOW_MIGRATIONS"),
    ("sustained_use_final_review", "Database.migrations_sustained_use_final_review", "SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS"),
    ("llm_output_audit", "Database.migrations_llm_output_audit", "LLM_OUTPUT_AUDIT_MIGRATIONS"),
    ("v2_rankings", "Database.migrations_v2_rankings", "V2_RANKINGS_MIGRATIONS"),
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