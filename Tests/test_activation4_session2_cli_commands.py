"""Standalone regression checks for Activation 4 Session 2's new CLI
commands in ``main.py``:

    * ``portfolio``
    * ``account``
    * ``orders``
    * ``trades``

Covers the proof points the Session 2 brief requires:

    1. ``portfolio`` reads real ``Position`` rows via
       ``PositionRepository.list_by_account()`` -- never a fabricated
       list -- and shows real unrealized P/L (via the real,
       unmodified ``UnrealizedPnLEngine`` against a fake
       ``MarketPriceTool``) for ``OPEN`` positions, with ``N/A`` when
       no current price is available (never invented).
    2. ``account`` reads the real ``Account`` row via
       ``AccountRepository.get_by_id()``.
    3. ``orders`` reads real ``Order`` rows via
       ``OrderRepository.list_by_account()``.
    4. ``trades`` reads real ``Trade`` rows via
       ``TradeRepository.list_by_account()``.
    5. All four commands are read-only: none of them call
       ``paper_trading_engine.submit_order()`` or write anything.

Run directly with
``python Tests/test_activation4_session2_cli_commands.py`` -- no
external test framework required, matching
``test_activation4_session1_cli_commands.py``. Uses only stdlib
``unittest.mock`` plus hand-rolled fakes for ``ApplicationGraph``
collaborators -- never a real database/network call.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.models import Account, Order, Position, Trade  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePositionRepository:
    def __init__(self, positions: Optional[List[Position]] = None) -> None:
        self._positions = positions or []

    def list_by_account(self, account_id: str) -> List[Position]:
        return [p for p in self._positions if p.account_id == account_id]


class FakeAccountRepository:
    def __init__(self, account: Optional[Account] = None) -> None:
        self._account = account

    def get_by_id(self, account_id: str) -> Optional[Account]:
        if self._account is not None and self._account.account_id == account_id:
            return self._account
        return None


class FakeOrderRepository:
    def __init__(self, orders: Optional[List[Order]] = None) -> None:
        self._orders = orders or []

    def list_by_account(self, account_id: str) -> List[Order]:
        return [o for o in self._orders if o.account_id == account_id]


class FakeTradeRepository:
    def __init__(self, trades: Optional[List[Trade]] = None) -> None:
        self._trades = trades or []

    def list_by_account(self, account_id: str) -> List[Trade]:
        return [t for t in self._trades if t.account_id == account_id]


class FakeMarketPriceTool:
    """Stands in for ``Orchestration.market_price_tool.MarketPriceTool``
    -- returns a fixed price per symbol (never a real network call).
    A symbol absent from ``prices`` simulates "no current price
    available" (``price: None``), mirroring the real Tool's failure
    shape.
    """

    def __init__(self, prices: Optional[dict] = None) -> None:
        self._prices = prices or {}

    def execute(self, context: Any) -> ToolResult:
        symbol = context.parameters.get("symbol")
        price = self._prices.get(symbol)
        return ToolResult(success=price is not None, output={"symbol": symbol, "price": price, "trend": "unknown"}, error=None, metadata={})


class FakeApp:
    """Stands in for ``Core.composition_root.ApplicationGraph`` --
    only the attributes each command under test actually reads.
    """

    def __init__(
        self,
        position_repository: Optional[FakePositionRepository] = None,
        account_repository: Optional[FakeAccountRepository] = None,
        order_repository: Optional[FakeOrderRepository] = None,
        trade_repository: Optional[FakeTradeRepository] = None,
        unrealized_pnl_engine: Optional[UnrealizedPnLEngine] = None,
    ) -> None:
        self.position_repository = position_repository or FakePositionRepository()
        self.account_repository = account_repository or FakeAccountRepository()
        self.order_repository = order_repository or FakeOrderRepository()
        self.trade_repository = trade_repository or FakeTradeRepository()
        # Real UnrealizedPnLEngine over a fake (network-free) price
        # tool -- proves the CLI uses the actual, LOCKED engine and
        # its actual formula, not a reimplementation.
        self.unrealized_pnl_engine = unrealized_pnl_engine or UnrealizedPnLEngine(FakeMarketPriceTool())
        self.paper_trading_engine = None  # must never be called by these commands


def _account(cash: float = 100_000_000.0, account_id: str = "paper") -> Account:
    return Account(
        account_id=account_id,
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _position(
    symbol: str = "BBCA",
    quantity: float = 100.0,
    average_price: float = 9000.0,
    realized_pnl: float = 0.0,
    status: str = "open",  # Database.position_constants.POSITION_STATUSES is lowercase
    account_id: str = "paper",
    position_id: int = 1,
) -> Position:
    return Position(
        position_id=position_id,
        account_id=account_id,
        symbol=symbol,
        quantity=quantity,
        average_price=average_price,
        realized_pnl=realized_pnl,
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _order(
    order_id: int = 1,
    symbol: str = "BBCA",
    action: str = "BUY",
    status: str = "FILLED",
    account_id: str = "paper",
) -> Order:
    return Order(
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=100.0,
        requested_price=9000.0,
        filled_price=9000.0,
        filled_quantity=100.0,
        status=status,
        reason="filled",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        filled_at="2026-01-01T00:00:00+00:00",
    )


def _trade(trade_id: int = 1, symbol: str = "BBCA", action: str = "BUY", account_id: str = "paper") -> Trade:
    return Trade(
        trade_id=trade_id,
        order_id=1,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=100.0,
        fill_price=9000.0,
        fee=0.0,
        tax=0.0,
        executed_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# 1. portfolio
# ---------------------------------------------------------------------------


def scenario_portfolio_reads_real_positions():
    print("\n[1] 'portfolio' reads real Position rows via PositionRepository.list_by_account()")
    repo = FakePositionRepository([_position(symbol="BBCA"), _position(symbol="TLKM", position_id=2, account_id="other")])
    app = FakeApp(position_repository=repo, unrealized_pnl_engine=UnrealizedPnLEngine(FakeMarketPriceTool({"BBCA": 9500.0})))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_portfolio_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is 0")
    check("BBCA" in output, "own-account position (BBCA) is shown")
    check("TLKM" not in output, "another account's position (TLKM) is NOT shown")


def scenario_portfolio_shows_real_unrealized_pnl_for_open_position():
    print("\n[2] 'portfolio' shows real unrealized P/L for an OPEN position via the real UnrealizedPnLEngine")
    position = _position(symbol="BBCA", quantity=100.0, average_price=9000.0, status="open")
    repo = FakePositionRepository([position])
    engine = UnrealizedPnLEngine(FakeMarketPriceTool({"BBCA": 9500.0}))
    app = FakeApp(position_repository=repo, unrealized_pnl_engine=engine)

    with redirect_stdout(io.StringIO()) as buf:
        main._run_portfolio_command(app, [])

    output = buf.getvalue()
    expected_pnl = (9500.0 - 9000.0) * 100.0
    check(f"market_price=9500.0" in output, "real current market price is shown")
    check(f"unrealized_pnl={expected_pnl}" in output, "unrealized P/L matches the engine's own formula exactly")


def scenario_portfolio_shows_na_when_no_market_price_available():
    print("\n[3] 'portfolio' shows N/A (never a fabricated number) when no current price is available")
    position = _position(symbol="UNKNOWN", status="open")
    repo = FakePositionRepository([position])
    engine = UnrealizedPnLEngine(FakeMarketPriceTool({}))  # no price for UNKNOWN
    app = FakeApp(position_repository=repo, unrealized_pnl_engine=engine)

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_portfolio_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is still 0 (a missing price is not a command failure)")
    check("N/A" in output, "unrealized fields are shown as N/A, never invented")


def scenario_portfolio_closed_position_skips_unrealized_lookup():
    print("\n[4] 'portfolio' never calls UnrealizedPnLEngine for a CLOSED position")
    position = _position(symbol="BBCA", status="closed", realized_pnl=12345.0)
    repo = FakePositionRepository([position])

    class ExplodingPnLEngine:
        def calculate(self, position):
            raise AssertionError("UnrealizedPnLEngine.calculate() must not be called for a CLOSED position")

    app = FakeApp(position_repository=repo, unrealized_pnl_engine=ExplodingPnLEngine())

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_portfolio_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is 0")
    check("realized_pnl=12345.0" in output, "the real, settled realized_pnl is shown")


def scenario_portfolio_empty():
    print("\n[5] 'portfolio' with no positions prints a clear empty message, not an error")
    app = FakeApp(position_repository=FakePositionRepository([]))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_portfolio_command(app, [])

    check(exit_code == 0, "exit code is 0")
    check("No positions." in buf.getvalue(), "empty portfolio message shown")


# ---------------------------------------------------------------------------
# 2. account
# ---------------------------------------------------------------------------


def scenario_account_reads_real_account():
    print("\n[6] 'account' reads the real Account row via AccountRepository.get_by_id()")
    account = _account(cash=87_500_000.0)
    app = FakeApp(account_repository=FakeAccountRepository(account))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_account_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is 0")
    check("cash         : 87500000.0" in output, "real cash figure is shown, not a hardcoded/zero placeholder")
    check("paper" in output, "account_id is shown")


def scenario_account_missing():
    print("\n[7] 'account' when the paper account does not exist yet")
    app = FakeApp(account_repository=FakeAccountRepository(None))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_account_command(app, [])

    check(exit_code == 1, "exit code is 1 (not found)")
    check("init" in buf.getvalue(), "message points the user at 'python main.py init'")


# ---------------------------------------------------------------------------
# 3. orders
# ---------------------------------------------------------------------------


def scenario_orders_reads_real_orders():
    print("\n[8] 'orders' reads real Order rows via OrderRepository.list_by_account()")
    orders = [_order(order_id=1, symbol="BBCA"), _order(order_id=2, symbol="TLKM", account_id="other")]
    app = FakeApp(order_repository=FakeOrderRepository(orders))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_orders_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is 0")
    check("order_id=1" in output and "BBCA" in output, "own-account order is shown")
    check("TLKM" not in output, "another account's order is NOT shown")
    check("filled_price=9000.0" in output, "real filled_price is shown")


def scenario_orders_empty():
    print("\n[9] 'orders' with no orders prints a clear empty message")
    app = FakeApp(order_repository=FakeOrderRepository([]))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_orders_command(app, [])

    check(exit_code == 0, "exit code is 0")
    check("No orders." in buf.getvalue(), "empty orders message shown")


# ---------------------------------------------------------------------------
# 4. trades
# ---------------------------------------------------------------------------


def scenario_trades_reads_real_trades():
    print("\n[10] 'trades' reads real Trade rows via TradeRepository.list_by_account()")
    trades = [_trade(trade_id=1, symbol="BBCA"), _trade(trade_id=2, symbol="TLKM", account_id="other")]
    app = FakeApp(trade_repository=FakeTradeRepository(trades))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_trades_command(app, [])

    output = buf.getvalue()
    check(exit_code == 0, "exit code is 0")
    check("trade_id=1" in output and "BBCA" in output, "own-account trade is shown")
    check("TLKM" not in output, "another account's trade is NOT shown")
    check("fill_price=9000.0" in output, "real fill_price is shown")


def scenario_trades_empty():
    print("\n[11] 'trades' with no trades prints a clear empty message")
    app = FakeApp(trade_repository=FakeTradeRepository([]))

    with redirect_stdout(io.StringIO()) as buf:
        exit_code = main._run_trades_command(app, [])

    check(exit_code == 0, "exit code is 0")
    check("No trades." in buf.getvalue(), "empty trades message shown")


# ---------------------------------------------------------------------------
# 5. read-only proof
# ---------------------------------------------------------------------------


def scenario_all_four_commands_never_touch_paper_trading_engine():
    print("\n[12] portfolio/account/orders/trades never touch app.paper_trading_engine (read-only)")
    app = FakeApp(
        position_repository=FakePositionRepository([_position()]),
        account_repository=FakeAccountRepository(_account()),
        order_repository=FakeOrderRepository([_order()]),
        trade_repository=FakeTradeRepository([_trade()]),
    )
    app.paper_trading_engine = None  # any access at all would raise AttributeError-free None misuse below

    class Boom:
        def submit_order(self, **kwargs):
            raise AssertionError("submit_order() must never be called by a read-only command")

    app.paper_trading_engine = Boom()

    with redirect_stdout(io.StringIO()):
        main._run_portfolio_command(app, [])
        main._run_account_command(app, [])
        main._run_orders_command(app, [])
        main._run_trades_command(app, [])

    check(True, "no command called paper_trading_engine.submit_order() (would have raised AssertionError above)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS = [
    scenario_portfolio_reads_real_positions,
    scenario_portfolio_shows_real_unrealized_pnl_for_open_position,
    scenario_portfolio_shows_na_when_no_market_price_available,
    scenario_portfolio_closed_position_skips_unrealized_lookup,
    scenario_portfolio_empty,
    scenario_account_reads_real_account,
    scenario_account_missing,
    scenario_orders_reads_real_orders,
    scenario_orders_empty,
    scenario_trades_reads_real_trades,
    scenario_trades_empty,
    scenario_all_four_commands_never_touch_paper_trading_engine,
]

if __name__ == "__main__":
    for scenario in _SCENARIOS:
        scenario()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 4 SESSION 2 CLI COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
        sys.exit(1)