"""Production migration for the ``portfolio_snapshots`` table
(Activation 5.2 -- Portfolio Snapshots).

Persistence only -- see ``Repository.persistence.
portfolio_snapshot_repository.PortfolioSnapshotRepository`` docstring
for the full scope boundary (no order/trade creation, no mutation of
``Account``/``Position``, no ``PaperTradingEngine`` involvement; this
Activation only stores an already-composed, already-computed snapshot
of portfolio state).

``snapshot_id`` is a surrogate ``INTEGER PRIMARY KEY AUTOINCREMENT``,
mirroring ``trades.trade_id``/``positions.position_id``/
``orders.order_id``/``ranking_snapshots.snapshot_id`` rather than
``accounts.account_id``: a portfolio snapshot has no stable natural
key of its own -- the same ``account_id`` reappears across many
distinct snapshots taken over time.

Version=8 (LOCKED DECISION): version=8 was reserved for exactly this
table, ``portfolio_snapshots``, since ``Database.migrations_accounts``
first documented the global version allocation (see that module's
"Migration version allocation" comment: "8 = portfolio_snapshots").
Versions 6, 7, and 9 (``analysis_snapshots``/``recommendations``/
``daily_performance``) remain reserved and untouched by this file --
they belong to a different, not-yet-implemented ERD schema and are
not this Activation's concern. This is therefore the correct,
already-reserved slot -- no new allocation decision was made here.

Table name is ``portfolio_snapshots`` -- exactly the name already
reserved for version=8, and distinct from the unrelated
``ranking_snapshots`` table (version=10/11, a per-symbol scan-run
record) and the unrelated Sprint 2 AutonomousHost snapshot/restore
concept.

``account_id`` carries a ``REFERENCES accounts(account_id)`` foreign
key, mirroring ``positions.account_id``/``orders.account_id``/
``trades.account_id``: a portfolio snapshot only has meaning relative
to the account whose cash/positions it captured. This is the one
field beyond the roadmap's explicit 8-field list added to this table,
and it is added because every quantity in a snapshot row (``cash``,
``market_value``, ``equity``, ``realized_pnl``, ``unrealized_pnl``) is
scoped to a specific ``Account`` -- without it, a snapshot row would
be ambiguous the moment more than one account exists, exactly the
same reasoning already applied to ``positions``/``orders``/``trades``.

``exposure`` is ``REAL NULL`` (nullable, no default), not
``REAL NOT NULL``: the Activation 5.2 audit found no existing,
already-computed source in the codebase for total-portfolio exposure
(``Orchestration.portfolio_engine.PortfolioEngine.exposure`` is a
different, per-signal/per-decision concept -- a pass-through of a
hypothetical execution's ``position_size``, not a measurement of the
real, current portfolio's exposure -- and is not reused here). Per
the Activation 5.2 roadmap's explicit "jangan mengarang nilainya...
laporkan field tersebut sebagai NOT VERIFIABLE / GAP" instruction,
this column exists (the roadmap requires the field to be persisted)
but ``Business.portfolio_snapshot_service.PortfolioSnapshotService``
never writes a fabricated value into it -- every row's ``exposure``
is ``NULL`` until a future Activation identifies (or builds, out of
this Activation's scope) a real source for it.

Immutable / append-only (LOCKED design decision, mirrors ``trades``/
``ranking_snapshots``): no ``update``/``delete`` statement or index
supports mutation here -- see ``PortfolioSnapshotRepository`` for the
enforced absence of any update/delete method.

Two indexes, both structural (not business logic), mirroring the
exact reasoning behind ``idx_ranking_snapshots_scan_time``/
``idx_ranking_snapshots_symbol``:

* ``(account_id, snapshot_id)`` -- supports "every snapshot for this
  account, in chronological/insertion order", the query
  ``PortfolioSnapshotRepository.list_by_account``/the equity-curve
  read ``Business.portfolio_snapshot_service.PortfolioSnapshotService``
  needs to compute ``drawdown`` via the existing
  ``Business.maximum_drawdown_engine.MaximumDrawdownEngine``.
* ``(timestamp)`` -- supports a future "snapshots around this time"
  query; cheap to add now, mirrors ``idx_ranking_snapshots_scan_time``.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from every
other ``Database.migrations_*`` module (different, already-applied or
separately-reserved versions), mirroring the same pattern.

Registered in ``Database.migration_registry.MIGRATION_MODULES``
(Activation 7, BLOCKER #1): that registry feeds both
``python main.py init`` and ``Core.doctor``, so ``portfolio_snapshots``
is now created automatically by ``init`` and reported on by ``doctor``
like every other domain, instead of being reachable only via the
standalone ``run_portfolio_snapshot_migrations.py`` script.
``Tests.test_doctor_command._apply_all_migrations`` and its "all N
applied" bookkeeping were updated in the same change (7 -> 8 domains)
per the Activation 1.3 rule that registry changes and their dependent
test bookkeeping move together.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders, 5 = trades,
#   6 = analysis_snapshots (reserved, not yet implemented),
#   7 = recommendations (reserved, not yet implemented),
#   8 = portfolio_snapshots (THIS FILE, Activation 5.2),
#   9 = daily_performance (reserved, not yet implemented),
#   10/11 = ranking_snapshots (Database.migrations_snapshots, a
#   different table -- see that module's docstring).
PORTFOLIO_SNAPSHOTS_MIGRATIONS = (
    Migration(
        version=8,
        name="create_portfolio_snapshots_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id      TEXT NOT NULL REFERENCES accounts(account_id),
                cash            REAL NOT NULL,
                market_value    REAL NOT NULL,
                equity          REAL NOT NULL,
                realized_pnl    REAL NOT NULL,
                unrealized_pnl  REAL NOT NULL,
                exposure        REAL NULL,
                drawdown        REAL NOT NULL,
                timestamp       TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_account_snapshot
            ON portfolio_snapshots (account_id, snapshot_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_timestamp
            ON portfolio_snapshots (timestamp)
            """,
        ],
    ),
)