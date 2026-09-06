from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MigrationRecord:
    """One applied-migration entry, mirroring one row of
    ``schema_migrations`` (see :mod:`Database.schema`).

    Attributes:
        version: Sequential migration version number.
        name: Short human-readable name of the migration.
        applied_at: ISO-8601 UTC timestamp of when it was applied.
    """

    version: int
    name: str
    applied_at: str


@dataclass
class DecisionBrief:
    """One row of the ``decision_briefs`` table (see
    ``Database.migrations_decision_briefs.DECISION_BRIEFS_MIGRATIONS``,
    migration version=19).

    Phase B ("Decision Copilot"): a persisted, read-only summary of
    whether a symbol was actionable at the time ``DecisionBriefService``
    ran, and -- only when it genuinely was -- the real risk-managed plan
    behind that call. Mirrors ``RankingSnapshot``/``PortfolioSnapshot``:
    ``brief_id`` is a repository-generated surrogate integer (a symbol
    can have many briefs over time), append-only (no update/delete),
    and every field is sourced from an already-real, already-computed
    place -- this dataclass computes nothing itself.

    ``status`` is one of the eight Phase-B statuses (``SUCCESS``,
    ``NO_TRADE``, ``DATA_STALE``, ``DATA_ERROR``, ``INSUFFICIENT_DATA``,
    ``ANALYSIS_FAILED``, ``RISK_REJECTED``, ``POLICY_BLOCKED``). Only a
    ``SUCCESS`` row may have a plan (``entry_price``/``stop_loss_price``/
    ``take_profit_price``/``position_size``/``risk_reward_ratio``
    non-``None``) -- every other status leaves all five ``None``,
    enforced by ``DecisionBriefService`` before a row is ever built, not
    by this dataclass or its repository.

    ``entry_price``/``stop_loss_price``/``take_profit_price``/
    ``risk_amount``/``position_size``/``risk_reward_ratio`` are the
    verbatim output of the existing, LOCKED ``RiskManagementService``
    (via ``entry_price`` = the real current price
    ``_fetch_current_price``-style lookup already used by
    ``main.py``'s ``recommendation`` command) -- never recomputed,
    never fabricated. ``source_snapshot_id`` points at the exact
    ``RankingSnapshot.snapshot_id`` this brief was derived from.

    Generating a brief never creates a paper order, a ``Trade``, or a
    ``Position`` -- this table has no foreign key to any of those and
    no code path from ``DecisionBriefService`` writes to them.
    """

    brief_id: int
    symbol: str
    generated_at: str
    status: str
    source_snapshot_id: Optional[int] = None
    reason: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    risk_amount: Optional[float] = None
    position_size: Optional[float] = None
    risk_reward_ratio: Optional[float] = None


@dataclass
class Account:
    """One row of the ``accounts`` table (see
    ``Database.migrations_accounts.ACCOUNTS_MIGRATIONS``).

    ``account_id`` is a stable, caller-assigned string identifier
    (e.g. ``"paper-id"``, ``"crypto-main"``) -- deliberately NOT an
    autoincrement integer, so identity survives database export/
    import/restore/cross-device sync.

    Mutable entity: cash/equity/buying_power are updated in place via
    ``AccountRepository.update_balances``, not appended-only.
    """

    account_id: str
    account_name: str
    mode: str
    currency: str
    asset_class: str
    cash: float
    equity: float
    buying_power: float
    created_at: str
    updated_at: str


@dataclass
class Position:
    """One row of the ``positions`` table (see
    ``Database.migrations_positions.POSITIONS_MIGRATIONS``).

    ``position_id`` is a surrogate autoincrement integer, unlike
    ``Account.account_id``: a position's natural key
    (``account_id`` + ``symbol``) is NOT stable across its lifecycle,
    since a position can go OPEN -> ... -> CLOSED and later reopen on
    a fresh BUY, which must become a new row rather than reusing the
    old (closed) one. ``position_id`` is purely a structural
    persistence identifier -- it carries no business meaning.

    Mutable entity: ``quantity``/``average_price``/``realized_pnl``/
    ``status`` are updated in place via ``PositionRepository.update``,
    not appended-only -- mirrors ``Account``/``AccountRepository.
    update_balances``. This STEP persists whatever values a caller
    supplies; it does not compute averaging, merging, or P/L itself
    (that is business logic reserved for a later Sprint 4 STEP).

    ``stop_loss``/``take_profit`` (Activation 3.8 STEP 2, additive):
    both ``Optional[float]``, defaulting to ``None`` (SQL ``NULL``) --
    mirrors ``Order.filled_at``'s nullable style, not the
    ``0.0``-default numeric style ``quantity``/``average_price``/
    ``realized_pnl`` use, because there is no sentinel float that
    honestly means "no stop loss/take profit configured". Persisted
    on ``Position`` (not ``Order``, not a new ``Strategy`` entity --
    LOCKED decisions, see ``Docs/ACTIVATION 3.8`` STEP 1 audit).
    Reference-price validation (LONG: ``stop_loss`` below entry,
    ``take_profit`` above entry) lives in
    ``Business.position_manager.PositionManager.
    set_stop_loss_take_profit``, not here -- this dataclass and its
    repository remain persistence-only.

    ``buy_fee_accumulated`` (net-performance-after-fee, additive):
    running total of BUY ``Trade.fee`` not yet realized against a
    SELL. A BUY (new position or merge) ADDS ``trade.fee`` here. A
    SELL realizes this proportionally to the fraction of ``quantity``
    sold -- what remains after the sell is
    ``buy_fee_accumulated * (remaining_quantity / quantity_before_sell)``,
    so a full SELL always leaves exactly ``0.0``; the remainder stays
    on the still-OPEN position. ``average_price``/``realized_pnl`` are
    computed exactly as before -- this field is tracked alongside
    them, not folded into either formula. Defaults to ``0.0``
    (``REAL NOT NULL``), same all-NOT-NULL numeric style as
    ``quantity``/``average_price``/``realized_pnl``.

    ``direction`` (Activation 11.11, additive, persistence groundwork
    only for Activation 11.10's LOCKED Forex persistence decision):
    ``"LONG"`` or ``"SHORT"`` (``Database.position_constants.
    POSITION_DIRECTIONS``, SQL ``CHECK``-enforced). Defaults to
    ``"LONG"``, all-NOT-NULL style like ``buy_fee_accumulated`` --
    there is no honest "no direction" NULL state, every position
    unambiguously has one. This is the single schema change
    Activation 11.10 Decision B/K identified as necessary to
    eventually represent a two-sided Forex position without turning
    ``quantity`` into a signed value (which stays an unsigned
    magnitude for every market, including this one). Setting it to
    anything other than the default ``"LONG"``, and any business
    logic that reads it, is explicitly OUT OF SCOPE for this
    Activation -- see ``Business.position_manager.PositionManager``,
    which is NOT modified here and still only ever produces
    ``"LONG"`` positions.
    """

    position_id: int
    account_id: str
    symbol: str
    quantity: float
    average_price: float
    realized_pnl: float
    status: str
    created_at: str
    updated_at: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    buy_fee_accumulated: float = 0.0
    direction: str = "LONG"


