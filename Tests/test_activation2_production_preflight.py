"""Activation 2 production preflight.

Checks that the documented production scanner dependency is installed and
that the runtime can reach the configured market-data provider. This test is
intentionally environment-sensitive: it never fakes network/data success.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
import urllib.error
import urllib.request


def check(condition: bool, message: str) -> None:
    print(f"  {'PASS' if condition else 'FAIL'} - {message}")
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("ACTIVATION 2 PRODUCTION PREFLIGHT")
    has_yfinance = importlib.util.find_spec("yfinance") is not None
    check(has_yfinance, "yfinance is installed (required by StockDataRepository/StockService)")

    host = os.environ.get("AIOS_MARKET_DATA_HOST", "query1.finance.yahoo.com")
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        dns_ok = True
    except OSError as exc:
        dns_ok = False
        print(f"  INFO - DNS resolution unavailable for {host}: {exc}")
    check(dns_ok, f"DNS resolves market-data host {host}")

    url = os.environ.get(
        "AIOS_MARKET_DATA_HEALTH_URL",
        "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?range=5d&interval=1d",
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            status = response.status
            body = response.read(128)
        check(status == 200, f"market-data provider returned HTTP 200 (got {status})")
        check(bool(body), "market-data provider returned a non-empty response")
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"  INFO - Provider request unavailable: {exc}")
        raise AssertionError("market-data provider is not reachable from this runtime") from exc

    print("ACTIVATION 2 PRODUCTION PREFLIGHT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
