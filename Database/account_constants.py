from __future__ import annotations

# Single source of truth for Accounts domain values.
#
# Both Repository.persistence.account_repository.AccountRepository
# (Python-level validation) and Database.migrations_accounts
# (SQL CHECK constraint, generated from these same tuples at import
# time) read from here. Nothing else defines these values separately.
#
# Trade-off: once ACCOUNTS_MIGRATIONS (version=2) has been applied to
# a real database, its CHECK constraint is baked into that table's
# schema as-is. Changing these tuples later does NOT retroactively
# change an already-applied table -- it requires a new migration
# (ALTER TABLE / recreate), same as any other schema change. Do not
# edit version=2 after it has been applied anywhere.
ACCOUNT_MODES: tuple[str, ...] = ("paper", "live")
ACCOUNT_ASSET_CLASSES: tuple[str, ...] = ("stock_id", "stock_us", "crypto", "forex")

#: Canonical default account balance (cash/equity/buying_power starting
#: value, and the risk-management fallback when a context has no
#: account balance of its own yet).
#:
#: This is the ONE place this number is written down. Both
#: ``Core.analysis_pipeline.AnalysisPipeline`` (pre-existing
#: risk-management fallback) and ``Core.bootstrap`` (Activation 1.4
#: default paper account) import it from here rather than each
#: defining -- or worse, silently duplicating -- their own literal.
#: Change it once, here, and both call sites pick it up.
DEFAULT_ACCOUNT_BALANCE: float = 100_000_000.0

#: IDX (Indonesia Stock Exchange) minimum tradable lot size, in shares.
#: One "lot" on IDX equals 100 shares -- any order quantity that is not
#: an exact multiple of this is not tradable on the real exchange.
#: Introduced for Activation 3.2 pre-trade validation
#: (``Business.paper_trading_engine.PaperTradingEngine``). Not read by
#: any migration/CHECK constraint -- this is a business-layer rule,
#: not a schema constraint, unlike ``ACCOUNT_MODES``/
#: ``ACCOUNT_ASSET_CLASSES`` above.
#:
#: Activation 3.3 STEP 2: this remains the one place the literal
#: ``100`` is written down. ``PaperTradingEngine`` no longer imports
#: this constant directly -- it now reads ``lot_size`` off the
#: canonical ``Business.execution_policy_config.ExecutionPolicy``,
#: whose default value is *this* constant
#: (``ExecutionPolicy.lot_size: int = IDX_LOT_SIZE_SHARES``). Change
#: the number here, once, and both the policy default and every
#: policy-reading consumer pick it up -- no second definition was
#: introduced.
IDX_LOT_SIZE_SHARES: int = 100

#: Default ceiling (in account currency, e.g. IDR) on a single order's
#: notional value (``quantity * requested_price``), used by
#: ``PaperTradingEngine``'s "risk limit" pre-trade gate (Activation
#: 3.2). Overridable via the ``RISK_MAX_ORDER_VALUE`` env var (see
#: ``Core.composition_root._max_order_value``). Deliberately set equal
#: to ``DEFAULT_ACCOUNT_BALANCE`` -- by default a single order may use
#: up to the full default starting cash of a fresh paper account; an
#: operator who wants a tighter per-order ceiling sets the env var
#: explicitly. This is a business-layer default, not a schema
#: constraint.
DEFAULT_RISK_MAX_ORDER_VALUE: float = DEFAULT_ACCOUNT_BALANCE