@dataclass
class Order:
    """One row of the ``orders`` table (see
    ``Database.migrations_orders.ORDERS_MIGRATIONS``).

    ``order_id`` is a surrogate autoincrement integer, mirroring
    ``Position.position_id`` rather than ``Account.account_id``: an
    order has no stable natural key of its own -- ``account_id`` +
    ``symbol`` can repeat across many distinct orders over time -- so
    a repository-generated surrogate key is the only sound identity
    here, exactly the same reasoning ``Position`` already documents.

    Mutable entity: ``filled_price``/``filled_quantity``/``status``/
    ``reason`` are updated in place via ``OrderRepository.update``/
    ``update_status``, not appended-only -- mirrors ``Position``.

    ``filled_quantity`` (Sprint 4 STEP 3, LOCKED design decision):
    added now as a structural field, not a speculative one. Without
    it, the ``PARTIALLY_FILLED`` status (see
    ``Database.order_constants.ORDER_STATUSES``) would have no data
    representation at all. Sprint 4 does NOT yet implement partial
    fills -- no business logic anywhere computes or reasons about this
    field yet -- this STEP only stores whatever value a caller
    supplies, exactly like every other persistence-only field here.
    Defaults to ``0.0`` (not ``NULL``): this project has no precedent
    for a nullable numeric domain field (``Position.quantity``/
    ``average_price``/``realized_pnl`` are all ``REAL NOT NULL``,
    never ``NULL``-defaulted) -- ``0.0`` reads as "nothing filled yet",
    which is both the correct initial value once fills are implemented
    and consistent with the project's existing all-NOT-NULL numeric
    style. See ``Database.migrations_orders`` for the column
    definition.

    ``filled_at`` (Activation 3.4 STEP 2, additive): the roadmap
    contract for a filled order is ``Order.status = FILLED``,
    ``Order.filled_price = Trade.fill_price``,
    ``Order.filled_quantity = Trade.quantity``, and
    ``Order.filled_at = Trade.executed_at`` -- the Activation 3.4
    STEP 1 audit confirmed this field did not exist anywhere in the
    schema/dataclass before this STEP. Unlike ``filled_price``/
    ``filled_quantity``, it is ``Optional[str]`` defaulting to
    ``None`` (SQL ``NULL``), not ``0.0``: there is no timestamp
    sentinel meaning "not filled yet" the way ``0.0`` reads for a
    numeric fill field, so an order that has never been filled simply
    has no ``filled_at`` value at all. Set once, together with
    ``status``/``filled_price``/``filled_quantity``, by
    ``Business.execution_service.ExecutionService.execute_order()``
    copying it from the ``Trade`` it just created -- never computed or
    read back from a market/clock source by this field itself. See
    ``Database.migrations_orders`` version=13 for the column
    definition.

    ``analysis_snapshot_id`` (Activation 5.1, additive): the single
    decision-linkage field (of the roadmap's 13) the Activation 5.1
    STEP 1 audit found a genuine, already-existing production source
    for -- ``RankingSnapshot.snapshot_id``. ``Optional[int]`` defaulting
    to ``None`` (SQL ``NULL``), mirroring ``filled_at``'s nullable
    style: an order submitted without a matching snapshot (or against
    a pre-Activation-5.1 row) simply has none, there is no numeric
    sentinel for "no snapshot". Set once, at creation, by
    ``Business.order_lifecycle_service.OrderLifecycleService.
    create_order()`` from whatever value
    ``Business.paper_trading_engine.PaperTradingEngine.submit_order()``
    extracted off its ``signal_evidence`` parameter -- never computed,
    never looked up independently by this field itself. See
    ``Database.migrations_orders`` version=15 for the column
    definition and the full rationale for why the other 12 roadmap 5.1
    fields are NOT added here.
    """

    order_id: int
    account_id: str
    symbol: str
    action: str
    quantity: float
    requested_price: float
    filled_price: float
    filled_quantity: float
    status: str
    reason: str
    created_at: str
    updated_at: str
    filled_at: Optional[str] = None
    analysis_snapshot_id: Optional[int] = None


