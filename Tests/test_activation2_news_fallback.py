from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Repository.external.news_repository import NewsRepository  # noqa: E402


def main() -> int:
    xml = b'''<?xml version="1.0"?><rss><channel><item><title>BBCA profit growth</title><link>https://example.test/a</link><pubDate>Wed, 19 Aug 2026 10:00:00 GMT</pubDate><source>Bursa Example</source></item></channel></rss>'''

    class _Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    checks = 0
    failures = []
    with patch("Repository.external.news_repository.urllib.request.urlopen", return_value=_Response(xml)):
        result = NewsRepository._fetch_google_news_rss("BBCA.JK")
        checks += 1
        if not result or result[0].get("title") != "BBCA profit growth":
            failures.append("real-client empty-news fallback returned incorrect RSS payload")
        checks += 1
        if result and result[0].get("publisher") != "Bursa Example":
            failures.append("RSS publisher was not preserved")

    # Injected test clients must remain deterministic and must not invoke fallback.
    class _InjectedTicker:
        news = []
    class _InjectedClient:
        @staticmethod
        def Ticker(symbol):
            return _InjectedTicker()

    injected = NewsRepository(yfinance_module=_InjectedClient())
    checks += 1
    if injected.get_news("BBCA.JK") != []:
        failures.append("injected yfinance client unexpectedly used RSS fallback")

    print(f"Activation 2 news fallback: {checks - len(failures)}/{checks} PASS")
    for failure in failures:
        print(f"FAIL - {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
