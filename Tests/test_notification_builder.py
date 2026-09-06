"""
Sprint 7 STEP 2 proof suite -- ``NotificationBuilder``.

Scope: dedicated regression suite for
``Business.notification_builder.NotificationBuilder`` only.

This STEP only builds a ``NotificationEvent`` in memory. Nothing here
sends a notification, touches Telegram/Discord/email/webhook,
``Services.notification_service.NotificationService``,
``Repository.*``, or ``Database.*``. This suite proves the builder's
exact output shape (event_type, timestamp, message, metadata),
non-mutation of its inputs, and the absence of any extra public
surface, dependency, or side effect.

Uses real Sprint 5 (`Report`) and Sprint 6 (`PerformanceSummary`)
value objects -- constructed directly with plain fixture data, no
mocks needed since both are already-locked, dependency-free
dataclasses.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Business/Tests proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Scenario coverage:
    S1  -- Constructor takes no dependency.
    S2  -- build_daily_report() returns a NotificationEvent.
    S3  -- event_type is exactly DAILY_REPORT.
    S4  -- timestamp comes from report.generated_at.
    S5  -- message contains generated_at, total_symbols, win_rate,
           maximum_drawdown.
    S6  -- metadata contains exactly the 4 locked keys with the right
           values.
    S7  -- Recommendations are not read/iterated one by one (message
           has no per-symbol content).
    S8  -- Inputs (report, performance) are not mutated.
    S9  -- Report object remains identical/unchanged after the call.
    S10 -- PerformanceSummary object remains identical/unchanged after
           the call.
    S11 -- metadata is a new dict object, not aliased to anything.
    S12 -- No external dependency (AST import check on the module).
"""

from __future__ import annotations

import ast
import copy
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.notification_builder import NotificationBuilder
from Business.notification_event import NotificationEvent, NotificationEventType
from Business.performance_summary_service import PerformanceSummary
from Business.report_service import Report
from Business.recommendation_service import Recommendation
from Business.trade_statistics_engine import TradeExecutionStatistics
from Business.position_performance_engine import PositionPerformanceStatistics
from Business.expectancy_engine import ExpectancyResult
from Business.profit_factor_engine import ProfitFactorResult
from Business.maximum_drawdown_engine import MaximumDrawdownResult

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
# Fixtures
# ---------------------------------------------------------------------------
def make_report() -> Report:
    recommendations = [
        Recommendation(
            symbol="BBCA",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        ),
        Recommendation(
            symbol="TLKM",
            recommendation="HOLD",
            confidence="MEDIUM",
            priority=2,
            rank=2,
        ),
    ]
    return Report(
        generated_at="2026-08-02T09:00:00Z",
        recommendations=recommendations,
        total_symbols=2,
    )


def make_performance_summary() -> PerformanceSummary:
    trade_statistics = TradeExecutionStatistics(
        total_trades=10,
        buy_trades=6,
        sell_trades=4,
        total_volume=1000.0,
        total_fees=5.0,
        total_tax=1.0,
        first_trade_time="2026-08-01T09:00:00Z",
        last_trade_time="2026-08-01T15:00:00Z",
    )
    position_statistics = PositionPerformanceStatistics(
        winning_positions=6,
        losing_positions=3,
        breakeven_positions=1,
        gross_profit=600.0,
        gross_loss=-200.0,
        net_profit=400.0,
        average_win=100.0,
        average_loss=-66.67,
    )
    return PerformanceSummary(
        trade_statistics=trade_statistics,
        position_statistics=position_statistics,
        win_rate=0.6,
        expectancy=ExpectancyResult(expectancy=40.0),
        profit_factor=ProfitFactorResult(profit_factor=3.0),
        maximum_drawdown=MaximumDrawdownResult(maximum_drawdown=0.15),
    )


# ---------------------------------------------------------------------------
# S1 -- constructor takes no dependency
# ---------------------------------------------------------------------------
def scenario_constructor_has_no_dependency() -> None:
    builder = NotificationBuilder()
    check(
        isinstance(builder, NotificationBuilder),
        "S1: NotificationBuilder() constructs with zero arguments",
    )

    import inspect

    sig = inspect.signature(NotificationBuilder.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 0,
        "S1: NotificationBuilder.__init__ takes no parameters beyond self",
    )


# ---------------------------------------------------------------------------
# S2 -- build_daily_report() returns a NotificationEvent
# ---------------------------------------------------------------------------
def scenario_build_daily_report_returns_notification_event() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()

    event = builder.build_daily_report(report, performance)
    check(
        isinstance(event, NotificationEvent),
        "S2: build_daily_report() returns a NotificationEvent instance",
    )


