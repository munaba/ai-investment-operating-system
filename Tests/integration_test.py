

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

#
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from Services.service_context import ServiceContext  # noqa: E402
from Services.service_result import ServiceResult  # noqa: E402
from Services.stock_service import StockService  # noqa: E402
from Services.chart_service import ChartService  # noqa: E402
from Services.news_service import NewsService  # noqa: E402
from Services.backtest_service import BacktestService  # noqa: E402
from Services.notification_service import NotificationService  # noqa: E402



class _FakeYFTicker:
    """Stand-in for a single ``yfinance.Ticker`` instance."""

    def __init__(self, symbol: str, has_data: bool = True, has_news: bool = True) -> None:
        self.symbol = symbol
        self._has_data = has_data
        self._has_news = has_news

    @property
    def info(self) -> Dict[str, Any]:
        return {"shortName": f"{self.symbol} Inc.", "sector": "Financials"}

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        if not self._has_data:
            return pd.DataFrame()

        periods = 80
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=periods, freq="D")
        rows: List[Dict[str, Any]] = []
        price = 1000.0
        for i, current_date in enumerate(dates):
            open_price = price
            drift = 1.004 if (i // 5) % 2 == 0 else 0.996
            close_price = open_price * drift
            high_price = max(open_price, close_price) * 1.01
            low_price = min(open_price, close_price) * 0.99
            rows.append(
                {
                    "Date": current_date,
                    "Open": open_price,
                    "High": high_price,
                    "Low": low_price,
                    "Close": close_price,
                    "Volume": 1_000_000 + i * 500,
                }
            )
            price = close_price

        return pd.DataFrame(rows).set_index("Date")

    @property
    def news(self) -> List[Dict[str, Any]]:
        if not self._has_news:
            return []
        return [
            {
                "title": f"{self.symbol} reports strong quarterly earnings",
                "publisher": "Fake Wire",
                "link": "https://example.com/news/1",
                "providerPublishTime": 1700000000,
                "summary": "Quarterly earnings beat expectations.",
                "relatedTickers": [self.symbol],
            },
            {
                "title": f"Analysts upgrade {self.symbol} outlook",
                "publisher": "Fake Wire",
                "link": "https://example.com/news/2",
                "providerPublishTime": 1700003600,
                "summary": "Analysts see continued growth.",
                "relatedTickers": [self.symbol],
            },
        ]


class FakeYFinanceModule:
    """Test double standing in for the real ``yfinance`` module.

    Used to inject into both ``StockService`` and ``NewsService`` via
    their existing ``yfinance_module`` constructor parameter, so neither
    network access nor the real ``yfinance`` package is required.
    """

    def __init__(self, empty_tickers: Optional[set] = None, no_news_tickers: Optional[set] = None) -> None:
        self._empty_tickers = empty_tickers or set()
        self._no_news_tickers = no_news_tickers or set()

    def Ticker(self, symbol: str) -> _FakeYFTicker:
        return _FakeYFTicker(
            symbol,
            has_data=symbol not in self._empty_tickers,
            has_news=symbol not in self._no_news_tickers,
        )


class _FakeTrace:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeGraphObjects:
    """Stand-in for ``plotly.graph_objects``."""

    def Candlestick(self, **kwargs: Any) -> _FakeTrace:
        return _FakeTrace(kind="candlestick", **kwargs)

    def Scatter(self, **kwargs: Any) -> _FakeTrace:
        return _FakeTrace(kind="scatter", **kwargs)

    def Bar(self, **kwargs: Any) -> _FakeTrace:
        return _FakeTrace(kind="bar", **kwargs)


class _FakeFigure:
    """Stand-in for a ``plotly.graph_objects.Figure`` built by ``make_subplots``."""

    def __init__(self, **kwargs: Any) -> None:
        self.traces: List[Any] = []
        self.layout: Dict[str, Any] = {}
        self._kwargs = kwargs

    def add_trace(self, trace: Any, row: Optional[int] = None, col: Optional[int] = None) -> "_FakeFigure":
        self.traces.append((trace, row, col))
        return self

    def update_layout(self, **kwargs: Any) -> "_FakeFigure":
        self.layout.update(kwargs)
        return self

    def write_image(self, path: str) -> None:
        # Simulate an image export without requiring the optional
        # `kaleido` package.
        with open(path, "wb") as file_obj:
            file_obj.write(b"FAKE_IMAGE_BYTES")


def _fake_make_subplots(**kwargs: Any) -> _FakeFigure:
    return _FakeFigure(**kwargs)


class _FakeHTTPResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[Dict[str, Any]] = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def json(self) -> Dict[str, Any]:
        return self._json_data


class MockHTTPClient:
    """Test double for ``requests``. Records calls; NEVER touches the network.

    Injected into ``NotificationService`` via its existing ``http_client``
    constructor parameter.
    """

    def __init__(self, discord_status: int = 204, telegram_ok: bool = True) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._discord_status = discord_status
        self._telegram_ok = telegram_ok

    def post(
        self,
        url: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> _FakeHTTPResponse:
        self.calls.append({"url": url, "json": json, "data": data, "files": files, "timeout": timeout})

        if "discord" in url or "webhook" in url:
            return _FakeHTTPResponse(status_code=self._discord_status, text="ok")
        if "telegram" in url:
            return _FakeHTTPResponse(
                status_code=200,
                json_data={"ok": self._telegram_ok, "result": {"message_id": 1}},
            )
        return _FakeHTTPResponse(status_code=404, text="not found")


# =========================================================================
# Minimal test harness (no external test framework required to run this)
# =========================================================================


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


_RESULTS: List[CheckResult] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _RESULTS.append(CheckResult(name=name, passed=bool(condition), detail=detail))


def run_no_leak(name: str, fn: Any) -> Any:
    """Run ``fn()`` and fail the check if it raises -- execute()/health_check()
    must never leak an exception per BaseService's documented contract.
    """
    try:
        result = fn()
        check(f"{name}: no exception leaked", True)
        return result
    except Exception as exc:  # noqa: BLE001 - this IS the thing under test
        check(f"{name}: no exception leaked", False, f"{type(exc).__name__}: {exc}")
        return None


def make_context(**metadata: Any) -> ServiceContext:
    return ServiceContext(
        agent_name="integration_test",
        provider_name="none",
        request_id=str(uuid.uuid4()),
        user_input="integration test run",
        metadata=metadata,
    )


# =========================================================================
# Test sections
# =========================================================================


def test_instantiation_and_health_checks() -> Dict[str, Any]:
    """✓ Semua service bisa di-instantiate, ✓ health_check()."""
    yfinance_module = FakeYFinanceModule()
    http_client = MockHTTPClient()

    stock_service = run_no_leak("instantiate StockService", lambda: StockService(yfinance_module=yfinance_module))
    chart_service = run_no_leak(
        "instantiate ChartService",
        lambda: ChartService(go_module=_FakeGraphObjects(), make_subplots_func=_fake_make_subplots),
    )
    news_service = run_no_leak("instantiate NewsService", lambda: NewsService(yfinance_module=yfinance_module))
    backtest_service = run_no_leak("instantiate BacktestService", lambda: BacktestService())
    notification_service = run_no_leak(
        "instantiate NotificationService", lambda: NotificationService(http_client=http_client)
    )

    services = {
        "stock_service": stock_service,
        "chart_service": chart_service,
        "news_service": news_service,
        "backtest_service": backtest_service,
        "notification_service": notification_service,
    }
    for key, svc in services.items():
        check(f"{key} instantiated", svc is not None)

    for key, svc in services.items():
        if svc is None:
            check(f"{key}.health_check() == True", False, "service was not instantiated")
            continue
        healthy = run_no_leak(f"{key}.health_check()", svc.health_check)
        check(f"{key}.health_check() == True", healthy is True, detail=f"got {healthy!r}")

    return {
        "stock_service": stock_service,
        "chart_service": chart_service,
        "news_service": news_service,
        "backtest_service": backtest_service,
        "notification_service": notification_service,
        "http_client": http_client,
    }


def test_chain_success_path(services: Dict[str, Any]) -> None:
    """StockService -> ChartService / BacktestService -> NotificationService,
    plus NewsService independently. All must return ServiceResult.success == True.
    """
    ticker = "BBCA.JK"

    # 1) StockService produces history -----------------------------------
    stock_context = make_context(ticker=ticker, period="6mo", interval="1d")
    stock_result: ServiceResult = run_no_leak(
        "stock_service.execute", lambda: services["stock_service"].execute(stock_context)
    )
    check("StockService.execute returned a ServiceResult", isinstance(stock_result, ServiceResult))
    if not isinstance(stock_result, ServiceResult):
        return

    check("StockService.execute succeeded", stock_result.success, detail=stock_result.message)
    history = stock_result.data.get("history") if stock_result.data else None
    check("StockService produced non-empty history", bool(history), detail=f"len={len(history) if history else 0}")
    if not history:
        return

    # 2) ChartService consumes that same history --------------------------
    chart_context = make_context(ticker=ticker, history=history)
    chart_result: ServiceResult = run_no_leak(
        "chart_service.execute", lambda: services["chart_service"].execute(chart_context)
    )
    check("ChartService.execute returned a ServiceResult", isinstance(chart_result, ServiceResult))
    if isinstance(chart_result, ServiceResult):
        check("ChartService.execute succeeded using StockService's history", chart_result.success, detail=chart_result.message)
        if chart_result.success:
            figure = chart_result.data.get("figure") if chart_result.data else None
            check("ChartService produced a figure object", figure is not None)
            check(
                "ChartService figure has traces built from the shared history",
                bool(getattr(figure, "traces", None)),
            )

    # 3) BacktestService consumes that same history ------------------------
    backtest_context = make_context(history=history, strategy="ema_cross", fast_period=5, slow_period=20)
    backtest_result: ServiceResult = run_no_leak(
        "backtest_service.execute", lambda: services["backtest_service"].execute(backtest_context)
    )
    check("BacktestService.execute returned a ServiceResult", isinstance(backtest_result, ServiceResult))
    if isinstance(backtest_result, ServiceResult):
        check(
            "BacktestService.execute succeeded using StockService's history",
            backtest_result.success,
            detail=backtest_result.message,
        )
        if backtest_result.success:
            check("BacktestService result contains total_return", "total_return" in backtest_result.data)
            check("BacktestService result contains trade_history", "trade_history" in backtest_result.data)

    # 4) NewsService fetches news independently -----------------------------
    news_context = make_context(ticker=ticker, max_news=5)
    news_result: ServiceResult = run_no_leak("news_service.execute", lambda: services["news_service"].execute(news_context))
    check("NewsService.execute returned a ServiceResult", isinstance(news_result, ServiceResult))
    if isinstance(news_result, ServiceResult):
        check("NewsService.execute succeeded", news_result.success, detail=news_result.message)
        if news_result.success:
            check("NewsService produced news items", news_result.data.get("total_news", 0) > 0)

    # 5) NotificationService sends a summary using a MOCKED HTTP client -----
    summary_bits = []
    if backtest_result and backtest_result.success:
        summary_bits.append(f"return={backtest_result.data['total_return']:.2f}%")
    if news_result and news_result.success:
        summary_bits.append(f"news={news_result.data['total_news']}")
    summary_message = f"[{ticker}] " + ", ".join(summary_bits or ["no data"])

    notif_context = make_context(
        channel="discord",
        message=summary_message,
        title=f"{ticker} daily summary",
        webhook_url="https://discord.com/api/webhooks/123456789/fake-token",
    )
    notif_result: ServiceResult = run_no_leak(
        "notification_service.execute", lambda: services["notification_service"].execute(notif_context)
    )
    check("NotificationService.execute returned a ServiceResult", isinstance(notif_result, ServiceResult))
    if isinstance(notif_result, ServiceResult):
        check("NotificationService.execute succeeded", notif_result.success, detail=notif_result.message)

    http_client: MockHTTPClient = services["http_client"]
    check(
        "NotificationService used the mocked HTTP client (no real request sent)",
        len(http_client.calls) == 1 and "discord" in http_client.calls[0]["url"],
        detail=f"calls={http_client.calls}",
    )


def test_fail_paths(services: Dict[str, Any]) -> None:
    """✓ Jalur ServiceResult.fail -- one deliberate failure case per service."""

    # StockService: ticker with no data -> ServiceResult.fail
    empty_yf = FakeYFinanceModule(empty_tickers={"NODATA.JK"})
    stock_service_empty = StockService(yfinance_module=empty_yf)
    stock_fail_result: ServiceResult = run_no_leak(
        "stock_service.execute (empty ticker)",
        lambda: stock_service_empty.execute(make_context(ticker="NODATA.JK")),
    )
    if isinstance(stock_fail_result, ServiceResult):
        check("StockService.execute fails for a ticker with no data", stock_fail_result.success is False)
        check("StockService fail result carries an error", stock_fail_result.error is not None)

    # ChartService: missing history -> ServiceResult.fail
    chart_fail_result: ServiceResult = run_no_leak(
        "chart_service.execute (missing history)",
        lambda: services["chart_service"].execute(make_context(ticker="BBCA.JK")),
    )
    if isinstance(chart_fail_result, ServiceResult):
        check("ChartService.execute fails when history is missing", chart_fail_result.success is False)

    # NewsService: invalid max_news -> ServiceResult.fail
    news_fail_result: ServiceResult = run_no_leak(
        "news_service.execute (invalid max_news)",
        lambda: services["news_service"].execute(make_context(ticker="BBCA.JK", max_news=-1)),
    )
    if isinstance(news_fail_result, ServiceResult):
        check("NewsService.execute fails for invalid max_news", news_fail_result.success is False)

    # BacktestService: empty history -> ServiceResult.fail
    backtest_fail_result: ServiceResult = run_no_leak(
        "backtest_service.execute (empty history)",
        lambda: services["backtest_service"].execute(make_context(history=[])),
    )
    if isinstance(backtest_fail_result, ServiceResult):
        check("BacktestService.execute fails for empty history", backtest_fail_result.success is False)

    # NotificationService: unsupported channel -> ServiceResult.fail (still via mock client)
    notif_fail_result: ServiceResult = run_no_leak(
        "notification_service.execute (unsupported channel)",
        lambda: services["notification_service"].execute(
            make_context(channel="carrier_pigeon", message="hello")
        ),
    )
    if isinstance(notif_fail_result, ServiceResult):
        check("NotificationService.execute fails for an unsupported channel", notif_fail_result.success is False)

    # NotificationService: Discord returns a bad status code -> ServiceResult.fail
    bad_http_client = MockHTTPClient(discord_status=500)
    bad_notification_service = NotificationService(http_client=bad_http_client)
    notif_bad_status_result: ServiceResult = run_no_leak(
        "notification_service.execute (discord 500)",
        lambda: bad_notification_service.execute(
            make_context(
                channel="discord",
                message="hello",
                webhook_url="https://discord.com/api/webhooks/123/bad",
            )
        ),
    )
    if isinstance(notif_bad_status_result, ServiceResult):
        check("NotificationService.execute fails on a bad Discord status code", notif_bad_status_result.success is False)
    check(
        "NotificationService failure path still used the mocked client (no real request)",
        len(bad_http_client.calls) == 1,
    )


# =========================================================================
# Runner / report
# =========================================================================


def _print_report() -> bool:
    passed = [r for r in _RESULTS if r.passed]
    failed = [r for r in _RESULTS if not r.passed]

    print("\n" + "=" * 70)
    print("INTEGRATION TEST REPORT - Service Layer")
    print("=" * 70)
    for result in _RESULTS:
        status = "PASS" if result.passed else "FAIL"
        line = f"[{status}] {result.name}"
        if result.detail and not result.passed:
            line += f"  -- {result.detail}"
        print(line)

    print("-" * 70)
    print(f"TOTAL: {len(_RESULTS)}  PASSED: {len(passed)}  FAILED: {len(failed)}")
    print("=" * 70)

    overall = "PASS" if not failed else "FAIL"
    print(f"OVERALL RESULT: {overall}")
    print("=" * 70 + "\n")
    return not failed


def main() -> int:
    services = test_instantiation_and_health_checks()
    test_chain_success_path(services)
    test_fail_paths(services)
    success = _print_report()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())