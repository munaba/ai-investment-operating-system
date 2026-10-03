"""Activation 9.5 STEP 2 -- focused regression coverage for the US
market-context timing fix in ``main._run_paper_buy_command`` /
``main._run_paper_sell_command``.

Reproduces and proves the fix for the exact defect the Activation 9.5
audit found: ``AIOS_MARKET="us"`` used to be applied only around
``PaperTradingEngine.submit_order()`` -- *after*
``_fetch_current_price()`` had already run, and *before*
``_run_post_trade_snapshot_and_reconciliation()`` ran -- so both of
those provider-symbol-resolving call sites could resolve a bare US
ticker (e.g. ``AAPL``) under whatever ``AIOS_MARKET`` happened to
already be set to (defaulting to ``"idx"``), mis-resolving it to
``AAPL.JK``.

Boundary spied (never faked/replaced with a stub resolver): the
module-level ``Orchestration.market_price_tool._fetch_real_prices``
function, the same network boundary
``Tests/test_activation9_us_e2e_acceptance.py`` already mocks for this
sandbox (no real network route). The spy wraps it, still calling the
real, unmodified ``Core.market_config.resolve_provider_symbol`` for
every invocation so each recorded entry reflects exactly what the real
resolver would compute against whatever ``AIOS_MARKET`` is actually
set to at that instant -- ``resolve_provider_symbol()`` itself is
never faked or monkeypatched.

Application wiring is reused, not reinvented: this module imports the
real, unmodified ``MinimalApp``/``_build_app`` fixture and the
``US_SYMBOL``/``US_CURRENT_PRICE``/``US_PREVIOUS_PRICE``/
``US_BUY_ALLOCATION``/``SELL_QUANTITY``/``US_REGULAR_SESSION_EXECUTED_AT``
scenario constants straight from
``Tests/test_activation9_us_e2e_acceptance.py`` (guarded by that
module's own ``if __name__ == "__main__"``, so importing it here does
not execute its own scenario). Only the watchlist scanner is swapped
for a two-symbol fake (adding the IDX ``BBCA`` ticker used by the
regression check D below) via the same private-attribute substitution
pattern ``ManualScanService`` already exposes for this purpose.

Run directly: ``python Tests/test_activation9_5_step2_us_provider_context.py``
-- no external test framework required, matching every other
``Tests/test_*`` script in this suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import Orchestration.market_price_tool as market_price_tool_module  # noqa: E402

from Core.bootstrap import DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_us_command import run_init_us  # noqa: E402
from Core.market_config import resolve_provider_symbol  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Orchestration.skill_result import SkillResult  # noqa: E402

import main as cli  # noqa: E402

from Tests.test_activation9_us_e2e_acceptance import (  # noqa: E402
    EXPECTED_BUY_QUANTITY,
    MinimalApp,
    SELL_QUANTITY,
    US_BUY_ALLOCATION,
    US_CURRENT_PRICE,
    US_PREVIOUS_PRICE,
    US_REGULAR_SESSION_EXECUTED_AT,
    US_SYMBOL,
    _build_app,
)

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
# Fixed, deterministic scenario data
# ---------------------------------------------------------------------------

IDX_SYMBOL = "BBCA"
IDX_CURRENT_PRICE = 9500.0
IDX_PREVIOUS_PRICE = 9400.0

_SCAN_TIME = "2026-01-05T00:00:00+00:00"


class _TwoMarketWatchlistScanner:
    """Same fake-data pattern ``FakeWatchlistScanner`` (the e2e test's
    own fixture) already establishes, widened to cover one US symbol
    (``AAPL``) and one IDX symbol (``BBCA``) in a single scan, so both
    regression paths (US provider-symbol fix, IDX no-regression) have
    a usable persisted snapshot to trade against.
    """

    def scan(self) -> Dict[str, Any]:
        return {
            US_SYMBOL: {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 1,
                                "symbol": US_SYMBOL,
                                "recommendation": "BUY",
                                "confidence": "HIGH",
                                "summary": "US scan: strong momentum breakout above resistance.",
                            }
                        ]
                    },
                )
            },
            IDX_SYMBOL: {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 1,
                                "symbol": IDX_SYMBOL,
                                "recommendation": "BUY",
                                "confidence": "HIGH",
                                "summary": "IDX scan: strong momentum breakout above resistance.",
                            }
                        ]
                    },
                )
            },
        }


def _build_spy_fetch_real_prices(
    recorded_calls: List[Tuple[str, str, Optional[str]]],
):
    """Build a spy replacement for
    ``Orchestration.market_price_tool._fetch_real_prices``.

    For every call, records ``(raw_symbol, provider_symbol,
    AIOS_MARKET-at-call-time)`` -- ``provider_symbol`` computed via the
    real, unmodified ``resolve_provider_symbol()`` (never faked) -- so
    the test can assert exactly what the real resolver would have
    produced at that instant, then returns a fixed, deterministic
    price tuple instead of making a real network call (this sandbox
    has no route to one), mirroring
    ``test_activation9_us_e2e_acceptance._fake_fetch_real_prices``.
    """

    def _spy(symbol: str) -> Tuple[Optional[float], Optional[float]]:
        provider_symbol = resolve_provider_symbol(symbol)
        recorded_calls.append((symbol, provider_symbol, os.environ.get("AIOS_MARKET")))
        bare = symbol.upper().split(".")[0]
        if bare == US_SYMBOL:
            return US_CURRENT_PRICE, US_PREVIOUS_PRICE
        if bare == IDX_SYMBOL:
            return IDX_CURRENT_PRICE, IDX_PREVIOUS_PRICE
        return None, None

    return _spy


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="activation9_5_step2_")
    db_path = Path(tmp_dir) / "activation9_5_step2.db"
    cfg = DatabaseConfig(db_path=db_path)

    previous_market_env = os.environ.get("AIOS_MARKET")
    original_fetch_real_prices = market_price_tool_module._fetch_real_prices

    try:
        print("=" * 70)
        print("[Setup] run_init() + run_init_us() against one temp SQLite DB")
        print("=" * 70)
        check(run_init(db_config=cfg, print_fn=lambda s: None) == 0, "run_init() succeeded")
        check(run_init_us(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_us() succeeded")

        app = _build_app(cfg)
        # Widen the watchlist scanner to also cover the IDX regression
        # symbol -- ManualScanService's own private substitution seam
        # (see its docstring / _watchlist_scanner attribute), not a new
        # abstraction.
        app.manual_scan_service._watchlist_scanner = _TwoMarketWatchlistScanner()

        app.watchlist_repository.add(US_SYMBOL)
        app.watchlist_repository.add(IDX_SYMBOL)

        recorded_calls: List[Tuple[str, str, Optional[str]]] = []
        market_price_tool_module._fetch_real_prices = _build_spy_fetch_real_prices(recorded_calls)

        scan_rc = cli._run_scan_command(app, ["--market", "us"])
        check(scan_rc == 0, "scan (seeding both AAPL and BBCA snapshots) exited 0")

        # ------------------------------------------------------------
        # A + C -- US BUY provider symbol, and US post-trade snapshot
        # provider symbol
        # ------------------------------------------------------------
        print("\n" + "=" * 70)
        print("[A/C] paper buy AAPL --market us -- provider symbol + post-trade snapshot symbol")
        print("=" * 70)
        recorded_calls.clear()
        buy_rc = cli._run_paper_buy_command(
            app,
            [
                US_SYMBOL,
                "--allocation",
                US_BUY_ALLOCATION,
                "--market",
                "us",
                "--executed-at",
                US_REGULAR_SESSION_EXECUTED_AT,
            ],
        )
        check(buy_rc == 0, "paper buy AAPL --market us exited 0")

        us_buy_calls = [c for c in recorded_calls if c[0].upper().split(".")[0] == US_SYMBOL]
        check(
            len(us_buy_calls) >= 2,
            f"at least 2 provider-symbol resolutions occurred for AAPL during buy "
            f"(price fetch + post-trade snapshot) (found {len(us_buy_calls)}: {us_buy_calls})",
        )
        check(
            all(provider_symbol == US_SYMBOL for _, provider_symbol, _ in us_buy_calls),
            f"every AAPL provider-symbol resolution during the US buy resolved to "
            f"'{US_SYMBOL}', never '{US_SYMBOL}.JK' (found: {us_buy_calls})",
        )
        check(
            all(market == "us" for _, _, market in us_buy_calls),
            f"AIOS_MARKET == 'us' at every AAPL provider-symbol resolution during the "
            f"US buy, including the post-trade snapshot lookup (found: {us_buy_calls})",
        )

        us_position = app.position_repository.get_open_position(DEFAULT_US_ACCOUNT_ID, US_SYMBOL)
        check(
            us_position is not None and us_position.quantity == EXPECTED_BUY_QUANTITY,
            f"US AAPL position opened with quantity {EXPECTED_BUY_QUANTITY} "
            f"(found: {us_position.quantity if us_position else None})",
        )
        us_snapshots = app.portfolio_snapshot_repository.list_by_account(DEFAULT_US_ACCOUNT_ID)
        check(
            len(us_snapshots) >= 1,
            f"a real PortfolioSnapshot for 'us-usd' was persisted by the post-trade hook "
            f"after the BUY (found {len(us_snapshots)})",
        )

        # ------------------------------------------------------------
        # E -- environment restoration after a successful US buy
        # ------------------------------------------------------------
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            f"AIOS_MARKET restored to its original value after the US buy "
            f"(before={previous_market_env!r}, after={os.environ.get('AIOS_MARKET')!r})",
        )

        # ------------------------------------------------------------
        # B -- US SELL provider symbol (and post-trade snapshot again)
        # ------------------------------------------------------------
        print("\n" + "=" * 70)
        print("[B] paper sell AAPL --market us -- provider symbol")
        print("=" * 70)
        recorded_calls.clear()
        sell_rc = cli._run_paper_sell_command(
            app,
            [
                US_SYMBOL,
                "--quantity",
                SELL_QUANTITY,
                "--market",
                "us",
                "--executed-at",
                US_REGULAR_SESSION_EXECUTED_AT,
            ],
        )
        check(sell_rc == 0, "paper sell AAPL --market us exited 0")

        # Note: unlike the BUY (which leaves an open position for the
        # post-trade snapshot to price), this SELL fully closes the
        # AAPL position (quantity == the entire held amount), so the
        # post-trade snapshot has no remaining AAPL position to price
        # and legitimately makes no second provider call here -- only
        # the pre-submission price fetch does. At least 1 call is the
        # correct expectation for this specific full-close scenario.
        us_sell_calls = [c for c in recorded_calls if c[0].upper().split(".")[0] == US_SYMBOL]
        check(
            len(us_sell_calls) >= 1,
            f"at least 1 provider-symbol resolution occurred for AAPL during sell "
            f"(price fetch) (found {len(us_sell_calls)}: {us_sell_calls})",
        )
        check(
            all(provider_symbol == US_SYMBOL for _, provider_symbol, _ in us_sell_calls),
            f"every AAPL provider-symbol resolution during the US sell resolved to "
            f"'{US_SYMBOL}', never '{US_SYMBOL}.JK' (found: {us_sell_calls})",
        )
        check(
            all(market == "us" for _, _, market in us_sell_calls),
            f"AIOS_MARKET == 'us' at every AAPL provider-symbol resolution during the "
            f"US sell, including the post-trade snapshot lookup (found: {us_sell_calls})",
        )

        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            f"AIOS_MARKET restored to its original value after the US sell "
            f"(before={previous_market_env!r}, after={os.environ.get('AIOS_MARKET')!r})",
        )

        # ------------------------------------------------------------
        # D -- IDX regression: BBCA still resolves to BBCA.JK
        # ------------------------------------------------------------
        print("\n" + "=" * 70)
        print("[D] paper buy BBCA --market idx -- IDX provider-symbol regression")
        print("=" * 70)
        recorded_calls.clear()
        idx_buy_rc = cli._run_paper_buy_command(
            app,
            [IDX_SYMBOL, "--allocation", "0.05", "--market", "idx"],
        )
        check(idx_buy_rc == 0, "paper buy BBCA --market idx exited 0")

        idx_calls = [c for c in recorded_calls if c[0].upper().split(".")[0] == IDX_SYMBOL]
        check(len(idx_calls) >= 1, f"at least 1 provider-symbol resolution occurred for BBCA (found {len(idx_calls)})")
        check(
            all(provider_symbol == f"{IDX_SYMBOL}.JK" for _, provider_symbol, _ in idx_calls),
            f"every BBCA provider-symbol resolution still resolves to '{IDX_SYMBOL}.JK' "
            f"(found: {idx_calls})",
        )
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            f"AIOS_MARKET restored to its original value after the IDX buy "
            f"(before={previous_market_env!r}, after={os.environ.get('AIOS_MARKET')!r})",
        )

        # ------------------------------------------------------------
        # F -- failure-path restoration
        # ------------------------------------------------------------
        print("\n" + "=" * 70)
        print("[F] forced failure inside the scoped US workflow -- AIOS_MARKET still restored")
        print("=" * 70)

        def _raising_fetch(symbol: str) -> Tuple[Optional[float], Optional[float]]:
            raise RuntimeError("forced failure for Activation 9.5 STEP 2 test F")

        market_price_tool_module._fetch_real_prices = _raising_fetch
        market_during_failure: Optional[str] = None
        raised = False
        try:
            cli._run_paper_buy_command(
                app,
                [
                    US_SYMBOL,
                    "--allocation",
                    US_BUY_ALLOCATION,
                    "--market",
                    "us",
                    "--executed-at",
                    US_REGULAR_SESSION_EXECUTED_AT,
                ],
            )
        except Exception:
            raised = True
            market_during_failure = os.environ.get("AIOS_MARKET")
        finally:
            market_price_tool_module._fetch_real_prices = _build_spy_fetch_real_prices(recorded_calls)

        check(raised, "the forced provider failure propagated out of _run_paper_buy_command as expected")
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            f"AIOS_MARKET restored to its original value even though _fetch_current_price "
            f"raised mid-workflow (before={previous_market_env!r}, "
            f"after={os.environ.get('AIOS_MARKET')!r}, during_failure={market_during_failure!r})",
        )

        print("\n" + "=" * 70)
        print(f"RESULT: {_PASS} PASS, {_FAIL} FAIL")
        print("=" * 70)
        return 0 if _FAIL == 0 else 1

    finally:
        market_price_tool_module._fetch_real_prices = original_fetch_real_prices
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)