# ---------------------------------------------------------------------------
# S3 -- event_type is exactly DAILY_REPORT
# ---------------------------------------------------------------------------
def scenario_event_type_is_daily_report() -> None:
    builder = NotificationBuilder()
    event = builder.build_daily_report(make_report(), make_performance_summary())
    check(
        event.event_type == NotificationEventType.DAILY_REPORT,
        "S3: event_type is exactly NotificationEventType.DAILY_REPORT",
    )
    check(
        event.title == "Daily Report",
        "S3: title is exactly 'Daily Report'",
    )


# ---------------------------------------------------------------------------
# S4 -- timestamp comes from report.generated_at
# ---------------------------------------------------------------------------
def scenario_timestamp_from_report_generated_at() -> None:
    builder = NotificationBuilder()
    report = make_report()
    event = builder.build_daily_report(report, make_performance_summary())
    check(
        event.timestamp == report.generated_at,
        "S4: timestamp equals report.generated_at exactly",
    )
    check(
        event.timestamp == "2026-08-02T09:00:00Z",
        "S4: timestamp is the exact fixture value, not regenerated",
    )


# ---------------------------------------------------------------------------
# S5 -- message contains the four locked values
# ---------------------------------------------------------------------------
def scenario_message_contains_locked_fields() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()
    event = builder.build_daily_report(report, performance)

    check(
        report.generated_at in event.message,
        "S5: message contains generated_at",
    )
    check(
        str(report.total_symbols) in event.message,
        "S5: message contains total_symbols",
    )
    check(
        f"{performance.win_rate:.2%}" in event.message,
        "S5: message contains win_rate formatted as percentage",
    )
    check(
        f"{performance.maximum_drawdown.maximum_drawdown:.2%}" in event.message,
        "S5: message contains maximum_drawdown formatted as percentage",
    )
    check(
        event.message.startswith("Daily Report"),
        "S5: message starts with the 'Daily Report' header",
    )


# ---------------------------------------------------------------------------
# S6 -- metadata is exactly the 4 locked keys with correct values
# ---------------------------------------------------------------------------
def scenario_metadata_exact_keys_and_values() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()
    event = builder.build_daily_report(report, performance)

    expected_keys = {"generated_at", "total_symbols", "win_rate", "maximum_drawdown"}
    check(
        set(event.metadata.keys()) == expected_keys,
        "S6: metadata has exactly the 4 locked keys -- nothing else",
    )
    check(
        event.metadata["generated_at"] == report.generated_at,
        "S6: metadata['generated_at'] matches report.generated_at",
    )
    check(
        event.metadata["total_symbols"] == report.total_symbols,
        "S6: metadata['total_symbols'] matches report.total_symbols",
    )
    check(
        event.metadata["win_rate"] == performance.win_rate,
        "S6: metadata['win_rate'] matches performance.win_rate",
    )
    check(
        event.metadata["maximum_drawdown"]
        == performance.maximum_drawdown.maximum_drawdown,
        "S6: metadata['maximum_drawdown'] matches "
        "performance.maximum_drawdown.maximum_drawdown",
    )


# ---------------------------------------------------------------------------
# S7 -- recommendations are not read one by one
# ---------------------------------------------------------------------------
def scenario_recommendations_not_enumerated() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()
    event = builder.build_daily_report(report, performance)

    for rec in report.recommendations:
        check(
            rec.symbol not in event.message,
            f"S7: message does not contain per-symbol recommendation "
            f"data for '{rec.symbol}'",
        )
    check(
        "BUY" not in event.message and "HOLD" not in event.message,
        "S7: message does not contain individual recommendation actions",
    )


# ---------------------------------------------------------------------------
# S8 -- inputs are not mutated
# ---------------------------------------------------------------------------
def scenario_inputs_not_mutated() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()

    report_snapshot = copy.deepcopy(report)
    performance_snapshot = copy.deepcopy(performance)

    builder.build_daily_report(report, performance)

    check(
        report == report_snapshot,
        "S8: report is unchanged (deep-equal to pre-call snapshot) "
        "after build_daily_report()",
    )
    check(
        performance == performance_snapshot,
        "S8: performance is unchanged (deep-equal to pre-call snapshot) "
        "after build_daily_report()",
    )


# ---------------------------------------------------------------------------
# S9 -- Report object remains identical after the call
# ---------------------------------------------------------------------------
def scenario_report_object_identity_preserved() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()
    report_id_before = id(report)
    recommendations_id_before = id(report.recommendations)

    builder.build_daily_report(report, performance)

    check(
        id(report) == report_id_before,
        "S9: the Report object itself is the same object after the call",
    )
    check(
        id(report.recommendations) == recommendations_id_before,
        "S9: report.recommendations list is not replaced/reassigned",
    )
    check(
        report.total_symbols == 2,
        "S9: report.total_symbols is unchanged",
    )


