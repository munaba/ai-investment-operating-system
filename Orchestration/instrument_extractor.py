from __future__ import annotations

import re
from abc import ABC, abstractmethod


class BaseInstrumentExtractor(ABC):
    """Strategy object responsible for extracting a tradable instrument from free-form user input."""

    @abstractmethod
    def extract(self, text: str) -> str:
        """Extract a tradable instrument identifier from ``text``.

        Args:
            text: Free-form user input to extract an instrument from.

        Returns:
            Normalized instrument identifier.

        Raises:
            ValueError: If no instrument can be determined.
        """
        raise NotImplementedError


class IDXTickerExtractor(BaseInstrumentExtractor):
    """Extracts an IDX ticker (e.g. "BBCA" -> "BBCA.JK") from free-form text.

    This is the source of truth for IDX ticker extraction, ported
    verbatim from the former ``StockAgent._extract_ticker`` (regex +
    stopword filter). ``StockAgent`` now delegates to this class instead
    of performing extraction itself.
    """

    _TICKER_PATTERN = re.compile(r"\b([A-Z]{4})(\.JK)?\b")

    _TICKER_STOPWORDS = frozenset({"BELI", "JUAL", "SAYA", "YANG", "ATAU"})

    def extract(self, text: str) -> str:
        """Extract an IDX ticker (e.g. "BBCA" -> "BBCA.JK") from ``text``.

        Looks for a 4-uppercase-letter token, optionally already suffixed
        with ``.JK``. Tokens in :attr:`_TICKER_STOPWORDS` (common
        Indonesian command/pronoun words such as "BELI", "JUAL", "SAYA")
        are ignored before determining the candidate(s).

        Raises:
            ValueError: If no candidate remains after filtering
                stopwords, or if more than one distinct ticker candidate
                remains (ambiguous -- never silently picked).
        """
        matches = self._TICKER_PATTERN.findall(text or "")
        candidates = [
            (base, suffix) for base, suffix in matches if base not in self._TICKER_STOPWORDS
        ]

        if not candidates:
            raise ValueError(f"Ticker tidak ditemukan pada input: {text!r}")

        unique_bases = {base for base, _ in candidates}
        if len(unique_bases) > 1:
            raise ValueError(
                f"Ditemukan lebih dari satu kandidat ticker yang ambigu "
                f"{sorted(unique_bases)!r} pada input: {text!r}"
            )

        base = candidates[0][0]
        return f"{base}.JK"
    