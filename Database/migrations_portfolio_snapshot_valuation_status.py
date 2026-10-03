"""Additive migration extending ``portfolio_snapshots`` with a
``valuation_status`` column (Phase G, Task 3 -- "Valuation Freshness +
Paper Review Inputs").

Version=29 (LOCKED DECISION): the next free slot after
``Database.migrations_valuation_observations`` version=28, per the
same "grep every ``Database/migrations_*.py`` ``version=`` literal
before choosing it" convention every prior domain migration documents.

Purpose: a paper portfolio review must be able to tell, at the
portfolio level and not just per-position, whether the snapshot it is
looking at was composed entirely from genuinely fresh market prices,
or whether one or more of its open positions had to fall back to a
retained last-good (stale) observation
(``Business.unrealized_pnl_engine.UnrealizedPnLEngine``'s Phase G Task
3 addition). ``valuation_status`` is that one summary label.

``valuation_status`` is ``TEXT NULL``, not ``TEXT NOT NULL``: a
``PortfolioSnapshot`` composed with freshness tracking disabled (the
pre-Phase-G-Task-3, still-default ``UnrealizedPnLEngine`` behavior --
see that module's docstring) never sets this column, exactly mirroring
why ``exposure`` is nullable (``Database.migrations_portfolio_
snapshots``: a field that is not always computable is never defaulted
to a fabricated value). Every pre-existing row is unaffected --
``ALTER TABLE ... ADD COLUMN`` with no default leaves existing rows'
``valuation_status`` as ``NULL``.

Kept in its own file rather than edited into
``Database.migrations_portfolio_snapshots`` (version=8, already
applied in production per that file's own "LOCKED DECISION" framing)
-- an ``ALTER TABLE`` against an already-applied ``CREATE TABLE``
migration is the established additive-column pattern this codebase
already uses (see e.g. ``Database.migrations_orders`` version=13/15
adding columns on top of version=4's original ``CREATE TABLE``, in
their own separate ``Migration`` entries within the same file). This
column lives in a dedicated new migration file instead of being added
into ``migrations_portfolio_snapshots.py`` itself, since Phase G's
"do not modify Phase A-F" instruction covers that already-complete
file; a new, additive-only migration file reaches the same schema
result without editing anything already shipped.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table):
#   ... 27 = brief_approvals, 28 = valuation_observations -- 29 is the
#   first free slot after 1-28, confirmed by grepping every
#   Database/migrations_*.py `version=` literal before choosing it.
PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS = (
    Migration(
        version=29,
        name="add_valuation_status_to_portfolio_snapshots",
        up_statements=[
            "ALTER TABLE portfolio_snapshots ADD COLUMN valuation_status TEXT NULL",
        ],
    ),
)