@dataclass
class Trade:
    """One row of the ``trades`` table (see
    ``Database.migrations_trades.TRADES_MIGRATIONS``).

    ``trade_id`` is a surrogate autoincrement integer, mirroring
    ``Position.position_id``/``Order.order_id`` rather than
    ``Account.account_id``: a trade has no stable natural key of its
    own -- ``account_id`` + ``symbol`` (and even ``order_id``) can
    repeat across many distinct trades over time (e.g. partial fills
    of the same order produce multiple trade rows) -- so a
    repository-generated surrogate key is the only sound identity
    here, exactly the same reasoning ``Position``/``Order`` already
    document.

    Immutable entity (LOCKED design decision, Sprint 4 STEP 4): unlike
    ``Account``/``Position``/``Order``, a ``Trade`` is never updated or
    deleted once recorded -- it is an append-only ledger entry. Any
    future correction is represented as a new ``Trade`` row, never an
    in-place mutation of an existing one. This is why ``Trade`` has no
    ``updated_at`` field: it would have no meaning for a row that can
    never change after insertion. ``executed_at`` is the one and only
    timestamp -- it is a business fact (when the trade executed), not
    a persistence-lifecycle timestamp, and is therefore supplied by
    the caller rather than auto-generated by this STEP's repository
    (see ``Repository.persistence.trade_repository.TradeRepository``
    for the full rationale -- deciding *when* a trade executed is
    business logic reserved for a future ``ExecutionService``).

    This STEP persists whatever ``action``/``quantity``/``fill_price``/
    ``fee``/``tax``/``executed_at`` values a caller supplies; it does
    not compute fees, taxes, average price, or P/L itself (that is
    business logic reserved for a later Sprint 4 STEP).
    """

    trade_id: int
    order_id: int
    account_id: str
    symbol: str
    action: str
    quantity: float
    fill_price: float
    fee: float
    tax: float
    executed_at: str


@dataclass
class OrderIdempotencyKey:
    """One row of the ``order_idempotency_keys`` table (see
    ``Database.migrations_idempotency.IDEMPOTENCY_MIGRATIONS``).

    Introduced for Activation 3.2 pre-trade validation. Records that a
    given caller-supplied ``idempotency_key`` has already been used to
    successfully submit and execute a paper order, so a retried/
    duplicate request carrying the same key can be rejected by
    ``PaperTradingEngine`` before any new ``Order``/``Trade`` row is
    created.

    ``idempotency_key`` is the natural primary key -- deliberately NOT
    a surrogate autoincrement integer, mirroring ``Account.account_id``
    rather than ``Position.position_id``/``Order.order_id``/
    ``Trade.trade_id``: the whole point of this table is a fast,
    unambiguous existence check on the caller-supplied key itself.

    Immutable entity, mirroring ``Trade``: written exactly once, after
    a ``submit_order()`` call has already produced a ``Trade`` --
    never updated afterward. See
    ``Business.paper_trading_engine.PaperTradingEngine.submit_order``
    for exactly when this row is written and the documented
    single-process-only concurrency caveat.
    """

    idempotency_key: str
    account_id: str
    order_id: int
    trade_id: int
    created_at: str


@dataclass
class OrderApproval:
    """One row of the ``order_approvals`` table (see
    ``Database.migrations_order_approvals.ORDER_APPROVALS_MIGRATIONS``).

    Introduced for Activation 7 Blocker #4: makes the ``user_approval``
    that already gates ``PaperTradingEngine.submit_order()`` (gate 3,
    LOCKED, unchanged) auditable from the database, instead of only
    ever existing as a transient function argument.

    ``order_id`` is the natural primary key -- deliberately NOT a
    surrogate autoincrement integer, mirroring ``OrderIdempotencyKey.
    idempotency_key`` rather than ``Trade.trade_id``/``Order.
    order_id``'s own surrogate keys: one ``submit_order()`` call
    produces at most one ``Order``, so ``order_id`` is already a
    unique, unambiguous key for its approval record.

    Immutable entity, mirroring ``OrderIdempotencyKey``: written
    exactly once, after a ``submit_order()`` call has already produced
    a fully-committed ``Trade`` -- never updated afterward. See
    ``Business.paper_trading_engine.PaperTradingEngine.submit_order``
    for exactly when this row is written (best-effort, after the
    trading state is already fully committed -- a failure writing this
    row never rolls back the trade).

    ``approved`` records the exact ``user_approval`` value gate 3
    already required to be ``True`` -- not hard-coded, so the row's
    own data is the source of truth. ``recorded_at`` is this row's own
    write timestamp, not a fabricated "approval granted at" time (see
    the migration module docstring for why).
    """

    order_id: int
    trade_id: int
    account_id: str
    approved: bool
    recorded_at: str


@dataclass
class BriefApproval:
    """One row of the ``brief_approvals`` table (see
    ``Database.migrations_brief_approvals.BRIEF_APPROVALS_MIGRATIONS``).

    Phase G (Task 1/2, "Approved Brief -> Paper Link Contract"):
    records that a specific, explicitly-approved ``DecisionBrief`` was
    the basis for a specific paper ``Order``/``Trade``. Distinct from
    ``OrderApproval``: that table records the ``user_approval``
    boolean ``PaperTradingEngine.submit_order()`` gate 3 already
    required for *any* order; this table records *which brief, if
    any* justified this particular order.

    ``brief_id`` is the natural primary key -- deliberately NOT a
    surrogate autoincrement integer, mirroring ``OrderApproval.
    order_id``: a brief may be linked to at most one paper order/trade
    (Phase G roadmap requirement), so ``brief_id`` is already a
    unique, unambiguous key for its own link record.

    Immutable entity, mirroring ``OrderApproval``: written exactly
    once, after ``PaperTradingEngine.submit_order()`` has already
    produced a fully-committed ``Trade`` -- never updated afterward.
    See ``Services.brief_approval_service.BriefApprovalService`` for
    exactly when this row is written (best-effort, after the trading
    state is already fully committed -- a failure writing this row
    never rolls back the trade).

    ``approved_at`` is the timestamp of the explicit human approval
    decision that gated this link. ``recorded_at`` is this row's own
    write timestamp, not a fabricated "approval granted at" time --
    mirroring the same distinction ``OrderApproval.recorded_at``
    already documents.
    """

    brief_id: int
    order_id: int
    trade_id: int
    approved_at: str
    recorded_at: str


