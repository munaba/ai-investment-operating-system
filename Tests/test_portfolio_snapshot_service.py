"""Standalone regression checks for
``Business.portfolio_snapshot_service.PortfolioSnapshotService``
(Activation 5.2).

Proves against a real on-disk SQLite file (real ``AccountRepository``/
``PositionRepository``/``PortfolioSnapshotRepository`` + real
migrations, real ``PositionManager`` for BUY/SELL setup, real
``UnrealizedPnLEngine``/``MaximumDrawdownEngine``):

* cash is read verbatim from the real Account;
* market_value/unrealized_pnl are computed from real open positions
  via the real, unmodified UnrealizedPnLEngine formula;
* realized_pnl sums real Position.realized_pnl across all positions
  (open + closed) for the account;
* equity == cash + market_value (not Account.equity, which is stale);
* exposure is always None (GAP, not fabricated);
* drawdown is computed via the real MaximumDrawdownEngine over a real
  equity curve built from persisted prior snapshots;
* the snapshot is actually persisted (row exists after a real
  reconnect / restart);
* taking a snapshot creates no Order and no Trade row (read-only /
  observational);
* an account with no positions still produces a valid, non-fabricated
  snapshot (cash only, zero market_value/unrealized_pnl).

Market price is supplied via the same small, duck-typed test double
(``_FixedPriceTool``) already used by
``Tests/activation_3_7_step4_proof.py`` -- the real
``MarketPriceTool`` in production is never modified.

Run directly with ``python Tests/test_portfolio_snapshot_service.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.portfolio_snapshot_service import PortfolioSnapshotService  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import PortfolioSnapshot, Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository  # noqa: E402
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


class _FixedPriceTool:
    """Test double for ``MarketPriceTool`` -- same ``execute(context)``
    contract, fixed price instead of a live network/yfinance call.
    Mirrors ``Tests/activation_3_7_step4_proof.py``'s own test double
    exactly.
    """

    def __init__(self, price):
        self._price = price

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": self._price, "trend": "manual-fixture"},
            error=None,
            metadata={},
        )


def _trade(trade_id, symbol="BBCA", account_id="paper-id", action="BUY",
           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0,
           executed_at="2026-08-05T10:00:00+00:00"):
    return Trade(
        trade_id=trade_id, order_id=trade_id, account_id=account_id, symbol=symbol,
        action=action, quantity=quantity, fill_price=fill_price, fee=fee, tax=tax,
        executed_at=executed_at,
    )


def _build(tmp_dir: str, db_name: str, price: float, account_id: str = "paper-id"):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id=account_id, account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )
    position_repo = PositionRepository(manager)
    position_manager = PositionManager(position_repo)
    portfolio_snapshot_repo = PortfolioSnapshotRepository(manager)

    service = PortfolioSnapshotService(
        account_repository=account_repo,
        position_repository=position_repo,
        unrealized_pnl_engine=UnrealizedPnLEngine(_FixedPriceTool(price)),
        maximum_drawdown_engine=MaximumDrawdownEngine(),
        portfolio_snapshot_repository=portfolio_snapshot_repo,
    )
    return db, cfg, manager, account_repo, position_repo, position_manager, portfolio_snapshot_repo, service


def scenario_snapshot_with_no_positions():
    print("\n[Scenario 1] Account with no positions: cash-only, zero market_value/unrealized_pnl")
    with tempfile.TemporaryDirectory() as tmp:
        db, *_rest, service = _build(tmp, "pf_svc_empty.db", price=10_000.0)
        try:
            snapshot = service.take_snapshot("paper-id")
            check(isinstance(snapshot, PortfolioSnapshot), "take_snapshot() returns a PortfolioSnapshot")
            check(snapshot.cash == 100_000_000.0, "cash read verbatim from real Account.cash")
            check(snapshot.market_value == 0.0, "market_value is 0.0 with no open positions (real, not fabricated)")
            check(snapshot.unrealized_pnl == 0.0, "unrealized_pnl is 0.0 with no open positions")
            check(snapshot.realized_pnl == 0.0, "realized_pnl is 0.0 with no positions at all")
            check(snapshot.equity == 100_000_000.0, "equity == cash + market_value == cash when flat")
            check(snapshot.exposure is None, "exposure is None (GAP, never fabricated)")
            check(snapshot.drawdown == 0.0, "drawdown is 0.0 on the very first snapshot (single equity point)")
            check(bool(snapshot.timestamp), "timestamp is populated")
        finally:
            db.disconnect()


def scenario_snapshot_with_open_position_market_up():
    print("\n[Scenario 2] One open BUY position, market price above entry")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, "pf_svc_open_up.db", price=9_800.0
        )
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            account = account_repo.get_by_id("paper-id")
            account_repo.update_balances(
                account_id="paper-id",
                cash=account.cash - (100.0 * 9500.0),
                equity=account.equity,
                buying_power=account.buying_power,
            )

            snapshot = service.take_snapshot("paper-id")

            expected_cash = 100_000_000.0 - (100.0 * 9500.0)
            expected_market_value = 100.0 * 9800.0
            expected_unrealized = (9800.0 - 9500.0) * 100.0

            check(snapshot.cash == expected_cash, f"cash reflects the real Account after the BUY (got {snapshot.cash})")
            check(snapshot.market_value == expected_market_value, f"market_value == qty * real market_price (got {snapshot.market_value})")
            check(snapshot.unrealized_pnl == expected_unrealized, f"unrealized_pnl matches UnrealizedPnLEngine's own formula (got {snapshot.unrealized_pnl})")
            check(snapshot.realized_pnl == 0.0, "realized_pnl is 0.0 -- no SELL has happened yet")
            check(snapshot.equity == expected_cash + expected_market_value, "equity == cash + market_value exactly")
            check(snapshot.equity != account.equity or account.equity == expected_cash + expected_market_value,
                  "equity is NOT silently copied from the stale Account.equity field")
        finally:
            db.disconnect()


def scenario_realized_pnl_after_sell():
    print("\n[Scenario 3] BUY then partial SELL: realized_pnl reflects real Position.realized_pnl")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, "pf_svc_sell.db", price=9_900.0
        )
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            position_manager.apply_trade(_trade(
                2, action="SELL", quantity=40.0, fill_price=9700.0,
                executed_at="2026-08-05T11:00:00+00:00",
            ))

            position = position_repo.get_open_position("paper-id", "BBCA")
            expected_realized = (9700.0 - 9500.0) * 40.0
            check(position.realized_pnl == expected_realized, "sanity: Position.realized_pnl matches PositionManager's own formula")

            snapshot = service.take_snapshot("paper-id")
            check(snapshot.realized_pnl == expected_realized, f"snapshot.realized_pnl == real Position.realized_pnl (got {snapshot.realized_pnl})")

            remaining_qty = 60.0
            expected_market_value = remaining_qty * 9900.0
            expected_unrealized = (9900.0 - 9500.0) * remaining_qty
            check(snapshot.market_value == expected_market_value, "market_value reflects the remaining open quantity only")
            check(snapshot.unrealized_pnl == expected_unrealized, "unrealized_pnl reflects the remaining open quantity only")
        finally:
            db.disconnect()


def scenario_drawdown_uses_real_equity_history():
    print("\n[Scenario 4] drawdown is computed by MaximumDrawdownEngine over real persisted equity history")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, "pf_svc_drawdown.db", price=9_500.0
        )
        try:
            # Snapshot 1: flat, equity = 100,000,000 (peak)
            s1 = service.take_snapshot("paper-id")
            check(s1.drawdown == 0.0, "first snapshot: drawdown 0.0 (single point)")

            # BUY, then price drops hard -> equity falls well below peak
            position_manager.apply_trade(_trade(1, action="BUY", quantity=1000.0, fill_price=9500.0))
            account = account_repo.get_by_id("paper-id")
            account_repo.update_balances(
                account_id="paper-id", cash=account.cash - (1000.0 * 9500.0),
                equity=account.equity, buying_power=account.buying_power,
            )
            service._unrealized_pnl_engine = UnrealizedPnLEngine(_FixedPriceTool(8000.0))
            s2 = service.take_snapshot("paper-id")

            equity_curve = [row.equity for row in snap_repo.list_by_account("paper-id")]
            expected_drawdown = MaximumDrawdownEngine().calculate(equity_curve[:-1] + [s2.equity])
            # recompute independently to cross-check against the engine, not against the service's own output
            independent_curve = [s1.equity, s2.equity]
            independent = MaximumDrawdownEngine().calculate(independent_curve)
            check(s2.drawdown == independent.maximum_drawdown, f"drawdown matches an independent MaximumDrawdownEngine computation over real equity history (got {s2.drawdown}, expected {independent.maximum_drawdown})")
            check(s2.drawdown > 0.0, "drawdown is positive after a real equity decline")
        finally:
            db.disconnect()


def scenario_persisted_and_readable_after_restart():
    print("\n[Scenario 5] snapshot is persisted and readable after a real reconnect")
    with tempfile.TemporaryDirectory() as tmp:
        db_name = "pf_svc_restart.db"
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, db_name, price=9_500.0
        )
        snapshot = service.take_snapshot("paper-id")
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=cfg.db_path))
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg)
            repo2 = PortfolioSnapshotRepository(manager2)
            reread = repo2.get_by_id(snapshot.snapshot_id)
            check(reread is not None, "snapshot exists after process restart / fresh connection")
            check(reread.cash == snapshot.cash, "cash value survives restart")
            check(reread.equity == snapshot.equity, "equity value survives restart")
        finally:
            db2.disconnect()


def scenario_read_only_creates_no_order_or_trade():
    print("\n[Scenario 6] take_snapshot() creates no Order and no Trade (read-only/observational)")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, "pf_svc_readonly.db", price=9_500.0
        )
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))

            order_repo = OrderRepository(manager)
            trade_repo = TradeRepository(manager)
            orders_before = len(order_repo.list_all())
            trades_before = len(trade_repo.list_all())

            service.take_snapshot("paper-id")
            service.take_snapshot("paper-id")
            service.take_snapshot("paper-id")

            orders_after = len(order_repo.list_all())
            trades_after = len(trade_repo.list_all())

            check(orders_after == orders_before, f"no Order rows created by take_snapshot() (before={orders_before}, after={orders_after})")
            check(trades_after == trades_before, f"no Trade rows created by take_snapshot() (before={trades_before}, after={trades_after})")

            snapshots = snap_repo.list_by_account("paper-id")
            check(len(snapshots) == 3, "three snapshot rows were persisted (append-only, one per call)")
        finally:
            db.disconnect()


def scenario_unknown_account_raises():
    print("\n[Scenario 7] Unknown account raises ValidationError, no partial write")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, snap_repo, service = _build(
            tmp, "pf_svc_unknown.db", price=9_500.0
        )
        try:
            raised = False
            try:
                service.take_snapshot("does-not-exist")
            except ValidationError:
                raised = True
            check(raised, "take_snapshot() raises ValidationError for an unknown account_id")
            check(snap_repo.list_all() == [], "no snapshot row was persisted for the failed attempt")
        finally:
            db.disconnect()


def scenario_no_scheduler_or_background_execution():
    print("\n[Scenario 8] No scheduler/daemon/background surface exists on the service")
    forbidden_substrings = ("schedule", "daemon", "background", "loop_forever", "cron")
    import inspect
    source = inspect.getsource(PortfolioSnapshotService)
    for token in forbidden_substrings:
        check(token not in source.lower(), f"PortfolioSnapshotService source contains no '{token}' concept")


def main() -> int:
    scenario_snapshot_with_no_positions()
    scenario_snapshot_with_open_position_market_up()
    scenario_realized_pnl_after_sell()
    scenario_drawdown_uses_real_equity_history()
    scenario_persisted_and_readable_after_restart()
    scenario_read_only_creates_no_order_or_trade()
    scenario_unknown_account_raises()
    scenario_no_scheduler_or_background_execution()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
