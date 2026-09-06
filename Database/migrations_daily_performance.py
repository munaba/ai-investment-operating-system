"""Production migration for the ``daily_performance`` table
(Activation 5.3 -- Daily Performance).

Persistence only -- see ``Repository.persistence.
daily_performance_repository.DailyPerformanceRepository`` docstring
for the full scope boundary (no order/trade creation, no mutation of
``Account``/``Position``/``PortfolioSnapshot``, no
``PaperTradingEngine`` involvement; this Activation only stores an
already-composed, already-computed daily-performance summary for a
caller-supplied period).

``daily_performance_id`` is a surrogate ``INTEGER PRIMARY KEY
AUTOINCREMENT``, mirroring ``portfolio_snapshots.snapshot_id``/
``trades.trade_id``/``positions.position_id``/``orders.order_id``
rather than ``accounts.account_id``: a daily performance row has no
stable natural key of its own -- the same ``account_id`` reappears
across many distinct periods summarized over time.

Version=9 (LOCKED DECISION): version=9 was reserved for exactly this
table, ``daily_performance``, since ``Database.migrations_accounts``
first documented the global version allocation (see that module's
"Migration version allocation" comment: "9 = daily_performance"; also
confirmed in ``Database.migrations_portfolio_snapshots``, which
reserved 8 for itself and left 9 untouched). Versions 6 and 7
(``analysis_snapshots``/``recommendations``) remain reserved and
untouched by this file -- they belong to a different, not-yet-
implemented ERD schema and are not this Activation's concern. This is
therefore the correct, already-reserved slot -- no new allocation
decision was made here.

Table name is ``daily_performance`` -- exactly the name already
reserved for version=9, and distinct from the unrelated
``portfolio_snapshots``/``ranking_snapshots`` tables.

``account_id`` carries a ``REFERENCES accounts(account_id)`` foreign
key, mirroring ``portfolio_snapshots.account_id``/
``positions.account_id``/``orders.account_id``/``trades.account_id``:
a daily performance row only has meaning relative to the account whose
trading activity/equity it summarizes.

``start_timestamp``/``end_timestamp`` are ``TEXT NOT NULL``: the
caller-supplied ISO-8601 boundaries of the period this row summarizes
(see ``Business.daily_performance_service.DailyPerformanceService`` --
this service never decides the period itself).

``starting_equity``/``ending_equity`` are ``REAL NULL`` (nullable, no
default), not ``REAL NOT NULL``: both depend entirely on a qualifying
``PortfolioSnapshot`` row existing at/before the relevant boundary. If
``Business.portfolio_snapshot_service.PortfolioSnapshotService.
take_snapshot()`` was never called in the relevant range, both fields
are legitimately ``NULL`` -- exactly the same "never fabricate,
persist NULL instead" rule already applied to ``portfolio_snapshots.
exposure``.

``number_of_signals`` is ``INTEGER NULL`` (nullable, no default): the
Activation 5.3 audit found no ``Signal`` entity anywhere in the
codebase, and ``RankingSnapshot`` is a different, per-symbol scan-run
record that does not qualify as a substitute. Per the same
"never fabricate -- persist NULL and report the field as NOT
VERIFIABLE / GAP" rule already applied to ``portfolio_snapshots.
exposure``, this column exists (the roadmap requires the field to be
persisted) but ``DailyPerformanceService`` never writes a fabricated
value into it -- every row's ``number_of_signals`` is ``NULL`` until a
future Activation identifies (or builds, out of this Activation's
scope) a real ``Signal`` source.

``realized_result``/``unrealized_result``/``fees``/``tax``/
``net_result``/``drawdown``/``number_of_executions`` are all
``NOT NULL``: every one of these is always computable from
already-real, already-persisted sources (see
``DailyPerformanceService`` for exactly how each is derived) --
none of them has a legitimate "no source yet" case the way
``starting_equity``/``ending_equity``/``number_of_signals`` do.

Immutable / append-only (LOCKED design decision, mirrors
``portfolio_snapshots``/``trades``): no ``update``/``delete``
statement or index supports mutation here -- see
``DailyPerformanceRepository`` for the enforced absence of any
update/delete method.

Two indexes, both structural (not business logic), mirroring the
exact reasoning behind ``idx_portfolio_snapshots_account_snapshot``/
``idx_portfolio_snapshots_timestamp``:

* ``(account_id, daily_performance_id)`` -- supports "every daily
  performance row for this account, in chronological/insertion
  order", the query ``DailyPerformanceRepository.list_by_account``
  needs.
* ``(start_timestamp, end_timestamp)`` -- supports a future "which
  period(s) cover this date" query; cheap to add now, mirrors
  ``idx_portfolio_snapshots_timestamp``.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from every
other ``Database.migrations_*`` module (different, already-applied or
separately-reserved versions), mirroring the same pattern.

Deliberately NOT added to ``Database.migration_registry.
MIGRATION_MODULES`` (LOCKED SCOPE DECISION for this Activation,
identical reasoning to ``Database.migrations_portfolio_snapshots``):
that registry feeds both ``python main.py init`` and ``Core.doctor``,
and ``Tests.test_doctor_command._apply_all_migrations`` currently
applies an explicit, hardcoded list of exactly 7 domains and asserts
doctor reports "Migrations section is READY once all 7 are applied".
Adding an 8th/9th registered domain here without also touching that
test file would make that already-passing regression test fail --
and this Activation's own rules forbid changing behavior/tests
outside its own roadmap scope. This migration therefore stays
reachable only via the explicit, standalone
``run_daily_performance_migrations.py`` script, exactly mirroring how
``run_portfolio_snapshot_migrations.py`` works today -- no automatic
migration run at startup, no composition-root wiring, no change to
``python main.py init``'s observed domain count. A future Activation
can add the registry entry (and update the doctor test's hardcoded
list in the same change) if that is ever desired; that decision is
explicitly out of this Activation's scope.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders, 5 = trades,
#   6 = analysis_snapshots (reserved, not yet implemented),
#   7 = recommendations (reserved, not yet implemented),
#   8 = portfolio_snapshots (Database.migrations_portfolio_snapshots),
#   9 = daily_performance (THIS FILE, Activation 5.3),
#   10/11 = ranking_snapshots (Database.migrations_snapshots, a
#   different table -- see that module's docstring).
DAILY_PERFORMANCE_MIGRATIONS = (
    Migration(
        version=9,
        name="create_daily_performance_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS daily_performance (
                daily_performance_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id            TEXT NOT NULL REFERENCES accounts(account_id),
                start_timestamp       TEXT NOT NULL,
                end_timestamp         TEXT NOT NULL,
                starting_equity       REAL NULL,
                ending_equity         REAL NULL,
                realized_result       REAL NOT NULL,
                unrealized_result     REAL NOT NULL,
                fees                  REAL NOT NULL,
                tax                   REAL NOT NULL,
                net_result            REAL NOT NULL,
                drawdown              REAL NOT NULL,
                number_of_signals     INTEGER NULL,
                number_of_executions  INTEGER NOT NULL,
                timestamp             TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_daily_performance_account_id
            ON daily_performance (account_id, daily_performance_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_daily_performance_period
            ON daily_performance (start_timestamp, end_timestamp)
            """,
        ],
    ),
)
