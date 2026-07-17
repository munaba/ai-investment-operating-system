"""Single source of truth for request-level default values.

These values were previously duplicated as local module constants inside
individual services (``Services.stock_service`` and
``Services.news_service``). They are now defined once, here, and consumed
from two places:

1. ``Agents.stock_agent.StockAgent._build_context`` seeds them into the
   initial ``ServiceContext.metadata`` for every request, so every
   downstream service in the pipeline sees the same values up front.
2. The services that previously hard-coded these values (``StockService``,
   ``NewsService``) still pass them as the ``default`` argument to
   ``ServiceContext.get_metadata(key, default)``. This preserves identical
   behavior for any caller that invokes a service directly without going
   through ``StockAgent`` (e.g. unit tests), while eliminating the
   duplicated literal values.
"""

from __future__ import annotations

#: Default ticker symbol, used when no ticker is supplied.
DEFAULT_TICKER: str = "BBCA.JK"

#: Default lookback period for OHLCV history requests (yfinance ``period``).
DEFAULT_PERIOD: str = "6mo"

#: Default bar interval for OHLCV history requests (yfinance ``interval``).
DEFAULT_INTERVAL: str = "1d"

#: Default maximum number of news items to fetch.
DEFAULT_MAX_NEWS: int = 10
