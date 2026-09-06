"""Production migration for the ``order_approvals`` table
(Activation 7 -- Blocker #4: persist ``user_approval`` so it is
auditable from the database).

Backs the audit-trail requirement raised against
``Business.paper_trading_engine.PaperTradingEngine.submit_order``:
gate 3 ("user approval tersedia") already REQUIRES the caller to pass
``user_approval=True`` before any ``Order``/``Trade`` is created (see
that class's module docstring -- this migration does not touch that
gate, its LOCKED order, or its rejection behaviour in any way). What
was missing is a durable, queryable record that the approval which
gated a given ``Order``/``Trade`` actually happened -- today that fact
only ever existed transiently as a Python function argument. This
table is that record.

Deliberately minimal -- only what genuinely exists in the production
flow at the point this row is written (see
``Repository.persistence.order_approval_repository.
OrderApprovalRepository.create()`` and
``PaperTradingEngine.submit_order()`` for the exact call site):

* ``approved`` -- the ``user_approval`` value gate 3 already checked
  (always ``True`` by the time this row is written, since gate 3
  raises ``ValidationError`` on anything else and no row is written
  for a rejected order -- see module docstring below). Stored rather
  than hard-coded so the table's own data, not application code, is
  the source of truth for what was approved.
* ``recorded_at`` -- this row's own write timestamp (server-side,
  ``datetime.now(timezone.utc).isoformat()``), mirroring
  ``order_idempotency_keys.created_at``
  (``Database.migrations_idempotency``) exactly. This is NOT an
  "approval was granted at ..." timestamp -- no such timestamp is
  ever supplied by any caller in this codebase (``submit_order()``
  takes no approval-time parameter), and inventing one would be
  fabricating data the production flow does not have. What this
  column truthfully records is when the audit row itself was
  persisted, which -- because it is written after the trade's state
  is already fully committed (see the repository/engine docstrings) --
  is always at or after the real approval-gated commit.
* ``order_id``/``trade_id``/``account_id`` -- linkage to the exact
  ``Order``/``Trade``/``Account`` this approval gated, all with
  ``REFERENCES`` foreign keys (this project's ``SQLiteDatabase``
  enables ``PRAGMA foreign_keys = ON`` by default -- see
  ``Database.database_config.DatabaseConfig.foreign_keys`` -- so these
  are enforced, not decorative).

No user identity field of any kind (no ``approved_by``, no user id,
no session/actor reference): the brief is explicit that no identity
may be invented, and audit-before-unifying found no existing,
already-authenticated caller-identity concept anywhere in this
codebase's production trading flow for this table to truthfully
reference (``submit_order()`` itself takes no such parameter). Adding
one would be fabrication, not persistence of "informasi yang benar-
benar tersedia dari production flow".

``order_id`` is the primary key (not a surrogate autoincrement
integer): gate 3 runs once per ``submit_order()`` call and, by the
time a row here can be written at all, has already produced exactly
one ``Order``. One order therefore has at most one approval record,
so ``order_id`` is both the natural and the unique key -- mirroring
``order_idempotency_keys.idempotency_key`` being the natural primary
key of that table rather than a surrogate integer.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` and every
other domain migration file, mirroring the established one-file-per-
domain pattern (``migrations_accounts``, ``migrations_orders``,
``migrations_trades``, ``migrations_idempotency``,
``migrations_portfolio_snapshots``).

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* -- same scope decision as every other domain (no automatic
migration run at startup). It IS wired into
``Database.migration_registry.MIGRATION_MODULES`` so ``python main.py
init``/``doctor`` picks it up automatically, same as every other
already-registered domain.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders, 5 = trades,
#   8 = portfolio_snapshots, 9 = daily_performance, 10/11 =
#   ranking_snapshots, 12 = order_idempotency_keys, 15 = orders
#   (analysis_snapshot_id extension) -- 16 is the first free slot after
#   1-15, confirmed by grepping every Database/migrations_*.py
#   `version=` literal before choosing it.
ORDER_APPROVALS_MIGRATIONS = (
    Migration(
        version=16,
        name="create_order_approvals_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS order_approvals (
                order_id     INTEGER PRIMARY KEY REFERENCES orders(order_id),
                trade_id     INTEGER NOT NULL REFERENCES trades(trade_id),
                account_id   TEXT NOT NULL REFERENCES accounts(account_id),
                approved     INTEGER NOT NULL,
                recorded_at  TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_order_approvals_account_id
            ON order_approvals (account_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_order_approvals_trade_id
            ON order_approvals (trade_id)
            """,
        ],
    ),
)