"""
Read-only Activation 7 crypto evidence checker.

Run from the project root:
    python check_activation7_crypto.py

This script only reads SQLite. It does not create orders, trades, positions,
migrations, or modify the database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


DB_PATH = Path("data/investment_platform.db")
ACCOUNT_ID = "crypto-usd"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def money(value: float) -> str:
    return f"${value:,.8f}"


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB NOT FOUND: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    checks: list[Check] = []

    account = conn.execute(
        """
        SELECT account_id, mode, currency, asset_class, cash, equity
        FROM accounts
        WHERE account_id = ?
        """,
        (ACCOUNT_ID,),
    ).fetchone()

    if account is None:
        print(f"ACCOUNT NOT FOUND: {ACCOUNT_ID}")
        conn.close()
        return 1

    checks.append(Check(
        "Crypto account",
        account["mode"] == "paper"
        and account["currency"] == "USD"
        and account["asset_class"] == "crypto",
        (
            f"mode={account['mode']}, currency={account['currency']}, "
            f"asset_class={account['asset_class']}, cash={money(float(account['cash']))}"
        ),
    ))

    orders = conn.execute(
        """
        SELECT order_id, symbol, action, quantity, status, created_at
        FROM orders
        WHERE account_id = ?
        ORDER BY order_id
        """,
        (ACCOUNT_ID,),
    ).fetchall()

    trades = conn.execute(
        """
        SELECT trade_id, order_id, symbol, action, quantity,
               fill_price, fee, tax, executed_at
        FROM trades
        WHERE account_id = ?
        ORDER BY trade_id
        """,
        (ACCOUNT_ID,),
    ).fetchall()

    positions = conn.execute(
        """
        SELECT symbol, quantity, average_price, buy_fee_accumulated
        FROM positions
        WHERE account_id = ?
        ORDER BY symbol
        """,
        (ACCOUNT_ID,),
    ).fetchall()

    filled_orders = [r for r in orders if r["status"] == "FILLED"]
    buy_trades = [r for r in trades if r["action"] == "BUY"]
    sell_trades = [r for r in trades if r["action"] == "SELL"]

    checks.append(Check(
        "Filled BUY",
        len(buy_trades) >= 1 and all(r["action"] == "BUY" for r in buy_trades),
        f"{len(buy_trades)} BUY trade(s)",
    ))
    checks.append(Check(
        "Filled SELL",
        len(sell_trades) >= 1 and all(r["action"] == "SELL" for r in sell_trades),
        f"{len(sell_trades)} SELL trade(s)",
    ))

    closed_ok = False
    realized_pnl = None
    if buy_trades and sell_trades:
        buy = buy_trades[-1]
        sell = sell_trades[-1]
        qty_match = abs(float(buy["quantity"]) - float(sell["quantity"])) < 1e-12
        realized_pnl = (
            (float(sell["fill_price"]) - float(buy["fill_price"]))
            * float(sell["quantity"])
            - float(buy["fee"]) - float(buy["tax"])
            - float(sell["fee"]) - float(sell["tax"])
        )
        closed_ok = qty_match

        checks.append(Check(
            "BUY↔SELL quantity reconciliation",
            qty_match,
            f"BUY={buy['quantity']} SELL={sell['quantity']}",
        ))
        checks.append(Check(
            "Realized P/L calculable",
            True,
            f"net realized P/L={money(realized_pnl)}",
        ))

    all_zero = all(abs(float(p["quantity"])) < 1e-12 for p in positions)
    checks.append(Check(
        "Position closed",
        all_zero and bool(positions),
        f"{[(p['symbol'], p['quantity']) for p in positions]}",
    ))

    total_fees = sum(float(r["fee"]) for r in trades)
    total_tax = sum(float(r["tax"]) for r in trades)

    print("ACTIVATION 7 — CRYPTO PAPER EVIDENCE")
    print("=" * 72)
    print(f"Database : {DB_PATH}")
    print(f"Account  : {ACCOUNT_ID}")
    print(f"Cash     : {money(float(account['cash']))}")
    print(f"Equity   : {money(float(account['equity']))}")
    print(f"Orders   : {len(orders)} ({len(filled_orders)} FILLED)")
    print(f"Trades   : {len(trades)}")
    print(f"Fees     : {money(total_fees)}")
    print(f"Tax      : {money(total_tax)}")
    if realized_pnl is not None:
        print(f"Realized : {money(realized_pnl)}")
    print()

    for c in checks:
        print(f"[{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")

    print("\nORDERS")
    for r in orders:
        print(
            f"  #{r['order_id']} {r['action']} {r['symbol']} "
            f"qty={r['quantity']} status={r['status']}"
        )

    print("\nTRADES")
    for r in trades:
        print(
            f"  #{r['trade_id']} {r['action']} {r['symbol']} "
            f"qty={r['quantity']} price={r['fill_price']} "
            f"fee={r['fee']} tax={r['tax']}"
        )

    conn.close()

    failed = [c for c in checks if not c.passed]
    print("\nRESULT")
    if failed:
        print(f"NOT READY — {len(failed)} check(s) failed.")
        return 1

    print("CRYPTO PAPER CYCLE EVIDENCE PASS")
    print("Note: this is evidence capture, not the final Activation 7 readiness gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())