@dataclass
class RankingSnapshot:
    """One row of the ``ranking_snapshots`` table (see
    ``Database.migrations_snapshots.SNAPSHOTS_MIGRATIONS``).

    ``snapshot_id`` is a surrogate autoincrement integer, mirroring
    ``Trade.trade_id``/``Position.position_id``/``Order.order_id``
    rather than ``Account.account_id``: a ranking snapshot has no
    stable natural key -- the same ``symbol`` reappears across many
    distinct ``RankingEngine`` runs over time, so a repository-
    generated surrogate key is the only sound identity here.

    Immutable entity (LOCKED design decision, Sprint 5 STEP 3): like
    ``Trade``, a ``RankingSnapshot`` is never updated or deleted once
    recorded -- it is an append-only record of what ``RankingEngine.
    rank()`` produced for one symbol at one ``scan_time``. Any future
    correction is a new row, never an in-place mutation. This is why
    there is no ``updated_at`` field: ``scan_time`` is the one and
    only timestamp, and it is a business fact (when the scan this
    ranking came from ran), not a persistence-lifecycle timestamp.

    ``symbol``/``recommendation``/``confidence``/``priority``/``rank``
    mirror ``Business.ranking_engine.RankedSymbol`` exactly -- this is
    a persisted copy of that already-computed, already-flattened
    value, not a recomputation of it. This STEP persists whatever
    values a caller supplies; it does not run ``RankingEngine``, read
    ``WatchlistScanner``/any Tool/``Core.analysis_pipeline``, compute a
    ranking, or produce a recommendation (that is all business logic
    that has already happened by the time ``SnapshotRepository.create``
    is called -- see ``Repository.persistence.snapshot_repository.
    SnapshotRepository`` for the full scope boundary).

    Deliberately NOT the same table/schema as the ERD's
    ``ANALYSIS_SNAPSHOTS`` (``instrument_id`` FK / ``analysis_type`` /
    ``payload_json`` / ``created_at``) -- that is a different, not-yet-
    implemented concept (an AI-analysis payload store), reserved
    separately at migration version=6. See
    ``Database.migrations_snapshots`` module docstring for the full
    version-numbering rationale.

    Extended by Activation 2.7 (migration version=11) to also carry,
    in the SAME row (no new table, no join key -- see
    ``Database.migrations_snapshots`` version=11 for why): ``status``
    (``"success"``/``"error"``), the ``score``/``score_breakdown_json``
    RankingEngine already computed but Sprint 5 STEP 4 discarded, the
    real ``evidence_summary`` text WatchlistAnalysisSkill already
    produced but nothing downstream read, and ``error_message`` for a
    symbol RankingEngine's own filter excluded.
    ``recommendation``/``confidence``/``priority``/``rank`` became
    ``Optional`` because an error row has none of them to report.
    """

    snapshot_id: int
    scan_time: str
    symbol: str
    recommendation: Optional[str] = None
    confidence: Optional[str] = None
    priority: Optional[int] = None
    rank: Optional[int] = None
    status: str = "success"
    score: Optional[int] = None
    score_breakdown_json: Optional[str] = None
    evidence_summary: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class PortfolioSnapshot:
    """One row of the ``portfolio_snapshots`` table (see
    ``Database.migrations_portfolio_snapshots.
    PORTFOLIO_SNAPSHOTS_MIGRATIONS``, migration version=8).

    ``snapshot_id`` is a surrogate autoincrement integer, mirroring
    ``Trade.trade_id``/``Position.position_id``/``Order.order_id``/
    ``RankingSnapshot.snapshot_id`` rather than ``Account.account_id``:
    a portfolio snapshot has no stable natural key -- the same
    ``account_id`` reappears across many distinct snapshots taken over
    time.

    ``account_id`` (beyond the Activation 5.2 roadmap's explicit
    8-field list): required to scope every other field on this row to
    the ``Account`` it was captured from -- mirrors ``Position``/
    ``Order``/``Trade``, all of which carry ``account_id`` for the
    same reason. See ``Database.migrations_portfolio_snapshots`` for
    the full rationale.

    Immutable entity (LOCKED design decision, Activation 5.2): like
    ``Trade``/``RankingSnapshot``, a ``PortfolioSnapshot`` is never
    updated or deleted once recorded -- it is an append-only record of
    portfolio state at ``timestamp``. Any future correction is a new
    row, never an in-place mutation.

    Every field is sourced from an already-real, already-verified
    place (see ``Business.portfolio_snapshot_service.
    PortfolioSnapshotService`` for exactly how each is derived) --
    this dataclass does not compute anything itself:

    * ``cash`` -- read verbatim from ``Account.cash``.
    * ``market_value``/``unrealized_pnl`` -- summed across this
      account's OPEN positions using the existing, LOCKED
      ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` (the sole
      business owner of unrealized P/L) and its real market price.
    * ``realized_pnl`` -- summed across every ``Position`` row (open
      and closed) for this account, straight off
      ``Position.realized_pnl``.
    * ``equity`` -- ``cash + market_value``, both already-real
      components; not read from ``Account.equity`` (that field is
      explicitly documented, in
      ``Business.account_balance_service``, as passed through
      unchanged / not yet computed by anything in this codebase --
      using it here would silently persist a stale/fabricated value).
    * ``exposure`` -- ``Optional[float]``, ``None`` unless a future
      Activation identifies a real source. The Activation 5.2 audit
      found no existing, already-computed total-portfolio exposure
      value in the codebase (see
      ``Database.migrations_portfolio_snapshots`` for why
      ``Orchestration.portfolio_engine.PortfolioEngine.exposure`` does
      NOT qualify as that source). NOT VERIFIABLE / GAP -- never
      fabricated.
    * ``drawdown`` -- computed by the existing, LOCKED
      ``Business.maximum_drawdown_engine.MaximumDrawdownEngine`` over
      the real equity curve formed by this account's prior
      ``PortfolioSnapshot.equity`` values (chronological) plus this
      snapshot's own ``equity``. ``0.0`` when fewer than two points
      exist yet -- the engine's own documented edge case, not a
      fabricated default.
    * ``timestamp`` -- the real UTC instant this snapshot was
      composed, ``datetime.now(timezone.utc).isoformat()`` -- the same
      pattern already used for ``Account``/``Position``/``Order``
      ``created_at``/``updated_at``.
    """

    snapshot_id: int
    account_id: str
    cash: float
    market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float
    timestamp: str
    exposure: Optional[float] = None
    valuation_status: Optional[str] = None
    """Phase G Task 3 addition (see ``Database.migrations_portfolio_
    snapshot_valuation_status``). Portfolio-level summary of the
    per-position valuation freshness labels
    ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` attached
    when composing this snapshot: ``"FRESH"`` if every open position's
    market price was fresh, ``"STALE"`` if at least one open position
    fell back to a retained last-good price, or ``None`` if freshness
    tracking was not enabled for this snapshot (the pre-Phase-G-Task-3
    default) or the account has no open positions. Never
    ``"UNAVAILABLE"`` on a persisted row -- an unavailable valuation
    fails the whole snapshot (``ValidationError``) rather than being
    persisted, per ``PortfolioSnapshotService.take_snapshot``."""

