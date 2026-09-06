"""Standalone regression checks for ``Repository.external.news_repository.NewsRepository``.

Covers the repository-extraction sprint for ``NewsService``:

* the repository returns the raw ``yfinance`` news payload unchanged
  (no ``or []`` fallback, no ``isinstance`` normalization);
* ``None``/non-list payloads are only normalized in ``NewsService``,
  never in the repository;
* SDK failures (including a missing/unresolvable ``yfinance`` module)
  surface as exactly one ``RepositoryError``, never a nested
  ``RepositoryError`` wrapping another ``RepositoryError``;
* ``NewsService.execute()`` translates a ``RepositoryError`` back into a
  failed ``ServiceResult`` carrying the original message text
  ``"Failed to fetch news for ticker '<ticker>'"``.

Run directly with ``python Tests/test_news_repository.py`` -- no external
test framework required, matching ``integration_test.py`` and
``test_stock_agent_smoke.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import RepositoryError  # noqa: E402
from Repository.external.news_repository import NewsRepository  # noqa: E402
from Services.news_service import NewsService  # noqa: E402
from Services.service_context import ServiceContext  # noqa: E402


# =========================================================================
# Minimal test harness (no external test framework required to run this)
# =========================================================================

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


# =========================================================================
# Fakes
# =========================================================================


class _FakeTicker:
    """Stand-in for a single ``yfinance.Ticker`` instance."""

    def __init__(self, news: Any = "__unset__", raise_on_news: bool = False) -> None:
        self._raise_on_news = raise_on_news
        if news != "__unset__":
            self.news = news
        # else: deliberately no `.news` attribute at all.

    def __getattribute__(self, item: str) -> Any:
        if item == "news" and object.__getattribute__(self, "_raise_on_news"):
            raise RuntimeError("Simulated yfinance SDK failure")
        return object.__getattribute__(self, item)


class _FakeYFinanceModule:
    """Fake ``yfinance`` module: ``.Ticker(symbol)`` -> ``_FakeTicker``."""

    def __init__(self, news: Any = "__unset__", raise_on_news: bool = False) -> None:
        self._news = news
        self._raise_on_news = raise_on_news
        self.requested_symbols: List[str] = []

    def Ticker(self, symbol: str) -> _FakeTicker:  # noqa: N802 - mirrors yfinance's API
        self.requested_symbols.append(symbol)
        return _FakeTicker(news=self._news, raise_on_news=self._raise_on_news)


def _make_context(ticker: str = "BBCA.JK", max_news: Optional[int] = None) -> ServiceContext:
    metadata = {"ticker": ticker}
    if max_news is not None:
        metadata["max_news"] = max_news
    return ServiceContext(
        agent_name="test_agent",
        provider_name="test_provider",
        request_id="test-request-1",
        user_input="test",
        metadata=metadata,
    )


class _ForceYFinanceUnavailable:
    """Context manager that makes ``import yfinance`` raise ``ImportError``.

    Manual replacement for pytest's ``monkeypatch.setitem`` fixture:
    temporarily sets ``sys.modules["yfinance"] = None`` (which forces the
    next ``import yfinance`` to raise ``ImportError``), then restores the
    previous state exactly on exit -- whether or not one was already
    present.
    """

    _SENTINEL = object()

    def __enter__(self) -> "_ForceYFinanceUnavailable":
        self._previous = sys.modules.get("yfinance", self._SENTINEL)
        sys.modules["yfinance"] = None  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._previous is self._SENTINEL:
            sys.modules.pop("yfinance", None)
        else:
            sys.modules["yfinance"] = self._previous


# =========================================================================
# 1. Raw payload is passed through unchanged
# =========================================================================


def test_get_news_returns_raw_payload_unchanged() -> None:
    raw_payload = [
        {"title": "Foo", "publisher": "Bar", "unexpected_field": {"nested": True}},
        {"content": {"title": "Baz"}},
    ]
    module = _FakeYFinanceModule(news=raw_payload)
    repo = NewsRepository(yfinance_module=module)

    result = repo.get_news("BBCA.JK")

    check(result is raw_payload, "NewsRepository.get_news returns the raw payload object unchanged")
    check(module.requested_symbols == ["BBCA.JK"], "NewsRepository.get_news requested the correct ticker symbol")


# =========================================================================
# 2. None/non-list payloads are NOT normalized by the repository
# =========================================================================


def test_get_news_returns_none_when_news_attribute_absent() -> None:
    module = _FakeYFinanceModule(news="__unset__")  # no `.news` attribute on the fake Ticker
    repo = NewsRepository(yfinance_module=module)

    result = repo.get_news("BBCA.JK")

    check(result is None, "NewsRepository.get_news returns None (not []) when .news attribute is absent")


def test_get_news_returns_non_list_payload_unchanged() -> None:
    module = _FakeYFinanceModule(news={"unexpected": "shape"})
    repo = NewsRepository(yfinance_module=module)

    result = repo.get_news("BBCA.JK")

    check(
        result == {"unexpected": "shape"},
        "NewsRepository.get_news returns a non-list payload as-is (not coerced to [])",
    )


def test_news_service_normalizes_none_payload_to_empty_result() -> None:
    module = _FakeYFinanceModule(news="__unset__")
    service = NewsService(yfinance_module=module)

    result = service.execute(_make_context())

    check(result.success is True, "NewsService.execute succeeds when the raw payload is None")
    check(result.data["total_news"] == 0, "NewsService normalizes a None payload to total_news == 0")
    check(result.data["news"] == [], "NewsService normalizes a None payload to an empty news list")


def test_news_service_normalizes_non_list_payload_to_empty_result() -> None:
    module = _FakeYFinanceModule(news={"unexpected": "shape"})
    service = NewsService(yfinance_module=module)

    result = service.execute(_make_context())

    check(result.success is True, "NewsService.execute succeeds when the raw payload is a non-list")
    check(result.data["total_news"] == 0, "NewsService normalizes a non-list payload to total_news == 0")
    check(result.data["news"] == [], "NewsService normalizes a non-list payload to an empty news list")


# =========================================================================
# 3. SDK exceptions become exactly one RepositoryError
# =========================================================================


def test_get_news_wraps_sdk_exception_in_single_repository_error() -> None:
    module = _FakeYFinanceModule(news=[], raise_on_news=True)
    repo = NewsRepository(yfinance_module=module)

    try:
        repo.get_news("BBCA.JK")
        check(False, "NewsRepository.get_news raises RepositoryError when the SDK call fails")
    except RepositoryError as exc:
        check(True, "NewsRepository.get_news raises RepositoryError when the SDK call fails")
        check(
            isinstance(exc.__cause__, RuntimeError) and "Simulated yfinance SDK failure" in str(exc.__cause__),
            "RepositoryError's __cause__ is the original SDK exception",
        )
        check(
            not isinstance(exc.__cause__, RepositoryError),
            "RepositoryError is not nested (cause is not itself a RepositoryError)",
        )
    except Exception as exc:  # noqa: BLE001 - this IS the thing under test
        check(False, f"NewsRepository.get_news raised {type(exc).__name__} instead of RepositoryError")


def test_get_news_raises_single_repository_error_when_yfinance_unavailable() -> None:
    # No injected module, and the real `yfinance` package is made unimportable.
    with _ForceYFinanceUnavailable():
        repo = NewsRepository(yfinance_module=None)
        try:
            repo.get_news("BBCA.JK")
            check(False, "NewsRepository.get_news raises RepositoryError when yfinance is unavailable")
        except RepositoryError as exc:
            check(True, "NewsRepository.get_news raises RepositoryError when yfinance is unavailable")
            check(isinstance(exc.__cause__, ImportError), "RepositoryError's __cause__ is the original ImportError")
            check(
                not isinstance(exc.__cause__, RepositoryError),
                "RepositoryError is not nested when client resolution fails (single wrap, not double)",
            )
        except Exception as exc:  # noqa: BLE001 - this IS the thing under test
            check(False, f"NewsRepository.get_news raised {type(exc).__name__} instead of RepositoryError")


# =========================================================================
# 4. NewsService.execute() preserves the old failure message
# =========================================================================


def test_news_service_execute_preserves_legacy_failure_message_on_sdk_error() -> None:
    module = _FakeYFinanceModule(news=[], raise_on_news=True)
    service = NewsService(yfinance_module=module)

    result = service.execute(_make_context(ticker="BBCA.JK"))

    check(result.success is False, "NewsService.execute fails when the repository raises RepositoryError")
    check(
        "Failed to fetch news for ticker 'BBCA.JK'" in result.message,
        "Failure message preserves the legacy text \"Failed to fetch news for ticker '...'\"",
    )
    check(
        "Unexpected error while fetching news" not in result.message,
        "Failure message is NOT the generic 'Unexpected error while fetching news' fallback",
    )


def test_news_service_health_check_true_when_client_resolvable() -> None:
    module = _FakeYFinanceModule(news=[])
    service = NewsService(yfinance_module=module)

    check(service.health_check() is True, "NewsService.health_check() is True when the client can be resolved")


def test_news_service_health_check_false_when_yfinance_unavailable() -> None:
    with _ForceYFinanceUnavailable():
        service = NewsService(yfinance_module=None)
        check(
            service.health_check() is False,
            "NewsService.health_check() is False when yfinance is unavailable",
        )


# =========================================================================
# Runner
# =========================================================================


def main() -> int:
    scenarios = [
        test_get_news_returns_raw_payload_unchanged,
        test_get_news_returns_none_when_news_attribute_absent,
        test_get_news_returns_non_list_payload_unchanged,
        test_news_service_normalizes_none_payload_to_empty_result,
        test_news_service_normalizes_non_list_payload_to_empty_result,
        test_get_news_wraps_sdk_exception_in_single_repository_error,
        test_get_news_raises_single_repository_error_when_yfinance_unavailable,
        test_news_service_execute_preserves_legacy_failure_message_on_sdk_error,
        test_news_service_health_check_true_when_client_resolvable,
        test_news_service_health_check_false_when_yfinance_unavailable,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception as exc:  # noqa: BLE001 - a scenario itself must never crash the runner
            check(False, f"{scenario.__name__} raised an unexpected exception: {type(exc).__name__}: {exc}")

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"NEWS REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())