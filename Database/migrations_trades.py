"""Production migration for the ``trades`` table (Sprint 4 STEP 4).

Persistence only -- see ``Repository.persistence.trade_repository.
TradeRepository`` docstring for the full scope boundary (no
execution/fill-decision/average-price/fee-calculation/tax-calculation/
merge/portfolio business logic here or there; this STEP only stores
whatever state a caller supplies).

``trade_id`` is a surrogate ``INTEGER PRIMARY KEY AUTOINCREMENT``,
mirroring ``positions.position_id``/``orders.order_id`` rather than
``accounts.account_id``: a trade has no stable natural key -- an
order can produce more than one trade (partial fills), so
``order_id`` + ``account_id`` + ``symbol`` can repeat across many
distinct trades over time. See ``Database.models.Trade`` for the full
rationale.

``account_id`` carries a ``REFERENCES accounts(account_id)`` foreign
key, and ``order_id`` carries a ``REFERENCES orders(order_id)``
foreign key -- this project's ``SQLiteDatabase`` enables
``PRAGMA foreign_keys = ON`` by default (see
``Database.database_config.DatabaseConfig.foreign_keys``), so both
are enforced, not decorative. A trade can never point at a
non-existent account or a non-existent order, mirroring the FK
pattern already established by ``Database.migrations_orders``/
``Database.migrations_positions``.

``action`` is intentionally left as a plain ``TEXT NOT NULL`` with no
``CHECK`` constraint, mirroring ``orders.action`` -- see
``Database.migrations_orders`` module docstring for the identical
reasoning: constraining ``action`` was never part of this STEP's
locked scope, and inventing that constraint now would be exactly the
kind of unrequested design decision this STEP is meant to avoid.
There is accordingly no ``Database.trade_constants`` module: unlike
``Order``/``Position``, ``Trade`` has no ``status`` (or any other)
domain field that needs a single source of truth for a SQL ``CHECK``
+ Python-level validation pair -- introducing one speculatively would
itself be an unrequested design decision.

``executed_at`` has no ``DEFAULT`` and is not auto-populated by this
migration or by ``TradeRepository`` -- it is a required, caller-
supplied business fact (when the trade executed), not a persistence-
lifecycle timestamp. See ``Database.models.Trade`` for the full
rationale.

Two indexes are included, both structural (not business logic),
mirroring the exact reasoning behind
``idx_orders_account_status``/``idx_orders_account_created_at``:

* ``(account_id)`` -- supports ``list_by_account``, the one query
  every later Sprint 4 STEP (trade history, portfolio valuation) will
  need immediately: "every trade for this account".
* ``(order_id)`` -- supports ``list_by_order``: "every trade (partial
  fill) produced by this order".

No compound/covering index (e.g. including ``executed_at``) is added:
``TradeRepository.list_by_account``/``list_by_order`` order by
``trade_id`` ascending (the surrogate key, i.e. insertion/rowid
order) exactly like ``OrderRepository.list_by_account`` orders by
``order_id`` ascending -- there is no separate ``executed_at``-based
ordering requirement in this STEP's locked scope to justify a wider
index.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from
``Database.migrations_accounts``/``Database.migrations_watchlist``/
``Database.migrations_positions``/``Database.migrations_orders``
(different, already-applied versions), mirroring the same pattern.

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* (same scope decision as accounts/watchlist/positions/
orders): no automatic migration run at startup. A caller passes
``TRADES_MIGRATIONS`` to ``MigrationRunner(database).apply(
TRADES_MIGRATIONS)`` explicitly -- see ``run_trade_migrations.py``.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders,
#   5 = trades (this file), 6 = analysis_snapshots,
#   7 = recommendations, 8 = portfolio_snapshots, 9 = daily_performance
TRADES_MIGRATIONS = (
    Migration(
        version=5,
        name="create_trades_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id             INTEGER NOT NULL REFERENCES orders(order_id),
                account_id           TEXT NOT NULL REFERENCES accounts(account_id),
                symbol               TEXT NOT NULL,
                action               TEXT NOT NULL,
                quantity             REAL NOT NULL,
                fill_price           REAL NOT NULL,
                fee                  REAL NOT NULL,
                tax                  REAL NOT NULL,
                executed_at          TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trades_account_id
            ON trades (account_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trades_order_id
            ON trades (order_id)
            """,
        ],
    ),
)