@dataclass
class DailyPerformance:
    """One row of the ``daily_performance`` table (see
    ``Database.migrations_daily_performance.DAILY_PERFORMANCE_MIGRATIONS``).

    ``daily_performance_id`` is a surrogate autoincrement integer,
    mirroring ``PortfolioSnapshot.snapshot_id``/``Trade.trade_id``/
    ``Position.position_id``/``Order.order_id`` rather than
    ``Account.account_id``: a daily performance row has no stable
    natural key of its own -- the same ``account_id`` reappears across
    many distinct periods summarized over time.

    Immutable entity (LOCKED design decision, Activation 5.3): like
    ``Trade``/``PortfolioSnapshot``, a ``DailyPerformance`` row is
    never updated or deleted once recorded -- it is an append-only
    summary of one account's trading performance over
    ``[start_timestamp, end_timestamp]``. Any future correction is a
    new row, never an in-place mutation.

    Every field is sourced from an already-real, already-verified
    place (see ``Business.daily_performance_service.
    DailyPerformanceService`` for exactly how each is derived) -- this
    dataclass does not compute anything itself:

    * ``start_timestamp``/``end_timestamp`` -- supplied verbatim by
      the caller; this entity does not decide its own period.
    * ``starting_equity``/``ending_equity`` -- the ``PortfolioSnapshot.
      equity`` of the latest snapshot at/before ``start_timestamp``/
      ``end_timestamp`` respectively. ``Optional[float]``, ``None``
      when no qualifying snapshot exists -- a real structural
      limitation (this account was never snapshotted in range), never
      fabricated as ``0.0`` or otherwise.
    * ``realized_result`` -- summed across every ``Position`` row
      (open and closed) for this account, straight off
      ``Position.realized_pnl``, mirroring
      ``PortfolioSnapshot.realized_pnl``.
    * ``unrealized_result`` -- summed across this account's OPEN
      positions using the existing, LOCKED
      ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` (the sole
      business owner of unrealized P/L) -- never recomputed here.
    * ``fees``/``tax`` -- summed across this account's ``Trade`` rows
      whose ``executed_at`` falls within
      ``[start_timestamp, end_timestamp]``, straight off
      ``Trade.fee``/``Trade.tax``.
    * ``net_result`` -- ``realized_result + unrealized_result - fees
      - tax``; a direct derivation, not a separately fabricated value
      and not owned by any dedicated engine.
    * ``drawdown`` -- computed by the existing, LOCKED
      ``Business.maximum_drawdown_engine.MaximumDrawdownEngine`` over
      the real ``PortfolioSnapshot.equity`` curve within this period
      -- this dataclass never reimplements the peak/drawdown formula.
    * ``number_of_signals`` -- ``Optional[int]``, always ``None`` at
      this Activation. NOT VERIFIABLE / GAP -- the Activation 5.3
      audit found no ``Signal`` entity in the codebase, and
      ``RankingSnapshot`` is a different, per-symbol scan-run record
      that does not qualify as a substitute. Never fabricated.
    * ``number_of_executions`` -- the count of this account's
      ``Trade`` rows within ``[start_timestamp, end_timestamp]``.
    * ``timestamp`` -- the real UTC instant this row was composed,
      ``datetime.now(timezone.utc).isoformat()`` -- the same pattern
      already used for ``PortfolioSnapshot.timestamp``.
    """

    daily_performance_id: int
    account_id: str
    start_timestamp: str
    end_timestamp: str
    realized_result: float
    unrealized_result: float
    fees: float
    tax: float
    net_result: float
    drawdown: float
    number_of_executions: int
    timestamp: str
    starting_equity: Optional[float] = None
    ending_equity: Optional[float] = None
    number_of_signals: Optional[int] = None

@dataclass
class RiskLimits:
    """The single, mutable row of the ``risk_limits`` table (see
    ``Database.migrations_risk_ledger.RISK_LEDGER_MIGRATIONS``,
    migration version=20).

    Phase C ("Personal Risk Ledger + Decision Journal"): a person's
    own trading limits, entirely caller-supplied -- this dataclass and
    its repository compute nothing. ``id`` is always the literal
    string ``"default"`` (one row, updated in place, same "mutable
    singleton" shape as ``Account``'s own row-per-account balances,
    just with exactly one row here since these are personal, not
    per-account, limits).

    ``max_risk_per_trade_percent`` is evaluated against
    ``reference_capital`` (never against a live ``Account.equity`` --
    that would silently change the limit's meaning as the account
    moves) by ``Business.risk_ledger_policy.RiskLedgerPolicy``, the
    one new risk-policy component Phase C adds; it never recomputes
    ``DecisionBrief.risk_amount`` itself. ``allowed_symbols`` is
    ``None``/empty for "no restriction", otherwise the exact
    upper-cased symbol list a TAKE decision is restricted to.
    """

    id: str
    reference_capital: float
    max_risk_per_trade_percent: float
    max_daily_loss: float
    max_trades_per_day: int
    loss_streak_cooldown: int
    allowed_symbols: Optional[List[str]] = None
    updated_at: str = ""


