from __future__ import annotations
from typing import Dict, List, Tuple
from Services.service_result import ServiceResult

_SECTION_ORDER: Tuple[Tuple[str, str], ...] = (
    ("stock_service", "Stock"),
    ("technical_indicator_service", "Technical Indicator"),
    ("moving_average_service", "Moving Average"),
    ("technical_score_service", "Technical Score"),
    ("fundamental_service", "Fundamental"),
    ("pattern_service", "Pattern"),
    ("news_service", "News"),
    ("chart_service", "Chart"),
    ("backtest_service", "Backtest"),
    ("risk_management_service", "Risk Management"),
    ("scoring_service", "Scoring"),
)

_FAILED_BODY: str = "FAILED"


class ToolContextBuilder:
    """Builds a single tool message string from many :class:`ServiceResult` values.

    This class is a pure formatter: it does not run services, call a
    Provider or Agent, perform network calls, or read a database. It only
    reads the ``ServiceResult`` values it is given and formats them into
    text. It never mutates its input.
    """

    @staticmethod
    def _format_data(data: object) -> str:
        """Format a successful :class:`ServiceResult`'s ``data`` payload as text.

        Args:
            data: The ``ServiceResult.data`` payload to format.

        Returns:
            A ``"key: value"`` line per entry when ``data`` is a ``dict``;
            otherwise the string representation of ``data``, or an empty
            string when ``data`` is ``None``.
        """
        if data is None:
            return ""

        if isinstance(data, dict):
            return "\n".join(f"{key}: {value}" for key, value in data.items())

        return str(data)

    @classmethod
    def _build_section(cls, label: str, result: ServiceResult) -> str:
        """Build a single ``[Label]`` section for one service result.

        Args:
            label: The display label for this section (e.g. ``"Stock"``).
            result: The service result to render.

        Returns:
            The formatted section text, including its ``[Label]`` header.
        """
        if not result.success:
            body = _FAILED_BODY
        else:
            body = cls._format_data(result.data)

        if body:
            return f"[{label}]\n{body}"

        return f"[{label}]"

    def build(self, results: Dict[str, ServiceResult]) -> str:
        """Build the combined tool message from a dict of service results.

        Services are rendered in the canonical order (``Stock``, ``Technical
        Indicator``, ``Moving Average``, ``Technical Score``, ``Fundamental``,
        ``Pattern``, ``News``, ``Chart``, ``Backtest``, ``Risk Management``,
        ``Scoring``) when present in ``results``. Keys not in the canonical
        order are ignored -- not rendered. Missing canonical services are
        simply omitted, and the pipeline never stops because of a failed
        result.

        Args:
            results: Mapping of service identifier to its ``ServiceResult``,
                e.g. ``{"stock_service": stock_result, "news_service": news_result, ...}``.

        Returns:
            The combined tool message, with one ``[Label]`` section per
            canonical entry present in ``results``, separated by a blank
            line.
        """
        sections: List[str] = [
            self._build_section(label, results[key])
            for key, label in _SECTION_ORDER
            if key in results
        ]

        return "\n\n".join(sections)