"""Production migration for the ``orders`` table (Sprint 4 STEP 3).

Persistence only -- see ``Repository.persistence.order_repository.
OrderRepository`` docstring for the full scope boundary (no
validation/execution/fill/average-price/fee/tax/lot/cash/portfolio
business logic here or there; this STEP only stores whatever state a
caller supplies).

``order_id`` is a surrogate ``INTEGER PRIMARY KEY AUTOINCREMENT``,
mirroring ``positions.position_id`` rather than ``accounts.account_id``:
an order has no stable natural key -- ``account_id`` + ``symbol`` can
repeat across many distinct orders over time -- so it cannot be the
primary key. See ``Database.models.Order`` for the full rationale.

``account_id`` carries a ``REFERENCES accounts(account_id)`` foreign
key -- this project's ``SQLiteDatabase`` enables
``PRAGMA foreign_keys = ON`` by default (see
``Database.database_config.DatabaseConfig.foreign_keys``), so this is
enforced, not decorative. An order can never point at a non-existent
account, mirroring ``Database.migrations_positions``.

``status`` is constrained via SQL ``CHECK``, generated from
``Database.order_constants.ORDER_STATUSES`` -- the same single source
of truth ``Repository.persistence.order_repository.OrderRepository``
reads for its own Python-level validation, mirroring the
``status``/``mode``/``asset_class`` pattern already established by
``Database.migrations_positions``/``Database.migrations_accounts``.

``action`` is intentionally left as a plain ``TEXT NOT NULL`` with no
``CHECK`` constraint. The Sprint 4 STEP 3 scope only asked for a
single source of truth + CHECK for ``status`` -- constraining
``action`` (e.g. to ``BUY``/``SELL``) was never part of this STEP's
locked scope, and inventing that constraint now would be exactly the
kind of unrequested design decision this STEP is meant to avoid. If a
future STEP wants ``action`` constrained, that is a new, explicit
decision for that STEP -- not backfilled here.

``filled_quantity`` is a structural field added per the LOCKED Sprint
4 STEP 3 design decision -- see ``Database.models.Order`` and
``Database.order_constants`` for the full rationale. It is
``REAL NOT NULL DEFAULT 0``, matching every other numeric domain
column in this schema (never nullable).

Two indexes are included, both structural (not business logic):

* ``(account_id, status)`` -- the one query every later Sprint 4 STEP
  (order validation, paper trading execution, trade history) will need
  immediately: "which orders for this account are in state X"),
  mirroring the reasoning behind
  ``idx_positions_account_symbol_status``.
* ``(account_id, created_at)`` -- supports listing an account's orders
  in chronological order without a full table scan, the natural access
  pattern for ``list_by_account``.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from
``Database.migrations_accounts``/``Database.migrations_watchlist``/
``Database.migrations_positions`` (different, already-applied
versions), mirroring the same pattern.

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* (same scope decision as accounts/watchlist/positions): no
automatic migration run at startup. A caller passes
``ORDERS_MIGRATIONS`` to ``MigrationRunner(database).apply(
ORDERS_MIGRATIONS)`` explicitly -- see ``run_order_migrations.py``.
"""

from __future__ import annotations

from .migrations import Migration
from .order_constants import ORDER_STATUSES


def _sql_in_list(values: "tuple[str, ...]") -> str:
    """Render ``values`` as a SQL ``IN (...)`` literal list, e.g. ('NEW', 'VALIDATED').

    ``values`` are always literal Python tuples defined in
    ``Database.order_constants``, never external/user input -- this is
    schema-definition code, not a query builder, so there is no SQL
    injection surface here. Mirrors ``Database.migrations_positions.
    _sql_in_list``/``Database.migrations_accounts._sql_in_list``.
    """
    return ", ".join(f"'{v}'" for v in values)


# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions,
#   4 = orders (this file), 5 = trades, 6 = analysis_snapshots,
#   7 = recommendations, 8 = portfolio_snapshots, 9 = daily_performance,
#   10 = ranking_snapshots, 11 = ranking_snapshots extension,
#   12 = order_idempotency_keys, 13 = orders.filled_at (this file,
#   Activation 3.4 STEP 2 -- see below), 14 = positions.stop_loss/
#   take_profit, 15 = orders.analysis_snapshot_id (this file,
#   Activation 5.1 -- see below).
ORDERS_MIGRATIONS = (
    Migration(
        version=4,
        name="create_orders_table",
        up_statements=[
            f"""
            CREATE TABLE IF NOT EXISTS orders (
                order_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id          TEXT NOT NULL REFERENCES accounts(account_id),
                symbol              TEXT NOT NULL,
                action              TEXT NOT NULL,
                quantity            REAL NOT NULL,
                requested_price     REAL NOT NULL,
                filled_price        REAL NOT NULL,
                filled_quantity     REAL NOT NULL DEFAULT 0,
                status              TEXT NOT NULL CHECK (
                                        status IN ({_sql_in_list(ORDER_STATUSES)})
                                    ),
                reason              TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_orders_account_status
            ON orders (account_id, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_orders_account_created_at
            ON orders (account_id, created_at)
            """,
        ],
    ),
    # version=13 (Activation 3.4 STEP 2, additive): adds the
    # ``filled_at`` column the roadmap contract requires
    # (``Order.filled_at = Trade.executed_at``) and which the
    # Activation 3.4 STEP 1 audit confirmed does not exist anywhere in
    # the schema/dataclass. Plain ``ALTER TABLE ... ADD COLUMN`` is
    # sufficient here (unlike ``migrations_snapshots`` version=11's
    # rebuild-in-place) because the new column is simply nullable, with
    # no NOT NULL/CHECK/DEFAULT expression referencing existing data --
    # SQLite supports that form of ``ADD COLUMN`` directly.
    #
    # ``filled_at TEXT NULL`` -- deliberately nullable, unlike this
    # table's numeric fill fields (``filled_price``/``filled_quantity``,
    # which default to ``0.0``, never ``NULL``, per
    # ``Database.models.Order``'s documented all-NOT-NULL numeric
    # style). ``filled_at`` is not numeric and ``0.0``'s "nothing
    # filled yet" convention has no timestamp equivalent -- there is no
    # sentinel timestamp that means "not filled". ``NULL`` is the
    # correct, honest representation for "this order has not been
    # filled (yet)", and every pre-existing row (all created before
    # this column existed) backfills to ``NULL`` automatically under
    # SQLite's ``ADD COLUMN`` semantics -- exactly correct here, since
    # this STEP does not attempt to retroactively infer a fill time for
    # rows that predate ``ExecutionService`` ever writing this column.
    Migration(
        version=13,
        name="add_orders_filled_at_column",
        up_statements=[
            "ALTER TABLE orders ADD COLUMN filled_at TEXT NULL",
        ],
    ),
    # version=15 (Activation 5.1, additive): adds ``analysis_snapshot_id``,
    # the ONE decision-linkage field the Activation 5.1 STEP 1 audit
    # found a genuine, already-existing, already-production source for:
    # ``Database.models.RankingSnapshot.snapshot_id``. The production
    # CLI path (``main.py`` ``paper buy``/``paper sell``) already looks
    # up the latest ``RankingSnapshot`` for the traded symbol and passes
    # the whole row through to ``PaperTradingEngine.submit_order()`` as
    # ``signal_evidence`` -- this column lets that already-available ID
    # travel with the ``Order`` it backs, instead of being discarded the
    # moment ``submit_order()``'s truthy-check reads it.
    #
    # Plain ``ALTER TABLE ... ADD COLUMN``, nullable, no ``REFERENCES``:
    # mirrors version=13's ``filled_at`` reasoning exactly -- every
    # pre-existing row backfills to ``NULL`` (honest: no snapshot was
    # ever recorded for it), and a ``REFERENCES ranking_snapshots
    # (snapshot_id)`` foreign key is deliberately NOT added, because
    # ``ORDERS_MIGRATIONS`` (version=4/13/15) and ``SNAPSHOTS_MIGRATIONS``
    # (version=10/11) are applied independently by
    # ``Database.migration_registry``/``python main.py init`` -- an
    # environment could legitimately have orders applied without
    # snapshots ever having been applied, and a FK to a possibly-absent
    # table would break that existing independence between domains.
    #
    # The remaining 8 not-yet-available roadmap 5.1 fields
    # (``signal_id``, ``recommendation_id``, ``strategy_name``,
    # ``strategy_version``, ``entry_reason``, ``exit_reason``,
    # ``risk_validation_id``, ``approval_id``) are deliberately NOT
    # added as columns here -- the Activation 5.1 STEP 1 audit found no
    # genuine, already-existing production source for any of them (see
    # ``Docs/ACTIVATION 5/AIOS_Activation5.1_Decision_Linkage_Report.md``
    # for the field-by-field audit). Adding empty/always-NULL columns
    # for them now would be schema invented ahead of a real source and
    # a real design decision -- exactly what the Activation 5.1 STEP 2
    # instructions forbid ("Jangan membuat sumber/arsitektur baru hanya
    # untuk mengisi field tersebut tanpa dasar dari roadmap"). They
    # remain reported as GAP, not fabricated as empty schema.
    Migration(
        version=15,
        name="add_orders_analysis_snapshot_id_column",
        up_statements=[
            "ALTER TABLE orders ADD COLUMN analysis_snapshot_id INTEGER NULL",
        ],
    ),
)