@dataclass
class JournalEntry:
    """One row of the ``journal_entries`` table (see
    ``Database.migrations_risk_ledger.RISK_LEDGER_MIGRATIONS``,
    migration version=21).

    Phase C ("Personal Risk Ledger + Decision Journal"): a person's own
    TAKE/SKIP/WAIT call against an existing ``DecisionBrief``
    (``brief_id``), plus -- for an ``ACCEPTED`` TAKE only -- optional
    manual execution/close information filled in later. Recording a
    journal entry, of any kind, never creates a paper order, a
    ``Trade``, or a ``Position``: this table has no foreign key to any
    of those and no code path from ``Services.journal_service.
    JournalService`` writes to them.

    ``decision`` is exactly one of ``"TAKE"``/``"SKIP"``/``"WAIT"``,
    caller-supplied. ``risk_policy_status`` (``"ACCEPTED"`` or
    ``"RISK_REJECTED"``) and ``risk_policy_reason`` are the verbatim
    output of ``Business.risk_ledger_policy.RiskLedgerPolicy.evaluate``
    -- a SKIP/WAIT always resolves ``ACCEPTED`` (nothing to enforce
    when no capital is being committed); only a TAKE is actually
    risk-checked against the persisted ``RiskLimits`` row and this
    person's own journal history. ``planned_r`` is the linked brief's
    own ``risk_reward_ratio``, verbatim, recorded only for a TAKE
    against a ``SUCCESS`` brief -- never recomputed.

    The five outcome fields (``outcome_status``/``exit_price``/
    ``realized_r``/``closed_at``, plus this same ``note`` field
    revisited) start ``None`` at creation and may be filled in exactly
    once, later, via ``JournalRepository.record_outcome`` -- the one
    field group in this table that is not append-only-immutable, since
    a trade's real-world outcome is only known after the fact.
    ``realized_r`` is computed only when genuinely calculable: a real
    ``exit_price`` was supplied AND the linked brief has a real
    ``entry_price``/``stop_loss_price`` with positive risk-per-unit --
    otherwise it stays ``None`` rather than being guessed.
    """

    entry_id: int
    brief_id: int
    symbol: str
    decision: str
    decided_at: str
    risk_policy_status: str
    created_at: str
    note: Optional[str] = None
    risk_policy_reason: Optional[str] = None
    planned_r: Optional[float] = None
    outcome_status: Optional[str] = None
    exit_price: Optional[float] = None
    realized_r: Optional[float] = None
    closed_at: Optional[str] = None


@dataclass
class SchedulerJobRun:
    """One row of the ``scheduler_job_runs`` table (see
    ``Database.migrations_scheduler.SCHEDULER_MIGRATIONS``, migration
    version=22).

    Phase D ("Proactive IDX Scheduler Routine"): the single source of
    truth ``Orchestration.idx_daily_scheduler.IDXDailyScheduler`` uses
    to decide "has job ``job_type`` already run (successfully or not)
    for IDX trading date ``trading_date``" -- surviving a process
    restart requires nothing more than re-reading this table.

    Primary key is ``(job_type, trading_date)`` -- a genuine upsert
    target (one row per job per trading day, not an append-only log).
    A retried job updates the same row's ``attempt``/``status``/
    ``finished_at``/``next_retry_at`` in place.

    Attributes:
        job_type: One of the fixed Phase D job identifiers (e.g.
            ``"pre_market_check"``, ``"session_scan"``,
            ``"data_health_check"``, ``"market_close_recap"``,
            ``"daily_review"``).
        trading_date: IDX-local (Asia/Jakarta) ISO date string
            (``YYYY-MM-DD``) this run belongs to.
        status: ``"RUNNING"`` / ``"SUCCESS"`` / ``"FAILED"``.
        attempt: 1-indexed attempt count for this job/trading_date.
        started_at: ISO-8601 timestamp of the most recent attempt's
            start.
        finished_at: ISO-8601 timestamp of the most recent attempt's
            end, or ``None`` while ``status == "RUNNING"``.
        next_retry_at: ISO-8601 timestamp before which a retry must
            not be attempted (backoff), or ``None`` when no retry is
            pending.
        detail: Free-text detail (e.g. an error message), or ``None``.
    """

    job_type: str
    trading_date: str
    status: str
    attempt: int
    started_at: str
    finished_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class NotificationDedupState:
    """One row of the ``notification_dedup_state`` table (see
    ``Database.migrations_scheduler.SCHEDULER_MIGRATIONS``, migration
    version=23).

    Phase D: persisted counterpart of
    ``Business.notification_dedup_policy.DedupState`` -- the last
    signature/timestamp/status of the last alert actually sent (or
    suppressed/failed) for one ``alert_type``. One row per
    ``alert_type`` (primary key), updated in place.

    Attributes:
        alert_type: Stable identifier for this alert channel (e.g.
            ``"session_scan_brief"``, ``"data_freshness"``).
        last_signature: Signature of the last alert actually sent, or
            ``None`` if never sent.
        last_sent_at: ISO-8601 timestamp of the last actual send, or
            ``None`` if never sent.
        last_status: ``"SENT"`` / ``"SUPPRESSED"`` / ``"FAILED"`` --
            the outcome of the most recent evaluation, regardless of
            whether it was actually sent.
        updated_at: ISO-8601 timestamp this row was last written.
    """

    alert_type: str
    last_signature: Optional[str]
    last_sent_at: Optional[str]
    last_status: str
    updated_at: str


@dataclass
class AuditEvent:
    """One row of the ``audit_events`` table (see
    ``Database.migrations_scheduler.SCHEDULER_MIGRATIONS``, migration
    version=24).

    Phase D Health/audit requirement: an append-only log of every
    scheduler job start/success/failure, notification sent/
    suppressed/failed, and freshness degradation/recovery transition.
    Never updated after creation -- ``id`` is auto-increment, purely
    chronological.

    Attributes:
        id: Auto-increment row id (``None`` before insert).
        event_type: Short machine-readable event name (e.g.
            ``"job_started"``, ``"job_succeeded"``, ``"job_failed"``,
            ``"notification_sent"``, ``"notification_suppressed"``,
            ``"notification_failed"``, ``"freshness_degraded"``,
            ``"freshness_recovered"``).
        payload: Free-form JSON string with event-specific detail
            (e.g. ``job_type``, ``trading_date``, ``reason``) -- never
            parsed/interpreted by the repository itself.
        created_at: ISO-8601 timestamp this event was recorded.
    """

    id: Optional[int]
    event_type: str
    payload: Optional[str]
    created_at: str


