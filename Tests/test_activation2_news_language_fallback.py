from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Orchestration.market_news_tool import _classify_headline
from Repository.external.news_repository import NewsRepository


def main() -> int:
    title = "Bank beats earnings estimates with strong profit growth"
    sentiment, positive, negative = _classify_headline(title)
    assert sentiment == "positive"
    assert positive > negative

    # Production fallback remains a static method and therefore does not
    # require a repository instance or mutable state.
    assert isinstance(NewsRepository.__dict__["_fetch_google_news_rss"], staticmethod)

    print("ACTIVATION 2 NEWS LANGUAGE FALLBACK: 2/2 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
