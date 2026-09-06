"""Standalone regression checks for
``Business.trade_attribution_engine.TradeAttributionEngine``.

Covers Activation 5.6 (Strategy Attribution) per-trade assembly of the
five LOCKED attribution dimensions from already-resolved inputs:

* constructor takes exactly one dependency (``DecisionPolicy``);
* ``strategy`` is ``"recommendation_following"`` when
  ``Order.analysis_snapshot_id`` is not ``None``, else ``"manual"``;
* ``strategy_version`` is always the literal ``"1"``;
* ``market``/``signal_snapshot_id``/``holding_period_seconds`` are
  placed verbatim from the caller-supplied arguments -- never
  recomputed;
* ``risk_category`` comes straight off
  ``DecisionPolicy.apply().risk_level`` for the trade's own
  ``action`` (``BUY`` -> ``"NORMAL"``, ``SELL`` -> ``"HIGH"``);
* traceability fields (``trade_id``/``order_id``/``account_id``/
  ``symbol``/``action``) are copied verbatim from ``trade``;
* neither ``trade`` nor ``order`` is mutated;
* the returned object is a real ``TradeAttribution`` instance.

Uses a real ``DecisionPolicy`` (Stage L20A, LOCKED, no dependency of
its own) plus hand-built ``Trade``/``Order`` instances directly -- no
database, no repository, no I/O.

Run directly with ``python Tests/test_trade_attribution_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.trade_attribution_engine import (  # noqa: E402
    STRATEGY_MANUAL,
    STRATEGY_RECOMMENDATION_FOLLOWING,
    STRATEGY_VERSION,
    TradeAttribution,
    TradeAttributionEngine,
)
from Database.models import Order, Trade  # noqa: E402
from Orchestration.decision_policy import DecisionPolicy  # noqa: E402

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


def _trade(trade_id: int = 1, order_id: int = 10, account_id: str = "paper",
           symbol: str = "BBCA", action: str = "BUY") -> Trade:
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=100.0,
        fill_price=9000.0,
        fee=0.0,
        tax=0.0,
        executed_at="2026-08-01T09:00:00+00:00",
    )


def _order(order_id: int = 10, account_id: str = "paper", symbol: str = "BBCA",
           action: str = "BUY", analysis_snapshot_id=None) -> Order:
    return Order(
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=100.0,
        requested_price=9000.0,
        filled_price=9000.0,
        filled_quantity=100.0,
        status="FILLED",
        reason="",
        created_at="2026-08-01T08:59:00+00:00",
        updated_at="2026-08-01T09:00:00+00:00",
        filled_at="2026-08-01T09:00:00+00:00",
        analysis_snapshot_id=analysis_snapshot_id,
    )


def scenario_constructor_requires_decision_policy():
    print("\n[Scenario 1] constructor takes exactly one dependency (DecisionPolicy)")
    engine = TradeAttributionEngine(DecisionPolicy())
    check(engine is not None, "TradeAttributionEngine(decision_policy) constructs")


def scenario_strategy_recommendation_following_when_snapshot_present():
    print("\n[Scenario 2] strategy = 'recommendation_following' when Order.analysis_snapshot_id is set")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade()
    order = _order(analysis_snapshot_id=42)
    attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=42, holding_period_seconds=None)
    check(attribution.strategy == STRATEGY_RECOMMENDATION_FOLLOWING, "strategy is 'recommendation_following'")
    check(attribution.strategy == "recommendation_following", "literal string matches the LOCKED value")


def scenario_strategy_manual_when_snapshot_absent():
    print("\n[Scenario 3] strategy = 'manual' when Order.analysis_snapshot_id is None")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade()
    order = _order(analysis_snapshot_id=None)
    attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution.strategy == STRATEGY_MANUAL, "strategy is 'manual'")
    check(attribution.strategy == "manual", "literal string matches the LOCKED value")


def scenario_strategy_version_is_always_literal_one():
    print("\n[Scenario 4] strategy_version is always the literal '1'")
    engine = TradeAttributionEngine(DecisionPolicy())
    for snapshot_id in (None, 7):
        attribution = engine.calculate(
            _trade(), _order(analysis_snapshot_id=snapshot_id),
            market="stock_id", signal_snapshot_id=snapshot_id, holding_period_seconds=None,
        )
        check(attribution.strategy_version == STRATEGY_VERSION, f"strategy_version == '1' regardless of strategy (snapshot_id={snapshot_id})")
        check(attribution.strategy_version == "1", "literal '1', not an int or any other type")


def scenario_market_placed_verbatim():
    print("\n[Scenario 5] market is placed verbatim from the caller-supplied argument")
    engine = TradeAttributionEngine(DecisionPolicy())
    attribution = engine.calculate(_trade(), _order(), market="crypto", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution.market == "crypto", "market is exactly the caller-supplied value, never recomputed")


def scenario_signal_snapshot_id_placed_verbatim():
    print("\n[Scenario 6] signal_snapshot_id is placed verbatim -- including None")
    engine = TradeAttributionEngine(DecisionPolicy())
    attribution_with = engine.calculate(_trade(), _order(analysis_snapshot_id=99), market="stock_id", signal_snapshot_id=99, holding_period_seconds=None)
    attribution_without = engine.calculate(_trade(), _order(analysis_snapshot_id=None), market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution_with.signal_snapshot_id == 99, "signal_snapshot_id is exactly the caller-supplied resolved id")
    check(attribution_without.signal_snapshot_id is None, "signal_snapshot_id is None when the caller resolved none -- never fabricated")


def scenario_holding_period_placed_verbatim():
    print("\n[Scenario 7] holding_period_seconds is placed verbatim -- including None")
    engine = TradeAttributionEngine(DecisionPolicy())
    attribution_closed = engine.calculate(_trade(), _order(), market="stock_id", signal_snapshot_id=None, holding_period_seconds=3600.0)
    attribution_open = engine.calculate(_trade(), _order(), market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution_closed.holding_period_seconds == 3600.0, "holding_period_seconds is exactly the caller-supplied computed value")
    check(attribution_open.holding_period_seconds is None, "holding_period_seconds is None for an open episode -- never fabricated as 0.0")


def scenario_risk_category_buy_is_normal():
    print("\n[Scenario 8] risk_category for a BUY trade is 'NORMAL', straight off DecisionPolicy")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade(action="BUY")
    order = _order(action="BUY")
    attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution.risk_category == "NORMAL", "risk_category == 'NORMAL' for BUY, matching DecisionPolicy._POLICIES['BUY']['risk_level']")


def scenario_risk_category_sell_is_high():
    print("\n[Scenario 9] risk_category for a SELL trade is 'HIGH', straight off DecisionPolicy")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade(action="SELL")
    order = _order(action="SELL")
    attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution.risk_category == "HIGH", "risk_category == 'HIGH' for SELL, matching DecisionPolicy._POLICIES['SELL']['risk_level']")


def scenario_risk_category_uses_real_unmodified_decision_policy():
    print("\n[Scenario 10] risk_category is cross-checked against a fresh, independent DecisionPolicy call")
    from types import SimpleNamespace
    policy = DecisionPolicy()
    engine = TradeAttributionEngine(policy)
    for action in ("BUY", "SELL"):
        trade = _trade(action=action)
        order = _order(action=action)
        attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
        expected = policy.apply(SimpleNamespace(action=action)).risk_level
        check(attribution.risk_category == expected, f"risk_category for {action} is bit-for-bit identical to a fresh, independent DecisionPolicy.apply() call")


def scenario_traceability_fields_copied_verbatim():
    print("\n[Scenario 11] traceability fields (trade_id/order_id/account_id/symbol/action) copied verbatim from trade")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade(trade_id=55, order_id=77, account_id="paper", symbol="ASII", action="SELL")
    order = _order(order_id=77, account_id="paper", symbol="ASII", action="SELL")
    attribution = engine.calculate(trade, order, market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(attribution.trade_id == 55, "trade_id copied verbatim")
    check(attribution.order_id == 77, "order_id copied verbatim")
    check(attribution.account_id == "paper", "account_id copied verbatim")
    check(attribution.symbol == "ASII", "symbol copied verbatim")
    check(attribution.action == "SELL", "action copied verbatim")


def scenario_neither_trade_nor_order_mutated():
    print("\n[Scenario 12] neither trade nor order is mutated")
    engine = TradeAttributionEngine(DecisionPolicy())
    trade = _trade()
    order = _order(analysis_snapshot_id=5)
    trade_before = copy.deepcopy(trade)
    order_before = copy.deepcopy(order)
    engine.calculate(trade, order, market="stock_id", signal_snapshot_id=5, holding_period_seconds=1800.0)
    check(trade == trade_before, "trade argument is unchanged after calculate()")
    check(order == order_before, "order argument is unchanged after calculate()")


def scenario_returns_real_trade_attribution_instance():
    print("\n[Scenario 13] returned object is a real TradeAttribution instance")
    engine = TradeAttributionEngine(DecisionPolicy())
    attribution = engine.calculate(_trade(), _order(), market="stock_id", signal_snapshot_id=None, holding_period_seconds=None)
    check(isinstance(attribution, TradeAttribution), "calculate() returns a real TradeAttribution dataclass instance")


def scenario_public_api_is_exactly_calculate():
    print("\n[Scenario 14] public API is exactly {'calculate'}")
    public_methods = {name for name in dir(TradeAttributionEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "TradeAttributionEngine's public API is exactly {'calculate'}")


def main() -> int:
    scenario_constructor_requires_decision_policy()
    scenario_strategy_recommendation_following_when_snapshot_present()
    scenario_strategy_manual_when_snapshot_absent()
    scenario_strategy_version_is_always_literal_one()
    scenario_market_placed_verbatim()
    scenario_signal_snapshot_id_placed_verbatim()
    scenario_holding_period_placed_verbatim()
    scenario_risk_category_buy_is_normal()
    scenario_risk_category_sell_is_high()
    scenario_risk_category_uses_real_unmodified_decision_policy()
    scenario_traceability_fields_copied_verbatim()
    scenario_neither_trade_nor_order_mutated()
    scenario_returns_real_trade_attribution_instance()
    scenario_public_api_is_exactly_calculate()

    print("\n" + "=" * 60)
    print(f"TRADE ATTRIBUTION ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())