"""Standalone regression checks for
``Business.paper_trading_engine.PaperTradingEngine``.

Covers Sprint 4 STEP 9 (pure orchestrator) as extended by Activation
3.2 (12 pre-trade validation gates):

* the happy path (BUY and SELL) still drives an order through
  OrderLifecycleService.create_order() -> ExecutionService.execute_order()
  and returns the resulting Trade, and records an idempotency key;
* each of the 12 pre-trade gates independently rejects a bad request
  with ValidationError, in the documented reason code, BEFORE
  OrderLifecycleService.create_order() is ever called -- proven by
  asserting zero new rows in orders/trades/accounts/positions/
  order_idempotency_keys after each failure, not just "an exception
  was raised";
* a structurally invalid order (passes pre-trade, but
  OrderLifecycleService.create_order() itself rejects it) still
  raises ValidationError and never reaches ExecutionService -- the
  Sprint 4 STEP 9 behavior, unchanged;
* submit_order() returns a Trade and only a Trade -- never a tuple,
  never the Order, never a dict;
* executed_at is passed straight through to ExecutionService
  unchanged -- the engine generates no timestamp of its own;
* the engine holds exactly its five collaborators plus two config
  values -- no other Repository/Service reference anywhere.

Run directly with ``python Tests/test_paper_trading_engine.py`` -- no
external test framework required, matching
``test_execution_service.py``/``test_order_lifecycle_service.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_ACCOUNT_NOT_FOUND,
    PRETRADE_REASON_APPROVAL_MISSING,
    PRETRADE_REASON_DUPLICATE_REQUEST,
    PRETRADE_REASON_EVIDENCE_MISSING,
    PRETRADE_REASON_INSUFFICIENT_CASH,
    PRETRADE_REASON_INSUFFICIENT_POSITION,
    PRETRADE_REASON_INVALID_LOT_SIZE,
    PRETRADE_REASON_INVALID_PRICE,
    PRETRADE_REASON_INVALID_QUANTITY,
    PRETRADE_REASON_INVALID_SYMBOL,
    PRETRADE_REASON_DAILY_LOSS_LIMIT_EXCEEDED,
    PRETRADE_REASON_KILL_SWITCH_ENGAGED,
    PRETRADE_REASON_MARKET_KILL_SWITCH_ENGAGED,
    PRETRADE_REASON_MAX_POSITION_VALUE_EXCEEDED,
    PRETRADE_REASON_RISK_LIMIT_EXCEEDED,
    PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED,
    PaperTradingEngine,
)
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _build_engine(
    tmp_dir: str,
    *,
    cash: float = 100_000_000.0,
    kill_switch: bool = False,
    max_order_value: float = 1_000_000_000.0,
    halted_markets: frozenset = None,
    halted_symbols: frozenset = None,
    max_daily_loss: float = None,
    max_position_value: float = None,
):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "paper_trading_engine.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo)
    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=kill_switch,
        max_order_value=max_order_value,
        halted_markets=halted_markets,
        halted_symbols=halted_symbols,
        max_daily_loss=max_daily_loss,
        max_position_value=max_position_value,
    )
    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
    }
    return engine, repos


def _row_counts(repos) -> dict:
    return {
        "accounts": len(repos["account"].list_all()),
        "positions": len(repos["position"].list_all()),
        "orders": len(repos["order"].list_all()),
        "trades": len(repos["trade"].list_all()),
    }


def _default_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        executed_at="2026-08-01T10:00:00+00:00",
        signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
        user_approval=True,
        idempotency_key="req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _expect_pretrade_rejection(engine, repos, reason: str, description: str, **overrides) -> None:
    before = _row_counts(repos)
    idempotency_before = repos["idempotency"].get_by_key(overrides.get("idempotency_key", "req-001"))

    raised_reason = None
    try:
        engine.submit_order(**_default_kwargs(**overrides))
    except ValidationError as exc:
        raised_reason = exc.details.get("reason")

    check(raised_reason == reason, f"{description}: ValidationError reason == '{reason}'")

    after = _row_counts(repos)
    check(before == after, f"{description}: zero writes to accounts/positions/orders/trades")

    idempotency_after = repos["idempotency"].get_by_key(overrides.get("idempotency_key", "req-001"))
    check(
        idempotency_before == idempotency_after,
        f"{description}: idempotency key state unchanged (no stray write)",
    )


def scenario_happy_path_buy_returns_trade():
    print("\n[Scenario 1] valid BUY order end-to-end: submit_order() returns a Trade")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)

        result = engine.submit_order(**_default_kwargs())

        check(isinstance(result, Trade), "submit_order() returns a Trade instance")
        check(result.trade_id is not None, "returned Trade has a trade_id")
        check(result.account_id == "paper-id", "Trade.account_id copied through the chain")
        check(result.symbol == "BBCA", "Trade.symbol copied through the chain")
        check(result.action == "BUY", "Trade.action copied through the chain")
        check(result.quantity == 100.0, "Trade.quantity copied through the chain")
        check(result.fill_price == 9500.0, "Trade.fill_price reflects requested_price")
        check(
            result.executed_at == "2026-08-01T10:00:00+00:00",
            "Trade.executed_at is exactly the caller-supplied value (no generated timestamp)",
        )

        trades = repos["trade"].list_by_order(result.order_id)
        check(len(trades) == 1, "exactly one Trade row exists for the order")

        order = repos["order"].get_by_id(result.order_id)
        check(order.status == "FILLED", "Order.status ends as FILLED")

        idem = repos["idempotency"].get_by_key("req-001")
        check(idem is not None, "idempotency key was recorded after successful Trade")
        check(idem.order_id == result.order_id and idem.trade_id == result.trade_id, "idempotency key points at the right order/trade")


def scenario_happy_path_sell_with_position_returns_trade():
    print("\n[Scenario 2] valid SELL order with sufficient open position returns a Trade")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        repos["position"].create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=500.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )

        result = engine.submit_order(
            **_default_kwargs(action="SELL", quantity=200.0, idempotency_key="req-sell-001")
        )

        check(isinstance(result, Trade), "SELL submit_order() returns a Trade instance")
        check(result.action == "SELL", "Trade.action == SELL")
        check(result.quantity == 200.0, "Trade.quantity == requested SELL quantity")


def scenario_rejected_order_raises_and_never_executes():
    print("\n[Scenario 3] pre-trade passes but OrderLifecycleService structurally rejects: no Trade")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)

        raised = False
        try:
            engine.submit_order(**_default_kwargs(action="INVALID_ACTION", idempotency_key="req-bad-action"))
        except ValidationError:
            raised = True
        check(raised, "submit_order() raises ValidationError for a structurally invalid order")

        all_orders = repos["order"].list_all()
        check(
            len(all_orders) == 1 and all_orders[0].status == "REJECTED",
            "the underlying Order was created and left REJECTED by OrderLifecycleService",
        )

        trades = repos["trade"].list_by_order(all_orders[0].order_id) if all_orders else []
        check(len(trades) == 0, "no Trade was created for the rejected order (ExecutionService never called)")

        idem = repos["idempotency"].get_by_key("req-bad-action")
        check(idem is None, "no idempotency key recorded for a structurally rejected order")


def scenario_pretrade_gate_1_account_not_found():
    print("\n[Scenario 4] Gate 1 -- account aktif: unknown account rejected, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_ACCOUNT_NOT_FOUND,
            "unknown account_id", account_id="ghost-account",
        )


def scenario_pretrade_gate_2_evidence_missing():
    print("\n[Scenario 5] Gate 2 -- signal/evidence tersedia: falsy evidence rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_EVIDENCE_MISSING,
            "empty signal_evidence", signal_evidence=None,
        )
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_EVIDENCE_MISSING,
            "empty-dict signal_evidence", signal_evidence={},
        )


def scenario_pretrade_gate_3_approval_missing():
    print("\n[Scenario 6] Gate 3 -- user approval tersedia: non-True approval rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_APPROVAL_MISSING,
            "user_approval=False", user_approval=False,
        )
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_APPROVAL_MISSING,
            "user_approval=None", user_approval=None,
        )


def scenario_pretrade_gate_4_invalid_symbol():
    print("\n[Scenario 7] Gate 4 -- symbol valid: blank symbol rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_SYMBOL,
            "blank symbol", symbol="   ",
        )


def scenario_pretrade_gate_5_invalid_quantity():
    print("\n[Scenario 8] Gate 5 -- quantity valid: non-positive quantity rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_QUANTITY,
            "negative quantity", quantity=-100.0,
        )
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_QUANTITY,
            "zero quantity", quantity=0.0,
        )


def scenario_pretrade_gate_6_invalid_lot_size():
    print("\n[Scenario 9] Gate 6 -- IDX lot size valid: non-multiple-of-100 rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_LOT_SIZE,
            "quantity=150 (not a multiple of 100)", quantity=150.0,
        )


def scenario_pretrade_gate_7_invalid_price():
    print("\n[Scenario 10] Gate 7 -- price positif: non-positive price rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_PRICE,
            "zero price", requested_price=0.0,
        )
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_PRICE,
            "negative price", requested_price=-500.0,
        )


def scenario_pretrade_gate_8_insufficient_cash():
    print("\n[Scenario 11] Gate 8 -- available cash: BUY beyond cash rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, cash=100_000.0)

        # Activation 3.9 STEP 2: strengthen the existing row-count-only
        # proof with an explicit VALUE assertion on cash -- the audit
        # (STEP 1, sec. 6) noted the row-count check alone does not
        # prove account.cash itself is untouched, only that no row was
        # added/removed.
        cash_before = repos["account"].get_by_id("paper-id").cash

        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INSUFFICIENT_CASH,
            "BUY 100 @ 9500 exceeds 100,000 cash", action="BUY", quantity=100.0, requested_price=9500.0,
        )

        cash_after = repos["account"].get_by_id("paper-id").cash
        check(cash_before == cash_after, "Gate 8: Account.cash VALUE unchanged (not just row count)")


def scenario_pretrade_gate_9_insufficient_position():
    print("\n[Scenario 12] Gate 9 -- available position untuk SELL: SELL without position rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INSUFFICIENT_POSITION,
            "SELL with zero open position", action="SELL", quantity=100.0,
        )
        check(
            repos["position"].get_open_position("paper-id", "BBCA") is None,
            "Gate 9: still no Position for BBCA after the rejected SELL",
        )

    print("  [12b] SELL more than the open position quantity also rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        repos["position"].create(
            account_id="paper-id", symbol="BBCA", quantity=100.0,
            average_price=9000.0, realized_pnl=0.0, status="open",
        )

        # Activation 3.9 STEP 2: strengthen with explicit VALUE
        # assertions on the Position (quantity/average_price/
        # realized_pnl/status), not just the pre-existing row-count
        # check -- same rationale as Gate 8 above.
        position_before = repos["position"].get_open_position("paper-id", "BBCA")

        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INSUFFICIENT_POSITION,
            "SELL 200 with only 100 open", action="SELL", quantity=200.0,
        )

        position_after = repos["position"].get_open_position("paper-id", "BBCA")
        check(
            position_after.quantity == position_before.quantity
            and position_after.average_price == position_before.average_price
            and position_after.realized_pnl == position_before.realized_pnl
            and position_after.status == position_before.status,
            "Gate 9 (12b): Position VALUE unchanged (not just row count)",
        )


def scenario_pretrade_gate_10_duplicate_idempotency():
    print("\n[Scenario 13] Gate 10 -- duplicate request/idempotency: reused key rejected on 2nd call")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)

        first = engine.submit_order(**_default_kwargs(idempotency_key="dup-key"))
        check(isinstance(first, Trade), "first submission with a fresh key succeeds")

        before = _row_counts(repos)
        raised_reason = None
        try:
            engine.submit_order(**_default_kwargs(idempotency_key="dup-key"))
        except ValidationError as exc:
            raised_reason = exc.details.get("reason")
        check(raised_reason == PRETRADE_REASON_DUPLICATE_REQUEST, "second submission with the same key is rejected as duplicate")
        after = _row_counts(repos)
        check(before == after, "duplicate submission produced zero additional writes")

        trades = repos["trade"].list_all()
        check(len(trades) == 1, "exactly one Trade exists across both attempts -- duplicate never produced a second Trade")

    print("  [13b] blank idempotency_key also rejected as duplicate-reason")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_DUPLICATE_REQUEST,
            "blank idempotency_key", idempotency_key="   ",
        )


def scenario_pretrade_gate_11_risk_limit():
    print("\n[Scenario 14] Gate 11 -- risk limit: order value above ceiling rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_order_value=500_000.0)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_RISK_LIMIT_EXCEEDED,
            "100 * 9500 = 950,000 exceeds 500,000 limit", quantity=100.0, requested_price=9500.0,
        )


def scenario_pretrade_gate_12_kill_switch():
    print("\n[Scenario 15] Gate 12 -- kill switch: engaged switch blocks everything")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, kill_switch=True)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_KILL_SWITCH_ENGAGED,
            "kill switch engaged blocks an otherwise-valid order",
        )


def scenario_pretrade_gate_13_market_kill_switch():
    print("\n[Scenario 15b] Gate 13 -- market kill switch: halted active market blocks everything")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, halted_markets=frozenset({"idx"}))
        old_market = os.environ.get("AIOS_MARKET")
        os.environ["AIOS_MARKET"] = "idx"
        try:
            _expect_pretrade_rejection(
                engine, repos, PRETRADE_REASON_MARKET_KILL_SWITCH_ENGAGED,
                "market kill switch engaged for the active market ('idx') blocks an otherwise-valid order",
            )
        finally:
            if old_market is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = old_market


def scenario_pretrade_gate_13_market_kill_switch_other_market_unaffected():
    print("\n[Scenario 15c] Gate 13 -- market kill switch only blocks the halted market, not others")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, halted_markets=frozenset({"us"}))
        old_market = os.environ.get("AIOS_MARKET")
        os.environ["AIOS_MARKET"] = "idx"
        try:
            result = engine.submit_order(**_default_kwargs(idempotency_key="market-unaffected"))
            check(isinstance(result, Trade), "active market ('idx') not in halted set ('us'): order proceeds normally")
        finally:
            if old_market is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = old_market


def scenario_pretrade_gate_14_symbol_kill_switch():
    print("\n[Scenario 15d] Gate 14 -- symbol kill switch: halted symbol blocks that symbol")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, halted_symbols=frozenset({"BBCA"}))
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED,
            "symbol kill switch engaged for 'BBCA' blocks an otherwise-valid order",
        )


def scenario_pretrade_gate_14_symbol_kill_switch_case_insensitive():
    print("\n[Scenario 15e] Gate 14 -- symbol kill switch compares case-insensitively")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, halted_symbols=frozenset({"bbca"}))
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED,
            "symbol kill switch configured lower-case still blocks upper-case 'BBCA' request",
        )


def scenario_pretrade_gate_14_symbol_kill_switch_other_symbol_unaffected():
    print("\n[Scenario 15f] Gate 14 -- symbol kill switch only blocks the halted symbol, not others")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, halted_symbols=frozenset({"TLKM"}))
        result = engine.submit_order(**_default_kwargs(idempotency_key="symbol-unaffected"))
        check(isinstance(result, Trade), "'BBCA' not in halted symbol set ('TLKM'): order proceeds normally")


def scenario_pretrade_gate_15_daily_loss_limit():
    print("\n[Scenario 15g] Gate 15 -- daily loss kill switch: accumulated realized loss blocks new BUYs")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_daily_loss=1_000_000.0)
        # Seed a closed position carrying a realized loss that already
        # meets the configured ceiling -- mirrors how a real losing
        # SELL would have left Position.realized_pnl negative via
        # PositionManager._reduce_sell, but written directly here
        # since this test only needs the *read* side (the gate), not
        # a second full BUY->SELL round trip.
        repos["position"].create(
            account_id="paper-id",
            symbol="TLKM",
            quantity=0.0,
            average_price=0.0,
            realized_pnl=-1_500_000.0,
            status="closed",
        )
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_DAILY_LOSS_LIMIT_EXCEEDED,
            "accumulated realized loss (1,500,000) >= daily loss limit (1,000,000) blocks a new BUY",
        )


def scenario_pretrade_gate_15_daily_loss_limit_does_not_block_sell():
    print("\n[Scenario 15h] Gate 15 -- daily loss kill switch never blocks SELL")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_daily_loss=1_000_000.0)
        repos["position"].create(
            account_id="paper-id",
            symbol="TLKM",
            quantity=0.0,
            average_price=0.0,
            realized_pnl=-1_500_000.0,
            status="closed",
        )
        # A separate, real open BBCA position so the SELL below has
        # something to reduce -- gate 9 ("available position untuk
        # SELL") must also pass for this to reach gate 15.
        repos["position"].create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )
        result = engine.submit_order(**_default_kwargs(
            action="SELL", idempotency_key="loss-limit-sell-allowed",
        ))
        check(isinstance(result, Trade), "daily loss limit already exceeded, but SELL still proceeds (closes/reduces exposure)")


def scenario_pretrade_gate_15_daily_loss_limit_not_yet_breached():
    print("\n[Scenario 15i] Gate 15 -- daily loss kill switch does not fire below the ceiling")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_daily_loss=1_000_000.0)
        repos["position"].create(
            account_id="paper-id",
            symbol="TLKM",
            quantity=0.0,
            average_price=0.0,
            realized_pnl=-500_000.0,
            status="closed",
        )
        result = engine.submit_order(**_default_kwargs(idempotency_key="loss-limit-not-breached"))
        check(isinstance(result, Trade), "realized loss (500,000) below limit (1,000,000): BUY proceeds normally")


def scenario_pretrade_gate_16_max_position_value():
    print("\n[Scenario 15j] Gate 16 -- position kill switch: resulting position value ceiling blocks a BUY")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_position_value=500_000.0)
        # default kwargs: BBCA, quantity=100, requested_price=9500 ->
        # resulting value 950,000 > 500,000 ceiling, no existing position.
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_MAX_POSITION_VALUE_EXCEEDED,
            "100 * 9500 = 950,000 resulting position value exceeds 500,000 ceiling",
        )


def scenario_pretrade_gate_16_max_position_value_includes_existing_position():
    print("\n[Scenario 15k] Gate 16 -- position kill switch adds this order onto an existing open position")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_position_value=2_000_000.0)
        repos["position"].create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )
        # existing 100 + order 100 = 200 shares * 9500 = 1,900,000 <= 2,000,000: passes.
        result = engine.submit_order(**_default_kwargs(idempotency_key="position-limit-ok"))
        check(isinstance(result, Trade), "(100 existing + 100 new) * 9500 = 1,900,000 <= 2,000,000 ceiling: BUY proceeds")


def scenario_pretrade_gate_16_max_position_value_does_not_block_sell():
    print("\n[Scenario 15l] Gate 16 -- position kill switch never blocks SELL")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, max_position_value=500_000.0)
        repos["position"].create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )
        result = engine.submit_order(**_default_kwargs(
            action="SELL", idempotency_key="position-limit-sell-allowed",
        ))
        check(isinstance(result, Trade), "position value ceiling already exceeded by holdings, but SELL still proceeds")


def scenario_gate_13_16_disabled_by_default():
    print("\n[Scenario 15m] Gates 13-16 are no-ops when not configured (defaults preserve pre-8.4 behavior)")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)  # no halted_markets/halted_symbols/max_daily_loss/max_position_value
        result = engine.submit_order(**_default_kwargs(idempotency_key="defaults-unaffected"))
        check(isinstance(result, Trade), "engine built with no Activation 8.4 config: order proceeds exactly as before")


def scenario_gate_order_first_match_wins():
    print("\n[Scenario 16] gate order: account check (gate 1) fires before evidence check (gate 2)")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        raised_reason = None
        try:
            engine.submit_order(**_default_kwargs(account_id="ghost-account", signal_evidence=None))
        except ValidationError as exc:
            raised_reason = exc.details.get("reason")
        check(
            raised_reason == PRETRADE_REASON_ACCOUNT_NOT_FOUND,
            "both gate 1 and gate 2 would fail, but gate 1 (account) fires first",
        )


def scenario_engine_holds_only_its_collaborators():
    print("\n[Scenario 17] engine depends on exactly its 5 Repository/Service collaborators + 2 config values + 1 policy")
    with tempfile.TemporaryDirectory() as tmp:
        engine, _ = _build_engine(tmp)
        attrs = sorted(vars(engine).keys())
        # Activation 3.3 STEP 2 (explicit contract change): the engine
        # gained one additional collaborator, _execution_policy (the
        # canonical Business.execution_policy_config.ExecutionPolicy it
        # reads lot_size from for gate 6). Activation 3.5 STEP 1 adds
        # one further collaborator, _account_balance_service (the
        # canonical Business.account_balance_service.AccountBalanceService
        # it calls apply_trade() on after a successful execute_order()).
        # Activation 3.5 STEP 2 adds one further collaborator,
        # _position_manager (the canonical
        # Business.position_manager.PositionManager it calls
        # apply_trade() on, immediately after
        # _account_balance_service.apply_trade()). The notification
        # wiring STEP adds two further collaborators,
        # _notification_builder/_notification_manager (the canonical
        # Business.notification_builder.NotificationBuilder /
        # Business.notification_manager.NotificationManager it calls
        # build_order_executed()/notify() on, best-effort, after the
        # idempotency key is recorded -- see PaperTradingEngine's own
        # module/constructor docstrings). Verified during Activation
        # 6.3 (VERIFY ONLY): this assertion had drifted stale (missing
        # both notification attributes even though the constructor
        # already accepted/stored them before 6.3) -- corrected here,
        # no production code changed. No other Repository/Service was
        # added.
        # Activation 7 Blocker #4 ("persist user_approval so it is
        # auditable from the database") adds exactly one further
        # attribute, _order_approval_repository -- the optional
        # (defaults to None) OrderApprovalRepository this engine
        # writes one best-effort audit row to, after the idempotency
        # key is recorded, mirroring _notification_builder/
        # _notification_manager's own additive precedent above. No
        # other Repository/Service was added, and gate 3/execution
        # order/transaction boundary are unchanged.
        # Activation 8.4 ("kill switch") adds four further plain
        # config-value attributes -- _halted_markets/_halted_symbols/
        # _max_daily_loss/_max_position_value, backing pre-trade gates
        # 13-16 -- mirroring _kill_switch_engaged/_max_order_value's
        # own "plain value, not a live callback" construct-once
        # pattern. No new Repository/Service collaborator was added by
        # this Activation (gates 15/16 reuse the already-held
        # _position_repository); only these four extra config values.
        check(
            attrs == sorted([
                "_order_lifecycle_service",
                "_execution_service",
                "_account_repository",
                "_position_repository",
                "_order_idempotency_repository",
                "_kill_switch_engaged",
                "_max_order_value",
                "_execution_policy",
                "_account_balance_service",
                "_position_manager",
                "_notification_builder",
                "_notification_manager",
                "_order_approval_repository",
                "_halted_markets",
                "_halted_symbols",
                "_max_daily_loss",
                "_max_position_value",
            ]),
            "PaperTradingEngine holds exactly its 5 collaborators + 2 config values "
            "+ 1 execution policy + 1 account balance service + 1 position manager "
            "+ 1 notification builder + 1 notification manager "
            "+ 1 order approval repository + 4 Activation 8.4 kill-switch config "
            "values, nothing else",
        )


def scenario_restart_persistence():
    print("\n[Scenario 18] restart persistence: reopening the same DB file preserves state")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        result = engine.submit_order(**_default_kwargs(idempotency_key="restart-key"))

        # Activation 3.9 STEP 2: capture Account.cash and the full
        # Position row BEFORE the restart, so they can be compared
        # against the state read back through a brand new connection
        # below -- the STEP 1 audit (sec. 7) found this scenario
        # previously verified only Order/Trade/idempotency-key
        # durability, not Account/Position.
        account_before_restart = repos["account"].get_by_id("paper-id")
        position_before_restart = repos["position"].get_open_position("paper-id", "BBCA")

        # Simulate an application restart: build a brand new engine/repo
        # graph over the SAME db file, nothing shared in memory.
        cfg = DatabaseConfig(db_path=Path(tmp) / "paper_trading_engine.db")
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        account_repo2 = AccountRepository(manager2)
        position_repo2 = PositionRepository(manager2)
        order_repo2 = OrderRepository(manager2)
        trade_repo2 = TradeRepository(manager2)
        idem_repo2 = OrderIdempotencyRepository(manager2)

        order_after_restart = order_repo2.get_by_id(result.order_id)
        check(order_after_restart is not None and order_after_restart.status == "FILLED", "Order survives a fresh connection to the same DB file, still FILLED")

        trades_after_restart = trade_repo2.list_by_order(result.order_id)
        check(len(trades_after_restart) == 1, "Trade survives a fresh connection to the same DB file")

        idem_after_restart = idem_repo2.get_by_key("restart-key")
        check(idem_after_restart is not None, "idempotency key survives a fresh connection to the same DB file")

        account_after_restart = account_repo2.get_by_id("paper-id")
        check(
            account_after_restart is not None and account_after_restart.cash == account_before_restart.cash,
            "Account.cash survives a fresh connection to the same DB file, identical value",
        )

        position_after_restart = position_repo2.get_open_position("paper-id", "BBCA")
        check(
            position_after_restart is not None
            and position_after_restart.quantity == position_before_restart.quantity
            and position_after_restart.average_price == position_before_restart.average_price
            and position_after_restart.realized_pnl == position_before_restart.realized_pnl
            and position_after_restart.status == position_before_restart.status,
            "Position survives a fresh connection to the same DB file, identical value",
        )


def main() -> int:
    scenario_happy_path_buy_returns_trade()
    scenario_happy_path_sell_with_position_returns_trade()
    scenario_rejected_order_raises_and_never_executes()
    scenario_pretrade_gate_1_account_not_found()
    scenario_pretrade_gate_2_evidence_missing()
    scenario_pretrade_gate_3_approval_missing()
    scenario_pretrade_gate_4_invalid_symbol()
    scenario_pretrade_gate_5_invalid_quantity()
    scenario_pretrade_gate_6_invalid_lot_size()
    scenario_pretrade_gate_7_invalid_price()
    scenario_pretrade_gate_8_insufficient_cash()
    scenario_pretrade_gate_9_insufficient_position()
    scenario_pretrade_gate_10_duplicate_idempotency()
    scenario_pretrade_gate_11_risk_limit()
    scenario_pretrade_gate_12_kill_switch()
    scenario_pretrade_gate_13_market_kill_switch()
    scenario_pretrade_gate_13_market_kill_switch_other_market_unaffected()
    scenario_pretrade_gate_14_symbol_kill_switch()
    scenario_pretrade_gate_14_symbol_kill_switch_case_insensitive()
    scenario_pretrade_gate_14_symbol_kill_switch_other_symbol_unaffected()
    scenario_pretrade_gate_15_daily_loss_limit()
    scenario_pretrade_gate_15_daily_loss_limit_does_not_block_sell()
    scenario_pretrade_gate_15_daily_loss_limit_not_yet_breached()
    scenario_pretrade_gate_16_max_position_value()
    scenario_pretrade_gate_16_max_position_value_includes_existing_position()
    scenario_pretrade_gate_16_max_position_value_does_not_block_sell()
    scenario_gate_13_16_disabled_by_default()
    scenario_gate_order_first_match_wins()
    scenario_engine_holds_only_its_collaborators()
    scenario_restart_persistence()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 3.2 + 8.4 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())