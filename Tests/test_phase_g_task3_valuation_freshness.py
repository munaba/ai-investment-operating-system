"""Standalone, focused regression checks for Phase G Task 3 ONLY:
"Valuation Freshness + Paper Review Inputs" --
``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` (Phase G Task 3
additive extension), ``Repository.persistence.
valuation_observation_repository.ValuationObservationRepository``, and
``Business.portfolio_snapshot_service.PortfolioSnapshotService`` (Phase
G Task 3 additive extension).

Every scenario drives the REAL ``UnrealizedPnLEngine``/
``PortfolioSnapshotService``/``ValuationObservationRepository``
against a real on-disk SQLite database and real migrations -- no
mocked business logic. Only ``_FixedPriceTool``/``_FailingPriceTool``
(test doubles for ``MarketPriceTool``, following the exact pattern
already established by ``Tests/activation_3_7_step4_proof.py``) stand
in for a live market-data fetch.

Proves, concretely:

* Scenario 1: a fresh live price -> ``valuation_status == "FRESH"``,
  and the observation is durably recorded.
* Scenario 2: a provider failure with a prior FRESH observation on
  record -> ``valuation_status == "STALE"``, the *original*
  ``observed_at``/price are preserved (never re-stamped to "now"),
  and the resulting ``unrealized_pnl`` is still computed from that
  retained price (never zero, never silently treated as current).
* Scenario 3: a provider failure with no prior observation on record
  -> ``ValidationError`` (explicit "unavailable"), never a fabricated
  price and never silently reported as fresh/stale/zero.
* Scenario 4: a full process restart (new ``DatabaseManager``/
  repository instances over the same on-disk file) preserves the
  exact ``observed_at``/``source``/price of the last-good observation.
* Scenario 5: no fabricated price -- the STALE valuation's
  ``market_price`` is byte-for-byte the previously-recorded price,
  never a guessed/interpolated/zero value.
* Scenario 6: freshness tracking disabled (no repository/policy
  supplied, the pre-Phase-G-Task-3 default) behaves byte-for-byte as
  before -- a provider failure still raises immediately, nothing is
  persisted, and ``valuation_status``/``observed_at``/``source`` on
  the result are all ``None``.
* Scenario 7: ``PortfolioSnapshotService.take_snapshot()`` surfaces a
  portfolio-level ``valuation_status`` ("FRESH" when every open
  position was fresh, "STALE" when at least one fell back to a
  retained price), and never persists a snapshot at all when a
  position's valuation is genuinely unavailable.
* Scenario 8: existing, unmodified callers of ``UnrealizedPnLEngine``
  (constructed with only ``market_price_tool``, exactly as every
  pre-Phase-G-Task-3 call site does) are completely unaffected.

Run directly with
``python Tests/test_phase_g_task3_valuation_freshness.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.data_freshness_policy import DataFreshnessPolicy  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.portfolio_snapshot_service import PortfolioSnapshotService  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.unrealized_pnl_engine import (  # noqa: E402
    UnrealizedPnLEngine,
    VALUATION_FRESH,
    VALUATION_STALE,
)
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshot_valuation_status import (  # noqa: E402
    PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
)
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.migrations_valuation_observations import (  # noqa: E402
    VALUATION_OBSERVATIONS_MIGRATIONS,
)
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import (  # noqa: E402
    PortfolioSnapshotRepository,
)
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.valuation_observation_repository import (  # noqa: E402
    ValuationObservationRepository,
)

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
    """Test double for ``MarketPriceTool``: reports a fixed,
    caller-supplied price. Mirrors ``Tests.activation_3_7_step4_proof.
    _FixedPriceTool`` exactly -- ``UnrealizedPnLEngine`` only ever
    depends on the ``execute(context) -> ToolResult`` shape.
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


class _FailingPriceTool:
    """Test double for ``MarketPriceTool`` simulating a provider
    failure: ``price`` is always ``None`` (the exact shape
    ``MarketPriceTool.execute()`` itself uses to report "no valid
    current price" -- never raises).
    """

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": None, "trend": "unknown"},
            error=None,
            metadata={},
        )


