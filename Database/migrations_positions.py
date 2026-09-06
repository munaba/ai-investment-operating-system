"""Production migration for the ``positions`` table (Sprint 4 STEP 2).

Persistence only -- see ``Repository.persistence.position_repository.
PositionRepository`` docstring for the full scope boundary (no
average-price/merge/realized-P&L business logic here or there; this
STEP only stores whatever state a caller supplies).

``position_id`` is a surrogate ``INTEGER PRIMARY KEY AUTOINCREMENT``,
unlike ``accounts.account_id``: a position's natural key
(``account_id`` + ``symbol``) is not stable across its lifecycle --
NO POSITION -> OPEN -> ... -> CLOSED -> (possibly) a fresh OPEN again
on a later BUY -- so it cannot be the primary key. A closed position's
row must remain distinct from a later reopened one. See
``Database.models.Position`` for the full rationale.

``account_id`` carries a ``REFERENCES accounts(account_id)`` foreign
key -- this project's ``SQLiteDatabase`` enables
``PRAGMA foreign_keys = ON`` by default (see
``Database.database_config.DatabaseConfig.foreign_keys``), so this is
enforced, not decorative. A position can never point at a
non-existent account.

``status`` is constrained via SQL ``CHECK``, generated from
``Database.position_constants.POSITION_STATUSES`` -- the same single
source of truth ``Repository.persistence.position_repository.
PositionRepository`` reads for its own Python-level validation,
mirroring the ``mode``/``asset_class`` pattern in
``Database.migrations_accounts``.

An index on ``(account_id, symbol, status)`` is included because
looking up "the open position for this account+symbol" is the one
query every later Sprint 4 STEP (merge-on-buy, reduce-on-sell) will
need immediately -- this is a structural index, not business logic.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from
``Database.migrations_accounts``/``Database.migrations_watchlist``
(different, already-applied versions), mirroring the same pattern.

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* (same scope decision as accounts/watchlist: no automatic
migration run at startup). A caller passes ``POSITIONS_MIGRATIONS`` to
``MigrationRunner(database).apply(POSITIONS_MIGRATIONS)`` explicitly --
see ``run_position_migrations.py``.
"""

from __future__ import annotations

from .migrations import Migration
from .position_constants import POSITION_DIRECTIONS, POSITION_STATUSES


def _sql_in_list(values: "tuple[str, ...]") -> str:
    """Render ``values`` as a SQL ``IN (...)`` literal list, e.g. ('open', 'closed').

    ``values`` are always literal Python tuples defined in
    ``Database.position_constants``, never external/user input -- this
    is schema-definition code, not a query builder, so there is no SQL
    injection surface here. Mirrors ``Database.migrations_accounts.
    _sql_in_list``.
    """
    return ", ".join(f"'{v}'" for v in values)


# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions (this file),
#   4 = orders, 5 = trades, 6 = analysis_snapshots,
#   7 = recommendations, 8 = portfolio_snapshots, 9 = daily_performance,
#   10 = ranking_snapshots, 11 = ranking_snapshots extension,
#   12 = order_idempotency_keys, 13 = orders.filled_at,
#   14 = positions.stop_loss/take_profit (this file, Activation 3.8
#   STEP 2), 15/16 = order_approvals/other tables, 17 =
#   positions.buy_fee_accumulated (this file, net-performance-after-
#   fee -- see below), 18 = positions.direction (this file, Activation
#   11.11 -- see below).
POSITIONS_MIGRATIONS = (
    Migration(
        version=3,
        name="create_positions_table",
        up_statements=[
            f"""
            CREATE TABLE IF NOT EXISTS positions (
                position_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id      TEXT NOT NULL REFERENCES accounts(account_id),
                symbol          TEXT NOT NULL,
                quantity        REAL NOT NULL,
                average_price   REAL NOT NULL,
                realized_pnl    REAL NOT NULL,
                status          TEXT NOT NULL CHECK (
                                    status IN ({_sql_in_list(POSITION_STATUSES)})
                                ),
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_positions_account_symbol_status
            ON positions (account_id, symbol, status)
            """,
        ],
    ),
    # version=14 (Activation 3.8 STEP 2, additive): adds the
    # ``stop_loss``/``take_profit`` columns the roadmap contract
    # requires ("Stop loss dan take profit disimpan pada position/order
    # strategy") -- the STEP 1 audit found neither existed anywhere in
    # the schema/dataclass, and LOCKED the owner as ``Position`` (not
    # ``Order``, not a new ``Strategy`` entity). Plain ``ALTER TABLE
    # ... ADD COLUMN`` is sufficient here, exactly like
    # ``Database.migrations_orders`` version=13's ``filled_at`` column
    # (both new columns are simply nullable, with no NOT NULL/CHECK/
    # DEFAULT expression referencing existing data), unlike
    # ``migrations_snapshots`` version=11's rebuild-in-place.
    #
    # ``stop_loss REAL NULL`` / ``take_profit REAL NULL`` -- both
    # deliberately nullable, unlike this table's other numeric columns
    # (``quantity``/``average_price``/``realized_pnl``, all
    # ``REAL NOT NULL`` per ``Database.models.Position``'s documented
    # all-NOT-NULL numeric style). There is no sentinel float that
    # honestly means "no stop loss/take profit configured" the way
    # ``0.0`` reads for ``Order.filled_quantity``'s "nothing filled
    # yet" -- ``NULL`` is the correct representation, mirroring
    # ``Database.migrations_orders`` version=13's ``filled_at``
    # reasoning. Every pre-existing row (all created before this
    # column existed) backfills to ``NULL`` automatically under
    # SQLite's ``ADD COLUMN`` semantics -- exactly correct, since this
    # STEP does not retroactively infer stop-loss/take-profit levels
    # for positions opened before this column existed.
    #
    # No SQL CHECK constraint is added for these columns: the LONG
    # reference-price rule (``stop_loss`` below entry, ``take_profit``
    # above entry) needs ``average_price`` on the *same row* to
    # evaluate, which a column-level ``CHECK`` cannot reference
    # relationally in SQLite in a way that also tolerates ``NULL``
    # cleanly -- that validation is Python-level business logic in
    # ``Business.position_manager.PositionManager.
    # set_stop_loss_take_profit``, not a schema constraint, mirroring
    # this project's existing status/mode/asset_class-only use of SQL
    # CHECK (domain-membership checks only, never cross-column
    # comparisons).
    Migration(
        version=14,
        name="add_positions_stop_loss_take_profit_columns",
        up_statements=[
            "ALTER TABLE positions ADD COLUMN stop_loss REAL NULL",
            "ALTER TABLE positions ADD COLUMN take_profit REAL NULL",
        ],
    ),
    # version=17 (net-performance-after-fee, additive): adds the
    # ``buy_fee_accumulated`` column tracking BUY-side ``Trade.fee``
    # not yet realized against a SELL (see ``Database.models.
    # Position`` for the full field rationale, and
    # ``Business.position_manager.PositionManager`` for how it is
    # written). ``REAL NOT NULL DEFAULT 0.0`` -- unlike
    # ``stop_loss``/``take_profit``, this mirrors ``quantity``/
    # ``average_price``/``realized_pnl``'s all-NOT-NULL numeric style:
    # ``0.0`` honestly means "no unrealized BUY fee", which is exactly
    # correct for every pre-existing row (all created before this
    # column existed, none of which can retroactively know their
    # historical BUY fees) under SQLite's ``ADD COLUMN ...
    # DEFAULT ...`` backfill semantics.
    Migration(
        version=17,
        name="add_positions_buy_fee_accumulated_column",
        up_statements=[
            "ALTER TABLE positions ADD COLUMN buy_fee_accumulated REAL NOT NULL DEFAULT 0.0",
        ],
    ),
    # version=18 (Activation 11.11, additive, persistence groundwork
    # only): adds the ``direction`` column locked by Activation 11.10
    # Decision B/K -- the ONE schema change that decision record
    # identified as necessary to eventually represent a Forex SHORT
    # position without overloading ``quantity`` (which stays an
    # unsigned magnitude everywhere, including for this column's own
    # existing non-Forex rows).
    #
    # ``direction TEXT NOT NULL DEFAULT 'LONG' CHECK (...)`` --
    # mirrors ``buy_fee_accumulated``'s all-NOT-NULL, DEFAULT-backed
    # style (not ``stop_loss``/``take_profit``'s nullable style):
    # every position, past or future, unambiguously has a direction --
    # there is no honest "no direction configured" NULL state the way
    # there is for an optional stop-loss level. Every pre-existing row
    # (all created before this column existed, all of them LONG-only
    # under the codebase's prior long-only behavior -- see Activation
    # 11.10's audit of ``PositionManager``) backfills to ``'LONG'``
    # automatically under SQLite's ``ADD COLUMN ... DEFAULT ...``
    # semantics, which is exactly correct: it is not a guess, it is
    # the only direction any position could have had before this
    # column existed.
    #
    # The CHECK constraint is generated from ``POSITION_DIRECTIONS``
    # (``Database.position_constants``), the same single-source-of-
    # truth pattern ``status``'s CHECK already uses -- confirmed
    # supported by SQLite's ``ALTER TABLE ADD COLUMN`` (unlike a
    # cross-column CHECK such as the LONG/SHORT stop-loss rule, a
    # domain-membership CHECK like this one needs no other column on
    # the row and is fully expressible here, mirroring ``status``'s
    # own CHECK rather than ``stop_loss``/``take_profit``'s
    # Python-only validation).
    #
    # This migration does NOT touch ``quantity``/``average_price``/
    # ``realized_pnl``/``status``/``stop_loss``/``take_profit``/
    # ``buy_fee_accumulated`` -- every other column is untouched, per
    # Activation 11.11's HARD SCOPE LIMIT.
    Migration(
        version=18,
        name="add_positions_direction_column",
        up_statements=[
            "ALTER TABLE positions ADD COLUMN direction TEXT NOT NULL DEFAULT 'LONG' "
            f"CHECK (direction IN ({_sql_in_list(POSITION_DIRECTIONS)}))",
        ],
    ),
)