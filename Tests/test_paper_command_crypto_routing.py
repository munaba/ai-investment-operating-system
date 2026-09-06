"""Activation 7 (Crypto Validation Profile) proof suite -- CLI-layer
account/market resolution added to ``main.py`` for
``paper buy``/``paper sell``, plus ``Core.market_config.
is_crypto_symbol()`` itself.

Scope: dedicated, additive proof suite for exactly the two new pieces
this Activation added at the CLI layer:

    1. ``main._resolve_account_id_for_symbol(symbol)`` -- picks
       ``crypto-usd`` for a recognized crypto symbol, ``paper``
       (unchanged default) for everything else.
    2. ``Core.market_config.is_crypto_symbol()`` / ``CRYPTO_SYMBOLS``
       -- the shared allowlist both this helper and
       ``MarketAnalysisSkill`` route on.

Does not re-exercise ``_compute_allocation_quantity``'s crypto
fractional-quantity branch or ``resolve_provider_symbol``'s crypto
passthrough -- both already covered by
``Tests/test_crypto_market_prototype.py`` -- only the NEW
symbol-to-account routing and the shared recognizer.

Invariant coverage:
    A1  -- is_crypto_symbol("BTC-USD") / ("ETH-USD") -> True.
    A2  -- is_crypto_symbol("BBCA") / ("AAPL") / a random string ->
           False.
    A3  -- case-insensitive: is_crypto_symbol("btc-usd") -> True.
    A4  -- defensive: is_crypto_symbol(None) / (123) -> False, never
           raises.
    A5  -- CRYPTO_SYMBOLS is exactly {"BTC-USD", "ETH-USD"} -- LOCKED
           narrow scope, no accidental third symbol.
    R1  -- _resolve_account_id_for_symbol("BTC-USD") ==
           DEFAULT_CRYPTO_ACCOUNT_ID.
    R2  -- _resolve_account_id_for_symbol("ETH-USD") ==
           DEFAULT_CRYPTO_ACCOUNT_ID.
    R3  -- _resolve_account_id_for_symbol("BBCA") ==
           DEFAULT_PAPER_ACCOUNT_ID (byte-for-byte the same account
           every pre-Activation-7 stock order already used).
    R4  -- _resolve_account_id_for_symbol("btc-usd") (lowercase) ==
           DEFAULT_CRYPTO_ACCOUNT_ID -- consistent with
           is_crypto_symbol's own case-insensitivity.
    R5  -- the two account ids returned are never equal to each other
           (sanity: crypto and stock orders can never collide onto
           the same account).

Run directly with ``python -m Tests.test_paper_command_crypto_routing``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.bootstrap import DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_ID  # noqa: E402
from Core.market_config import CRYPTO_SYMBOLS, is_crypto_symbol  # noqa: E402
from main import _resolve_account_id_for_symbol  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


def scenario_is_crypto_symbol():
    print("\n[A] Core.market_config.is_crypto_symbol()")
    check(is_crypto_symbol("BTC-USD") is True, "A1: BTC-USD -> True")
    check(is_crypto_symbol("ETH-USD") is True, "A1: ETH-USD -> True")

    check(is_crypto_symbol("BBCA") is False, "A2: BBCA (IDX stock) -> False")
    check(is_crypto_symbol("AAPL") is False, "A2: AAPL (US stock) -> False")
    check(is_crypto_symbol("SOL-USD") is False, "A2: SOL-USD (not on the LOCKED allowlist) -> False")

    check(is_crypto_symbol("btc-usd") is True, "A3: lowercase 'btc-usd' -> True")
    check(is_crypto_symbol("Eth-Usd") is True, "A3: mixed case 'Eth-Usd' -> True")

    check(is_crypto_symbol(None) is False, "A4: None -> False, no exception")
    check(is_crypto_symbol(123) is False, "A4: non-str 123 -> False, no exception")
    check(is_crypto_symbol("") is False, "A4: empty string -> False")

    check(CRYPTO_SYMBOLS == frozenset({"BTC-USD", "ETH-USD"}), "A5: CRYPTO_SYMBOLS is exactly the LOCKED two symbols")


def scenario_account_resolution():
    print("\n[R] main._resolve_account_id_for_symbol()")
    check(_resolve_account_id_for_symbol("BTC-USD") == DEFAULT_CRYPTO_ACCOUNT_ID, "R1: BTC-USD -> crypto-usd account")
    check(_resolve_account_id_for_symbol("ETH-USD") == DEFAULT_CRYPTO_ACCOUNT_ID, "R2: ETH-USD -> crypto-usd account")

    check(_resolve_account_id_for_symbol("BBCA") == DEFAULT_PAPER_ACCOUNT_ID, "R3: BBCA -> default paper (IDR) account, unchanged")
    check(_resolve_account_id_for_symbol("AAPL") == DEFAULT_PAPER_ACCOUNT_ID, "R3: AAPL -> default paper account (not on crypto allowlist)")

    check(_resolve_account_id_for_symbol("btc-usd") == DEFAULT_CRYPTO_ACCOUNT_ID, "R4: lowercase 'btc-usd' -> crypto-usd account")

    check(DEFAULT_CRYPTO_ACCOUNT_ID != DEFAULT_PAPER_ACCOUNT_ID, "R5: the two account ids are distinct")


def main() -> int:
    scenario_is_crypto_symbol()
    scenario_account_resolution()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 PAPER-COMMAND CRYPTO-ROUTING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())