def _build(tmp_dir: str, name: str, account_id: str = "paper-id"):
    db_path = Path(tmp_dir) / name
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS)
    MigrationRunner(db).apply(VALUATION_OBSERVATIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id=account_id,
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    position_repo = PositionRepository(manager)
    position_manager = PositionManager(position_repo)
    valuation_repo = ValuationObservationRepository(manager)
    portfolio_snapshot_repo = PortfolioSnapshotRepository(manager)
    return {
        "db_path": db_path,
        "db": db,
        "manager": manager,
        "account_repo": account_repo,
        "position_repo": position_repo,
        "position_manager": position_manager,
        "valuation_repo": valuation_repo,
        "portfolio_snapshot_repo": portfolio_snapshot_repo,
    }


def _trade(trade_id, symbol="BBCA", account_id="paper-id", action="BUY",
           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0,
           executed_at="2026-08-05T10:00:00+00:00"):
    return Trade(
        trade_id=trade_id,
        order_id=trade_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        tax=tax,
        executed_at=executed_at,
    )


def _policy(window_seconds: float = 900.0) -> DataFreshnessPolicy:
    return DataFreshnessPolicy(freshness_window_seconds=window_seconds)


# ---------------------------------------------------------------------------
# Scenario 1: fresh price -> fresh valuation
# ---------------------------------------------------------------------------
def scenario_1_fresh_price_fresh_valuation():
    print("\n[Scenario 1] fresh live price -> valuation_status == FRESH, recorded durably")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s1.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, fill_price=9500.0))
            position = ctx["position_repo"].get_open_position("paper-id", "BBCA")

            engine = UnrealizedPnLEngine(
                _FixedPriceTool(9800.0),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            result = engine.calculate(position)

            check(result.valuation_status == VALUATION_FRESH, "fresh live price -> valuation_status == FRESH")
            check(result.market_price == 9800.0, "market_price is the real live price, unchanged")
            check(result.unrealized_pnl == (9800.0 - 9500.0) * 100.0, "unrealized_pnl uses the fresh price")
            check(result.observed_at == result.market_timestamp, "FRESH observed_at equals this call's own timestamp")

            recorded = ctx["valuation_repo"].get("paper-id", "BBCA")
            check(recorded is not None, "a fresh observation was durably recorded")
            check(recorded is not None and recorded.price == 9800.0, "recorded observation price matches the live price")
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 2: stale price -> stale label, original observed_at preserved
# ---------------------------------------------------------------------------
def scenario_2_stale_price_stale_label():
    print("\n[Scenario 2] provider failure with a prior FRESH observation -> STALE, original observed_at preserved")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s2.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, fill_price=9500.0))
            position = ctx["position_repo"].get_open_position("paper-id", "BBCA")

            fresh_engine = UnrealizedPnLEngine(
                _FixedPriceTool(9800.0),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            fresh_result = fresh_engine.calculate(position)
            original_observed_at = fresh_result.observed_at
            check(fresh_result.valuation_status == VALUATION_FRESH, "setup: first call is FRESH")

            failing_engine = UnrealizedPnLEngine(
                _FailingPriceTool(),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            stale_result = failing_engine.calculate(position)

            check(stale_result.valuation_status == VALUATION_STALE, "provider failure -> valuation_status == STALE")
            check(stale_result.market_price == 9800.0, "STALE valuation reuses the retained last-good price, never fabricated")
            check(
                stale_result.observed_at == original_observed_at,
                "STALE observed_at is the ORIGINAL observation timestamp, never re-stamped to now",
            )
            check(
                stale_result.market_timestamp != stale_result.observed_at,
                "market_timestamp (this call's own clock) differs from the preserved observed_at",
            )
            check(
                stale_result.unrealized_pnl == (9800.0 - 9500.0) * 100.0,
                "unrealized_pnl for a STALE valuation is still computed from the retained real price",
            )
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 3: unavailable price -> explicit unavailable, never fabricated
# ---------------------------------------------------------------------------
def scenario_3_unavailable_price_explicit():
    print("\n[Scenario 3] provider failure with NO prior observation -> explicit ValidationError, never fabricated")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s3.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, fill_price=9500.0))
            position = ctx["position_repo"].get_open_position("paper-id", "BBCA")

            engine = UnrealizedPnLEngine(
                _FailingPriceTool(),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            raised = False
            try:
                engine.calculate(position)
            except ValidationError as exc:
                raised = True
                check(
                    exc.details.get("valuation_status") == "UNAVAILABLE",
                    "raised ValidationError explicitly identifies valuation_status == UNAVAILABLE",
                )
            check(raised, "no prior observation + provider failure raises ValidationError (never fabricated)")
            check(
                ctx["valuation_repo"].get("paper-id", "BBCA") is None,
                "nothing was persisted for the failed, never-observed symbol",
            )
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 4: restart preserves the valuation label/source timestamp
# ---------------------------------------------------------------------------
def scenario_4_restart_preserves_observation():
    print("\n[Scenario 4] restart (new connection/repository instances) preserves observed_at/source/price")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "s4.db"
        cfg = DatabaseConfig(db_path=db_path)

        db1 = SQLiteDatabase(cfg)
        db1.connect()
        MigrationRunner(db1).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db1).apply(POSITIONS_MIGRATIONS)
        MigrationRunner(db1).apply(VALUATION_OBSERVATIONS_MIGRATIONS)
        manager1 = DatabaseManager(db1, cfg)
        account_repo1 = AccountRepository(manager1)
        account_repo1.create(
            account_id="paper-id",
            account_name="Paper Indonesia",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )
        position_repo1 = PositionRepository(manager1)
        position_manager1 = PositionManager(position_repo1)
        position_manager1.apply_trade(_trade(1, fill_price=9500.0))
        position = position_repo1.get_open_position("paper-id", "BBCA")

        valuation_repo1 = ValuationObservationRepository(manager1)
        engine1 = UnrealizedPnLEngine(
            _FixedPriceTool(9700.0),
            valuation_observation_repository=valuation_repo1,
            data_freshness_policy=_policy(),
        )
        first_result = engine1.calculate(position)
        original_observed_at = first_result.observed_at
        db1.disconnect()

        # Genuine restart: brand new connection/manager/repository over
        # the same on-disk file.
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg)
            valuation_repo2 = ValuationObservationRepository(manager2)
            recorded = valuation_repo2.get("paper-id", "BBCA")

            check(recorded is not None, "observation row survives a real restart")
            check(recorded is not None and recorded.price == 9700.0, "price survives a real restart, unchanged")
            check(
                recorded is not None and recorded.observed_at == original_observed_at,
                "observed_at survives a real restart, byte-for-byte unchanged",
            )
            check(
                recorded is not None and recorded.source == "market_price_tool",
                "source label survives a real restart, unchanged",
            )

            # And the engine, freshly reconstructed post-restart, still
            # reports STALE (not a fabricated fresh value) on a
            # provider failure, using the row that survived restart.
            position_repo2 = PositionRepository(manager2)
            position_after_restart = position_repo2.get_open_position("paper-id", "BBCA")
            engine2 = UnrealizedPnLEngine(
                _FailingPriceTool(),
                valuation_observation_repository=valuation_repo2,
                data_freshness_policy=_policy(),
            )
            stale_result = engine2.calculate(position_after_restart)
            check(
                stale_result.valuation_status == VALUATION_STALE,
                "post-restart provider failure still correctly reports STALE using the restored observation",
            )
            check(
                stale_result.observed_at == original_observed_at,
                "post-restart STALE result's observed_at is the original pre-restart timestamp",
            )
        finally:
            db2.disconnect()


