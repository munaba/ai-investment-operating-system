"""Production migration for the ``order_idempotency_keys`` table
(Activation 3.2 -- pre-trade validation).

Backs the "duplicate request/idempotency" pre-trade gate in
``Business.paper_trading_engine.PaperTradingEngine.submit_order``: a
row here means a given caller-supplied ``idempotency_key`` has already
been used to successfully submit and execute a paper order, so a
retried/duplicate request carrying the same key is rejected before any
new ``Order``/``Trade`` row is created (see that class's docstring for
the exact point in the flow this row is written).

``idempotency_key`` is the primary key (not a surrogate integer,
mirroring ``accounts.account_id`` -- see ``Database.models.
OrderIdempotencyKey`` for the full rationale). ``account_id``,
``order_id`` (``orders.order_id``), and ``trade_id`` (``trades.
trade_id``) all carry ``REFERENCES`` foreign keys -- this project's
``SQLiteDatabase`` enables ``PRAGMA foreign_keys = ON`` by default
(see ``Database.database_config.DatabaseConfig.foreign_keys``), so
these are enforced, not decorative.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` and every
other domain migration file, mirroring the established one-file-per-
domain pattern (``migrations_accounts``, ``migrations_positions``,
``migrations_orders``, ``migrations_trades``, ``migrations_snapshots``,
``migrations_watchlist``).

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* -- same scope decision as every other domain (no automatic
migration run at startup). A caller passes ``IDEMPOTENCY_MIGRATIONS``
to ``MigrationRunner(database).apply(IDEMPOTENCY_MIGRATIONS)``
explicitly -- see ``run_idempotency_migrations.py``. It IS wired into
``Database.migration_registry.MIGRATION_MODULES`` so ``python main.py
init``/``doctor`` picks it up automatically, same as every other
already-registered domain.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders, 5 = trades,
#   10 = ranking_snapshots, 11 = ranking_snapshots (Activation 2.7
#   extension), 12 = order_idempotency_keys (this file, Activation 3.2)
#   -- first free slot after 1-11, confirmed by grepping every
#   Database/migrations_*.py `version=` literal before choosing it.
IDEMPOTENCY_MIGRATIONS = (
    Migration(
        version=12,
        name="create_order_idempotency_keys_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS order_idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                account_id      TEXT NOT NULL REFERENCES accounts(account_id),
                order_id        INTEGER NOT NULL REFERENCES orders(order_id),
                trade_id        INTEGER NOT NULL REFERENCES trades(trade_id),
                created_at      TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_order_idempotency_keys_account_id
            ON order_idempotency_keys (account_id)
            """,
        ],
    ),
)