@dataclass
class TelegramCommandAudit:
    """One row of the ``telegram_command_audit`` table (see
    ``Database.migrations_telegram_control.TELEGRAM_CONTROL_MIGRATIONS``,
    migration version=25).

    Phase E foundational task: an append-only log of every inbound
    Telegram command received, regardless of outcome. Never updated
    after creation -- ``id`` is auto-increment, purely chronological.
    Mirrors the ``AuditEvent`` append-only pattern from Phase D.

    Attributes:
        id: Auto-increment row id (``None`` before insert).
        update_id: The Telegram ``update_id`` this command came from,
            or ``None`` if not available/applicable.
        chat_id: Telegram chat identifier the command was received
            from, or ``None`` if not available.
        command: The parsed command identifier (e.g. ``"/status"``).
        raw_text: The raw inbound message text, or ``None``.
        status: Outcome of processing this command (e.g.
            ``"RECEIVED"`` / ``"PROCESSED"`` / ``"REJECTED"``).
        detail: Free-text detail (e.g. an error message), or ``None``.
        received_at: ISO-8601 timestamp this command was recorded.
    """

    id: Optional[int]
    update_id: Optional[int]
    chat_id: Optional[str]
    command: str
    raw_text: Optional[str]
    status: str
    detail: Optional[str]
    received_at: str


@dataclass
class TelegramInboundState:
    """One row of the ``telegram_inbound_state`` table (see
    ``Database.migrations_telegram_control.TELEGRAM_CONTROL_MIGRATIONS``,
    migration version=26).

    Phase E foundational task: durable long-poll offset so an inbound
    Telegram poller can resume after a process restart without
    re-processing or dropping updates. One row per ``state_key``
    (primary key), updated in place -- mirrors the
    ``NotificationDedupState`` single-row-per-key pattern from Phase D.

    Attributes:
        state_key: Stable identifier for this polling identity (e.g.
            ``"default"`` for a single-bot deployment).
        last_update_id: The last Telegram ``update_id`` successfully
            processed, or ``None`` if polling has never advanced.
        updated_at: ISO-8601 timestamp this row was last written.
    """

    state_key: str
    last_update_id: Optional[int]
    updated_at: str


@dataclass
class ValuationObservation:
    """One row of the ``valuation_observations`` table (see
    ``Database.migrations_valuation_observations.
    VALUATION_OBSERVATIONS_MIGRATIONS``, migration version=28).

    Phase G Task 3 ("Valuation Freshness + Paper Review Inputs"): the
    most recent market price this process genuinely observed for one
    ``(account_id, symbol)`` pair, kept durable so a valuation can
    still be labelled (rather than silently fabricated) after a
    provider failure or a process restart. One row per
    ``(account_id, symbol)`` (composite primary key), overwritten in
    place on each new successful observation -- this is a "last known
    good" cache, not an append-only history.

    Every field is either read verbatim from
    ``Orchestration.market_price_tool.MarketPriceTool``'s own output
    (``price``) or the real moment that output was obtained
    (``observed_at``) -- never fabricated, interpolated, or
    re-stamped to "now" on a later read.

    Attributes:
        account_id: The account this observation's position belongs
            to (a price is scoped per account since valuation review
            is per-account, mirroring every other per-account table).
        symbol: The ticker this observation is for.
        price: The observed market price at ``observed_at``.
        observed_at: ISO-8601 UTC timestamp of the moment ``price``
            was genuinely obtained. Preserved verbatim across reads.
        source: Free-text label identifying where this observation
            came from (e.g. ``"market_price_tool"``), carried through
            for audit purposes only.
    """

    account_id: str
    symbol: str
    price: float
    observed_at: str
    source: str


@dataclass
class ObservationWindow:
    """One row of the ``operator_observation_windows`` table (see
    ``Database.migrations_observation_window.OBSERVATION_WINDOW_MIGRATIONS``,
    migration version=30).

    Phase H Task 1 ("Observation Window + Sustained-Use Review
    Record"): records exactly one operator-selected stretch of time
    the operator has chosen to review real operating records over.
    This table computes nothing and evaluates nothing -- it is purely
    the durable record of *which* window was selected, so that
    selection survives a process restart.

    Append-only history (like ``DecisionBrief``, not the single
    mutable ``RiskLimits`` row): a person may open, close, and later
    open a further window. ``status`` distinguishes the one row
    currently under review (``"ACTIVE"``) from every previously
    reviewed window (``"CLOSED"``).

    Attributes:
        window_id: Repository-generated (autoincrement) identifier.
        start_at: Operator-supplied start date/time of the window, as
            given -- never inferred or computed from data.
        end_at: Operator-supplied end date/time of the window, as
            given.
        timezone: The timezone ``start_at``/``end_at`` are expressed
            in (e.g. ``"Asia/Jakarta"``), preserved verbatim.
        note: Optional free-text operator label/note for this window.
        status: ``"ACTIVE"`` or ``"CLOSED"``.
        created_at: ISO-8601 UTC timestamp this row was created (the
            window was opened).
        closed_at: ISO-8601 UTC timestamp this window was explicitly
            closed, or ``None`` while ``status == "ACTIVE"``.
    """

    window_id: int
    start_at: str
    end_at: str
    timezone: str
    note: Optional[str]
    status: str
    created_at: str
    closed_at: Optional[str] = None