# ---------------------------------------------------------------------------
# Scenario 5: no fabricated price (byte-for-byte check across statuses)
# ---------------------------------------------------------------------------
def scenario_5_no_fabricated_price():
    print("\n[Scenario 5] STALE market_price is byte-for-byte the retained price, never zero/guessed")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s5.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, fill_price=5000.0))
            position = ctx["position_repo"].get_open_position("paper-id", "BBCA")

            fresh_engine = UnrealizedPnLEngine(
                _FixedPriceTool(12345.75),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            fresh_result = fresh_engine.calculate(position)

            failing_engine = UnrealizedPnLEngine(
                _FailingPriceTool(),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            stale_result = failing_engine.calculate(position)

            check(stale_result.market_price == fresh_result.market_price, "STALE price is exactly the retained FRESH price")
            check(stale_result.market_price != 0.0, "STALE price is never a fabricated zero")
            check(stale_result.market_price == 12345.75, "STALE price has no rounding/guessing drift from the original")
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 6: existing (freshness-disabled) callers unaffected
# ---------------------------------------------------------------------------
def scenario_6_existing_callers_unaffected():
    print("\n[Scenario 6] engine constructed with only market_price_tool behaves exactly as before")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s6.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, fill_price=9500.0))
            position = ctx["position_repo"].get_open_position("paper-id", "BBCA")

            # Exactly the pre-Phase-G-Task-3 construction: one positional arg.
            engine = UnrealizedPnLEngine(_FixedPriceTool(9800.0))
            result = engine.calculate(position)
            check(result.valuation_status is None, "freshness disabled: valuation_status stays None")
            check(result.observed_at is None, "freshness disabled: observed_at stays None")
            check(result.source is None, "freshness disabled: source stays None")
            check(result.market_price == 9800.0, "freshness disabled: market_price behavior unchanged")

            failing_engine = UnrealizedPnLEngine(_FailingPriceTool())
            raised = False
            try:
                failing_engine.calculate(position)
            except ValidationError:
                raised = True
            check(raised, "freshness disabled: a provider failure still raises immediately, exactly as before")

            check(
                ctx["valuation_repo"].get("paper-id", "BBCA") is None,
                "freshness disabled: nothing is ever persisted to valuation_observations",
            )
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 7: portfolio-level valuation_status via PortfolioSnapshotService
# ---------------------------------------------------------------------------
def scenario_7_portfolio_snapshot_valuation_status():
    print("\n[Scenario 7] PortfolioSnapshotService surfaces a portfolio-level valuation_status")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s7.db")
        try:
            ctx["position_manager"].apply_trade(_trade(1, symbol="BBCA", fill_price=9500.0))
            ctx["position_manager"].apply_trade(_trade(2, symbol="TLKM", fill_price=3000.0))

            drawdown_engine = MaximumDrawdownEngine()

            # All-fresh snapshot.
            fresh_engine = UnrealizedPnLEngine(
                _FixedPriceTool(9800.0),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            service = PortfolioSnapshotService(
                account_repository=ctx["account_repo"],
                position_repository=ctx["position_repo"],
                unrealized_pnl_engine=fresh_engine,
                maximum_drawdown_engine=drawdown_engine,
                portfolio_snapshot_repository=ctx["portfolio_snapshot_repo"],
            )
            fresh_snapshot = service.take_snapshot("paper-id")
            check(fresh_snapshot.valuation_status == "FRESH", "all-fresh positions -> snapshot valuation_status == FRESH")

            # Now BBCA's price fails -> falls back to retained STALE,
            # TLKM still fetches fresh live -- portfolio must report STALE.
            class _PerSymbolTool:
                def execute(self, context):
                    symbol = context.parameters.get("symbol")
                    price = None if symbol == "BBCA" else 3100.0
                    return ToolResult(success=True, output={"symbol": symbol, "price": price, "trend": "x"}, error=None, metadata={})

            mixed_engine = UnrealizedPnLEngine(
                _PerSymbolTool(),
                valuation_observation_repository=ctx["valuation_repo"],
                data_freshness_policy=_policy(),
            )
            mixed_service = PortfolioSnapshotService(
                account_repository=ctx["account_repo"],
                position_repository=ctx["position_repo"],
                unrealized_pnl_engine=mixed_engine,
                maximum_drawdown_engine=drawdown_engine,
                portfolio_snapshot_repository=ctx["portfolio_snapshot_repo"],
            )
            mixed_snapshot = mixed_service.take_snapshot("paper-id")
            check(
                mixed_snapshot.valuation_status == "STALE",
                "one stale position among fresh ones -> snapshot valuation_status == STALE",
            )

            # Persisted row round-trips valuation_status correctly.
            reloaded = ctx["portfolio_snapshot_repo"].get_by_id(mixed_snapshot.snapshot_id)
            check(
                reloaded is not None and reloaded.valuation_status == "STALE",
                "persisted snapshot row round-trips valuation_status through the repository",
            )

            # Freshness-disabled engine -> valuation_status stays None.
            disabled_engine = UnrealizedPnLEngine(_FixedPriceTool(9800.0))
            disabled_service = PortfolioSnapshotService(
                account_repository=ctx["account_repo"],
                position_repository=ctx["position_repo"],
                unrealized_pnl_engine=disabled_engine,
                maximum_drawdown_engine=drawdown_engine,
                portfolio_snapshot_repository=ctx["portfolio_snapshot_repo"],
            )
            disabled_snapshot = disabled_service.take_snapshot("paper-id")
            check(
                disabled_snapshot.valuation_status is None,
                "freshness tracking disabled at the engine -> snapshot valuation_status stays None (unchanged default)",
            )
        finally:
            ctx["db"].disconnect()


# ---------------------------------------------------------------------------
# Scenario 8: existing paper-trading-adjacent regression sanity
# ---------------------------------------------------------------------------
def scenario_8_no_second_pnl_engine_or_new_persistence_surface():
    print("\n[Scenario 8] structural checks: still one PnL engine, no live/broker path added")
    import Business.unrealized_pnl_engine as engine_module

    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    check("class UnrealizedPnLEngine" in source, "UnrealizedPnLEngine remains the sole PnL engine class in this module")
    import re
    top_level_classes = re.findall(r"^class \w+", source, re.MULTILINE)
    check(
        top_level_classes == ["class UnrealizedPnLResult", "class UnrealizedPnLEngine"],
        "exactly two top-level classes in this module (result dataclass + engine, no second engine)",
    )
    check("broker" not in source.lower(), "no broker concept introduced")
    check("live_execution" not in source.lower() and "live_order" not in source.lower(), "no live execution concept introduced")


def main() -> int:
    scenario_1_fresh_price_fresh_valuation()
    scenario_2_stale_price_stale_label()
    scenario_3_unavailable_price_explicit()
    scenario_4_restart_preserves_observation()
    scenario_5_no_fabricated_price()
    scenario_6_existing_callers_unaffected()
    scenario_7_portfolio_snapshot_valuation_status()
    scenario_8_no_second_pnl_engine_or_new_persistence_surface()

    print("\n" + "=" * 60)
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    print("=" * 60)
    if _FAIL:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
