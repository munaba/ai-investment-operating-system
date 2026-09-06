"""Activation 3.5 STEP 3 -- real-SQLite acceptance proof.

Proves gate 8 (available cash) now uses the identical required_cash
formula as AccountBalanceService.apply_trade() (gross_value + fee +
tax), against a real SQLite file on disk -- not mocks, not :memory:.

Run: python Tests/activation_3_5_step3_proof.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_policy_config import ExecutionPolicy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_INSUFFICIENT_CASH,
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


def _build(tmp_dir: str, *, cash: float, buy_fee_rate: float, sell_fee_rate: float = 0.0, sell_tax_rate: float = 0.0):
    """Build a full, real-SQLite-backed graph, with ONE shared
    ExecutionPolicy instance handed to both ExecutionService and
    PaperTradingEngine -- exactly as Core.composition_root wires it.
    """
    db_path = Path(tmp_dir) / "acceptance.db"
    cfg = DatabaseConfig(db_path=db_path)
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
        account_id="paper-id", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=cash, equity=cash, buying_power=cash,
    )

    execution_policy = ExecutionPolicy(
        buy_fee_rate=buy_fee_rate, sell_fee_rate=sell_fee_rate, sell_tax_rate=sell_tax_rate,
    )

    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo, execution_policy)
    account_balance_service = AccountBalanceService(account_repo)

    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
        execution_policy=execution_policy,
        account_balance_service=account_balance_service,
    )

    repos = {
        "account": account_repo, "position": position_repo, "order": order_repo,
        "trade": trade_repo, "idempotency": idempotency_repo,
    }
    return db_path, engine, repos


def _row_counts(repos, idempotency_key: str | None = None) -> dict:
    return {
        "orders": len(repos["order"].list_all()),
        "trades": len(repos["trade"].list_all()),
        "idempotency": (
            0 if idempotency_key is None or repos["idempotency"].get_by_key(idempotency_key) is None else 1
        ),
    }


def _default_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id", symbol="BBCA", action="BUY", quantity=100.0,
        requested_price=9500.0, signal_evidence={"note": "acceptance"},
        user_approval=True, idempotency_key="proof-key-1", executed_at="2026-08-04T00:00:00Z",
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# PROOF 1: cash == gross + fee + tax exactly -> order executes, cash -> 0
# ---------------------------------------------------------------------------
def proof_1_exact_cash_succeeds():
    print("\n[PROOF 1] cash == gross_value + fee + tax exactly -> BUY succeeds, cash -> 0")
    quantity, price, fee_rate = 100.0, 9500.0, 500.0
    gross = quantity * price
    fee = fee_rate  # buy_fee_rate is applied as an absolute per-trade fee (Activation 3.3 placeholder policy)
    tax = 0.0
    exact_cash = gross + fee + tax

    with tempfile.TemporaryDirectory() as tmp:
        db_path, engine, repos = _build(tmp, cash=exact_cash, buy_fee_rate=fee_rate)
        trade = engine.submit_order(**_default_kwargs(
            quantity=quantity, requested_price=price, idempotency_key="proof1-key",
        ))
        check(isinstance(trade, Trade), "order executes and returns a Trade")
        check(trade.fee == fee and trade.tax == tax, f"Trade carries fee={trade.fee}, tax={trade.tax} as configured")

        account_after = repos["account"].get_by_id("paper-id")
        check(account_after.cash == 0.0, f"account.cash is exactly 0.0 after the trade (got {account_after.cash})")

        # Restart proof for this scenario: re-open the same physical DB file.
        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        account_repo2 = AccountRepository(manager2)
        reread = account_repo2.get_by_id("paper-id")
        check(reread.cash == 0.0, f"after reconnecting to the same DB file, cash still reads 0.0 (got {reread.cash})")


# ---------------------------------------------------------------------------
# PROOF 2: cash slightly less than gross + fee + tax -> rejected pre-trade,
# zero writes anywhere.
# ---------------------------------------------------------------------------
def proof_2_shortfall_rejected_pretrade_zero_writes():
    print("\n[PROOF 2] cash slightly < gross_value + fee + tax -> rejected BEFORE Order is created, zero writes")
    quantity, price, fee_rate = 100.0, 9500.0, 500.0
    gross = quantity * price
    required = gross + fee_rate  # tax = 0 for BUY
    shortfall_cash = required - 1.0  # exactly 1 short

    with tempfile.TemporaryDirectory() as tmp:
        db_path, engine, repos = _build(tmp, cash=shortfall_cash, buy_fee_rate=fee_rate)

        key = "proof2-key"
        before = _row_counts(repos, idempotency_key=key)
        account_before = repos["account"].get_by_id("paper-id")

        raised_reason = None
        try:
            engine.submit_order(**_default_kwargs(
                quantity=quantity, requested_price=price, idempotency_key=key,
            ))
        except ValidationError as exc:
            raised_reason = exc.details.get("reason")

        check(
            raised_reason == PRETRADE_REASON_INSUFFICIENT_CASH,
            f"rejected with reason={PRETRADE_REASON_INSUFFICIENT_CASH} (got {raised_reason})",
        )

        after = _row_counts(repos, idempotency_key=key)
        account_after = repos["account"].get_by_id("paper-id")

        check(before["orders"] == after["orders"] == 0, "orders table: zero rows before and after (order never created)")
        check(before["trades"] == after["trades"] == 0, "trades table: zero rows before and after (trade never created)")
        check(account_before.cash == account_after.cash == shortfall_cash, "account.cash is byte-for-byte unchanged")
        check(before["idempotency"] == after["idempotency"] == 0, "order_idempotency_keys table: zero rows before and after (key never recorded)")

        # This is the exact gap the audit found: the OLD gate 8
        # (order_value only) would have let this cash value THROUGH,
        # since account.cash (999,999,499 short by 1 of required) >=
        # gross order_value (950,000.0). Confirm the boundary is at
        # `required`, not at `gross`.
        check(shortfall_cash >= gross, "sanity: shortfall_cash still covers bare gross_value (this is precisely the old gap's blind spot)")
        check(shortfall_cash < required, "sanity: shortfall_cash is below gross_value + fee + tax (the new, correct boundary)")


# ---------------------------------------------------------------------------
# PROOF 3: SELL still works normally (gate 8 is BUY-only; unaffected).
# ---------------------------------------------------------------------------
def proof_3_sell_unaffected():
    print("\n[PROOF 3] SELL continues to work normally (gate 8 is BUY-only, unaffected by this fix)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path, engine, repos = _build(tmp, cash=100_000_000.0, buy_fee_rate=500.0, sell_fee_rate=250.0, sell_tax_rate=100.0)

        buy_trade = engine.submit_order(**_default_kwargs(idempotency_key="proof3-buy-key"))
        check(isinstance(buy_trade, Trade), "BUY leg succeeds")

        cash_after_buy = repos["account"].get_by_id("paper-id").cash

        # PositionManager is not wired into PaperTradingEngine yet (per
        # the STEP 2 audit -- Position is untouched by this pipeline),
        # so a Position must be seeded directly for gate 9 (available
        # position for SELL) to pass, mirroring
        # Tests/test_paper_trading_engine.py's own pattern.
        repos["position"].create(
            account_id="paper-id", symbol="BBCA", quantity=100.0,
            average_price=9500.0, realized_pnl=0.0, status="open",
        )

        sell_trade = engine.submit_order(**_default_kwargs(
            action="SELL", idempotency_key="proof3-sell-key",
        ))
        check(isinstance(sell_trade, Trade), "SELL succeeds normally")
        check(sell_trade.fee == 250.0 and sell_trade.tax == 100.0, f"SELL Trade carries configured fee/tax (got fee={sell_trade.fee}, tax={sell_trade.tax})")

        expected_cash = cash_after_buy + (100.0 * 9500.0) - 250.0 - 100.0
        cash_after_sell = repos["account"].get_by_id("paper-id").cash
        check(cash_after_sell == expected_cash, f"cash after SELL matches gross - fee - tax (expected {expected_cash}, got {cash_after_sell})")


# ---------------------------------------------------------------------------
# PROOF 4: restart proof (already folded into Proof 1's reconnect step;
# repeated standalone here for a rejection scenario too).
# ---------------------------------------------------------------------------
def proof_4_restart_proof_after_rejection():
    print("\n[PROOF 4] Restart proof: reconnecting to the same DB file after a rejected BUY shows unchanged state")
    quantity, price, fee_rate = 100.0, 9500.0, 500.0
    gross = quantity * price
    required = gross + fee_rate
    shortfall_cash = required - 1.0

    with tempfile.TemporaryDirectory() as tmp:
        db_path, engine, repos = _build(tmp, cash=shortfall_cash, buy_fee_rate=fee_rate)
        try:
            engine.submit_order(**_default_kwargs(idempotency_key="proof4-key"))
        except ValidationError:
            pass

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        account_repo2 = AccountRepository(manager2)
        order_repo2 = OrderRepository(manager2)
        trade_repo2 = TradeRepository(manager2)

        reread_account = account_repo2.get_by_id("paper-id")
        check(reread_account.cash == shortfall_cash, f"cash still {shortfall_cash} after reconnect (got {reread_account.cash})")
        check(len(order_repo2.list_all()) == 0, "orders table still empty after reconnect")
        check(len(trade_repo2.list_all()) == 0, "trades table still empty after reconnect")


def main() -> int:
    proof_1_exact_cash_succeeds()
    proof_2_shortfall_rejected_pretrade_zero_writes()
    proof_3_sell_unaffected()
    proof_4_restart_proof_after_rejection()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 3.5 STEP 3 ACCEPTANCE PROOF: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())