# ---------------------------------------------------------------------------
# S10 -- PerformanceSummary object remains identical after the call
# ---------------------------------------------------------------------------
def scenario_performance_summary_identity_preserved() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()
    performance_id_before = id(performance)
    maximum_drawdown_id_before = id(performance.maximum_drawdown)

    builder.build_daily_report(report, performance)

    check(
        id(performance) == performance_id_before,
        "S10: the PerformanceSummary object itself is the same object "
        "after the call",
    )
    check(
        id(performance.maximum_drawdown) == maximum_drawdown_id_before,
        "S10: performance.maximum_drawdown is not replaced/reassigned",
    )
    check(
        performance.win_rate == 0.6,
        "S10: performance.win_rate is unchanged",
    )


# ---------------------------------------------------------------------------
# S11 -- metadata is a new dict object
# ---------------------------------------------------------------------------
def scenario_metadata_is_new_dict() -> None:
    builder = NotificationBuilder()
    report = make_report()
    performance = make_performance_summary()

    event_a = builder.build_daily_report(report, performance)
    event_b = builder.build_daily_report(report, performance)

    check(
        event_a.metadata is not event_b.metadata,
        "S11: metadata dict is freshly built each call, not shared/aliased",
    )
    check(
        event_a.metadata == event_b.metadata,
        "S11: metadata dicts are equal in content across calls with the "
        "same inputs",
    )
    check(
        event_a.metadata is not report.__dict__,
        "S11: metadata is not aliased to report.__dict__",
    )
    check(
        event_a.metadata is not performance.__dict__,
        "S11: metadata is not aliased to performance.__dict__",
    )


# ---------------------------------------------------------------------------
# S12 -- no external dependency (AST import inspection)
# ---------------------------------------------------------------------------
def scenario_no_external_dependency() -> None:
    module_path = ROOT / "Business" / "notification_builder.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)

    # "Database.models" is a documented, narrow exception (see the
    # module's own docstring: "Database.models.Trade for
    # build_order_executed()'s input type annotation only (never
    # constructed or mutated here)") -- added alongside
    # build_order_executed() for the paper-trading notification
    # wiring. Verified during Activation 6.3 (VERIFY ONLY): this
    # scenario had drifted stale (still forbidding it, and still
    # asserting a single-method API) even though the constructor/
    # module docstring already documented both before 6.3 -- corrected
    # here, no production code changed. Every other forbidden
    # substring (real Repository/Database *I/O*, Services, transport
    # libraries) is still forbidden unchanged.
    forbidden_substrings = (
        "Repository",
        "Services.notification_service",
        "telegram",
        "discord",
        "requests",
        "smtplib",
        "webhook",
    )
    violations = [
        m
        for m in imported_modules
        for bad in forbidden_substrings
        if bad.lower() in m.lower()
    ]
    violations += [
        m for m in imported_modules if "database" in m.lower() and m != "Database.models"
    ]
    check(
        len(violations) == 0,
        f"S12: no forbidden dependency imported (found: {violations})",
    )

    allowed_prefixes = (
        "__future__",
        "Business.notification_event",
        "Business.performance_summary_service",
        "Business.report_service",
        "Database.models",
    )
    unexpected = [
        m
        for m in imported_modules
        if not any(m == p or m.startswith(p) for p in allowed_prefixes)
    ]
    check(
        len(unexpected) == 0,
        f"S12: only the expected modules are imported (unexpected: {unexpected})",
    )


# ---------------------------------------------------------------------------
# Public API surface check (supports several scenarios' "pure builder" claim)
# ---------------------------------------------------------------------------
def scenario_no_extra_public_methods() -> None:
    public_methods = [
        name
        for name in dir(NotificationBuilder)
        if not name.startswith("_") and callable(getattr(NotificationBuilder, name))
    ]
    # build_order_executed() was added for the paper-trading
    # notification wiring (documented in the module's own docstring
    # before Activation 6.3) -- this assertion had drifted stale,
    # corrected here during Activation 6.3 verification, no production
    # code changed.
    check(
        public_methods == ["build_daily_report", "build_order_executed"],
        f"S3/S12: NotificationBuilder has exactly its two documented "
        f"public methods (found: {public_methods})",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_has_no_dependency,
        scenario_build_daily_report_returns_notification_event,
        scenario_event_type_is_daily_report,
        scenario_timestamp_from_report_generated_at,
        scenario_message_contains_locked_fields,
        scenario_metadata_exact_keys_and_values,
        scenario_recommendations_not_enumerated,
        scenario_inputs_not_mutated,
        scenario_report_object_identity_preserved,
        scenario_performance_summary_identity_preserved,
        scenario_metadata_is_new_dict,
        scenario_no_external_dependency,
        scenario_no_extra_public_methods,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"SPRINT 7 STEP 2 NOTIFICATION BUILDER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())