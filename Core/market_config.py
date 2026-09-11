"""Market selection helpers for CLI paper validation."""
from __future__ import annotations

import os


#: Recognized crypto symbols for the Activation 7 Crypto Validation
#: Profile (LOCKED, narrow scope -- exactly the two symbols the
#: activation brief named). Not auto-detected from a "-USD" suffix or
#: any other heuristic: an explicit, reviewable allowlist, so adding a
#: third symbol later is a deliberate one-line change here, not a
#: side effect of some other string happening to match a pattern.
#: Shared by every consumer that needs to tell a crypto symbol apart
#: from a stock ticker -- ``Orchestration.market_analysis_skill.
#: MarketAnalysisSkill`` (routing to ``CryptoAnalysisSkill`` vs
#: ``TextAnalysisSkill``) and ``main.py`` (routing a ``paper buy``/
#: ``paper sell`` order to the ``crypto-usd`` account vs the default
#: IDR ``paper`` account) -- so the two can never silently drift
#: apart into disagreeing about what counts as "crypto".
CRYPTO_SYMBOLS: frozenset[str] = frozenset({"BTC-USD", "ETH-USD"})


def is_crypto_symbol(symbol: str) -> bool:
    """Return whether ``symbol`` is a recognized crypto symbol.

    Case-insensitive (mirrors how CLI commands already upper-case
    symbols before use, e.g. ``main.py``'s ``_run_paper_buy_command``)
    but otherwise an exact match against ``CRYPTO_SYMBOLS`` -- no
    prefix/suffix heuristic, no partial match.

    Args:
        symbol: The symbol to check, in any case.

    Returns:
        ``True`` if ``symbol.upper()`` is in ``CRYPTO_SYMBOLS``,
        ``False`` otherwise (including for ``None`` or a non-``str``,
        which this function treats defensively as "not crypto" rather
        than raising).
    """
    if not isinstance(symbol, str):
        return False
    return symbol.upper() in CRYPTO_SYMBOLS



def is_forex_pair(symbol: str) -> bool:
    """Return whether ``symbol`` is one of the LOCKED Forex pairs.

    The import is intentionally lazy so ``Core.market_config`` stays a
    low-level market-context module and does not participate in the
    Business package's import graph.
    """
    if not isinstance(symbol, str):
        return False
    from Business.forex_pip_policy import SUPPORTED_PIP_VALUE_PAIRS, _normalize_pair
    try:
        return _normalize_pair(symbol) in SUPPORTED_PIP_VALUE_PAIRS
    except Exception:
        return False

def current_market() -> str:
    """Return the active market, defaulting to the existing IDX behavior."""
    return os.getenv("AIOS_MARKET", "idx").strip().lower() or "idx"


def resolve_provider_symbol(symbol: str) -> str:
    """Resolve a watchlist symbol to the provider symbol for the active market."""
    if "." in symbol:
        return symbol
    market = current_market()
    if market in ("us", "crypto"):
        return symbol
    if market == "forex":
        from Business.forex_pip_policy import SUPPORTED_PIP_VALUE_PAIRS, _normalize_pair
        try:
            pair = _normalize_pair(symbol)
        except Exception:
            return symbol
        if pair in SUPPORTED_PIP_VALUE_PAIRS:
            return pair.replace("/", "") + "=X"
        return symbol
    return f"{symbol}.JK"