@dataclass
class OperatorFeedback:
    """One row of the ``operator_feedback`` table (see
    ``Database.migrations_sustained_use_final_review.
    SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS``, migration version=31).

    Phase H Task 4 ("Operator Feedback + Final Review Record"): one
    operator's real, explicitly-given feedback about a specific
    ``ObservationWindow``'s sustained-use review. Append-only history
    (like ``DecisionBrief``/``ObservationWindow`` -- never overwritten
    in place): an operator may record feedback more than once for the
    same window (e.g. mid-window and again at review time), so each
    submission gets its own row. This table computes nothing and
    scores nothing -- it stores exactly what the operator typed/
    selected, verbatim.

    ``concerns`` is a JSON-encoded list of operator-selected free-form
    concern/limitation labels (e.g. ``["too_many_alerts",
    "stale_data"]``), preserved verbatim as given -- this table does
    not define or constrain that vocabulary itself.

    Attributes:
        feedback_id: Repository-generated (autoincrement) identifier.
        observation_window_id: The ``ObservationWindow.window_id`` this
            feedback concerns.
        recorded_at: ISO-8601 UTC timestamp this feedback was recorded.
        operator_rating: Optional overall usefulness rating, exactly as
            given by the operator (e.g. an integer 1-5), never
            normalized or recomputed here.
        alert_usefulness: Optional free-text/label feedback on alert
            usefulness, exactly as given.
        data_reliability_feedback: Optional free-text/label feedback on
            data reliability, exactly as given.
        decision_quality_feedback: Optional free-text/label feedback on
            decision quality, exactly as given.
        workflow_usability_feedback: Optional free-text/label feedback
            on workflow usability, exactly as given.
        free_text: Optional open-ended operator comment, exactly as
            given.
        concerns: JSON-encoded list of operator-selected concern/
            limitation labels, exactly as given (``"[]"`` when none
            selected).
        operator_label: Optional operator identifier/label, exactly as
            given (mirrors ``FinalReviewRecord.decided_by``'s
            "identifier or label, whichever the caller already tracks"
            convention -- this table does not require a real user
            account system to exist).
    """

    feedback_id: int
    observation_window_id: int
    recorded_at: str
    operator_rating: Optional[int]
    alert_usefulness: Optional[str]
    data_reliability_feedback: Optional[str]
    decision_quality_feedback: Optional[str]
    workflow_usability_feedback: Optional[str]
    free_text: Optional[str]
    concerns: str = "[]"
    operator_label: Optional[str] = None


#: The exact, LOCKED ``human_decision`` vocabulary a
#: ``FinalReviewRecord`` row may hold -- see
#: ``Services.sustained_use_final_review_service`` for the service
#: that is the ONLY code path permitted to move a row off
#: ``"PENDING"``, and only via an explicit, caller-supplied value.
FINAL_REVIEW_DECISION_PENDING: str = "PENDING"
FINAL_REVIEW_DECISION_CONTINUE: str = "CONTINUE"
FINAL_REVIEW_DECISION_SIMPLIFY: str = "SIMPLIFY"
FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION: str = "AUTHORIZE_FUTURE_INVESTIGATION"


@dataclass
class FinalReviewRecord:
    """One row of the ``final_review_records`` table (see
    ``Database.migrations_sustained_use_final_review.
    SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS``, migration version=32).

    Phase H Task 4 ("Operator Feedback + Final Review Record"): the
    single durable record of one ``ObservationWindow``'s final review
    -- the evidence status/known limitations it was reviewed under,
    which real ``OperatorFeedback`` rows informed it, and, eventually,
    the one deliberate human decision that closes Phase H's review
    loop. Exactly one row per ``observation_window_id`` (unique,
    enforced by a unique index, not by application code alone),
    updated in place as more feedback arrives and, eventually, when
    the human decision is explicitly recorded -- mirrors
    ``RiskLimits``'s single-mutable-row convention, not
    ``DecisionBrief``'s append-only one, because a window has exactly
    one final review, not a history of them.

    ``human_decision`` starts, and stays, ``"PENDING"`` until a human
    explicitly supplies one of ``"CONTINUE"``/``"SIMPLIFY"``/
    ``"AUTHORIZE_FUTURE_INVESTIGATION"`` via
    ``Services.sustained_use_final_review_service.
    SustainedUseFinalReviewService.record_decision`` -- this table
    itself enforces nothing about that transition (SQLite has no
    application-level CHECK here); the service is the sole write path
    that guarantees it.

    Attributes:
        review_id: Repository-generated (autoincrement) identifier.
        observation_window_id: The ``ObservationWindow.window_id`` this
            final review concerns. Unique across this table.
        reviewed_at: ISO-8601 UTC timestamp this row was last built/
            refreshed from a real ``SustainedUseReviewResult``.
        evidence_status: Copied verbatim from
            ``SustainedUseReviewResult.overall_evidence_status``
            (``"COMPLETE_EVIDENCE"`` / ``"PARTIAL_EVIDENCE"``) at
            ``reviewed_at`` -- never recomputed here.
        known_limitations: JSON-encoded list of known-limitation
            strings, copied verbatim from
            ``SustainedUseReviewResult.known_limitations`` at
            ``reviewed_at``.
        operator_feedback_ids: JSON-encoded list of
            ``OperatorFeedback.feedback_id`` values linked to this
            window as of ``reviewed_at`` (``"[]"`` when none exist
            yet).
        human_decision: ``"PENDING"`` / ``"CONTINUE"`` / ``"SIMPLIFY"``
            / ``"AUTHORIZE_FUTURE_INVESTIGATION"``. See
            ``FINAL_REVIEW_DECISION_*`` constants above.
        decision_note: Optional free-text human rationale for
            ``human_decision``, exactly as given. ``None`` while
            ``human_decision == "PENDING"``.
        decided_at: ISO-8601 UTC timestamp the human decision was
            recorded, or ``None`` while ``human_decision == "PENDING"``.
        decided_by: Optional human/operator identifier or label,
            exactly as given. ``None`` while
            ``human_decision == "PENDING"``.
        created_at: ISO-8601 UTC timestamp this row was first created.
        updated_at: ISO-8601 UTC timestamp this row was last updated
            (evidence refresh or decision recorded).
    """

    review_id: int
    observation_window_id: int
    reviewed_at: str
    evidence_status: str
    known_limitations: str
    operator_feedback_ids: str
    human_decision: str
    decision_note: Optional[str]
    decided_at: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str