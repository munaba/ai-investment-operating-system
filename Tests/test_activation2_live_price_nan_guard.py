"""Activation 2 regression: ignore a latest NaN/empty provider candle."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Orchestration.market_price_tool import _fetch_real_prices


class _FakeServiceResult:
    success = True
    data = {
        "history": [
            {"Date": "2026-08-13", "Close": 6375.0},
            {"Date": "2026-08-14", "Close": 6350.0},
            {"Date": "2026-08-18", "Close": 6300.0},
            {"Date": "2026-08-19", "Close": float("nan")},
        ]
    }


class _FakeStockService:
    def __init__(self):
        self.last_ticker = None

    def execute(self, context):
        self.last_ticker = context.metadata["ticker"]
        return _FakeServiceResult()


def main() -> None:
    import Orchestration.market_price_tool as module

    original = module.StockService
    try:
        module.StockService = _FakeStockService
        current, previous = _fetch_real_prices("BBCA")
    finally:
        module.StockService = original

    assert current == 6300.0, (current, previous)
    assert previous == 6350.0, (current, previous)
    print("1/1 PASS")


if __name__ == "__main__":
    main()
