"""DataFreshnessPolicy -- Phase D (Proactive IDX Scheduler Routine).

Pure decision logic answering exactly one question: given the most
recent observation this process has of some external value (a price,
a scan result, a provider response -- anything with a timestamp) and
the current moment, is that observation still usable ("FRESH"), or has
it aged past its configured freshness window ("STALE")?

Hard rule (Phase D brief, "never fabricate signals"): this module
never invents a value. When an observation is missing or stale, the
result is an explicit non-action state (``STALE``/``MISSING``) that
carries the *last-good* observation forward unchanged, with its
*original* timestamp -- never a re-stamped "now", and never a
guessed/interpolated value. A caller that receives a ``STALE`` result
is expected to skip whatever action (fetch-triggered alert, ranking,
recommendation) would otherwise depend on genuinely fresh data, not to
silently use the stale value as if it were current.

This module performs no I/O and knows nothing about Telegram,
scheduler jobs, or any specific data provider -- it is intentionally
as small and generic as ``Business.execution_policy_config.
ExecutionPolicy`` ("define the parameter, do not compute anything
market-specific with it").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Optional, TypeVar

FRESH: str = "FRESH"
STALE: str = "STALE"
MISSING: str = "MISSING"

T = TypeVar("T")


@dataclass(frozen=True)
class Observation(Generic[T]):
    """One timestamped value this process observed.

    Attributes:
        value: The observed value itself (any caller-defined type --
            a price, a full scan report, a provider health payload).
        observed_at: ISO-8601 timestamp of when ``value`` was
            genuinely obtained. Never rewritten by this module.
        source: Free-text label identifying where this observation
            came from (e.g. ``"yfinance"``, ``"manual_scan_service"``)
            -- carried through for audit purposes only.
    """

    value: T
    observed_at: str
    source: str = ""


@dataclass(frozen=True)
class FreshnessResult(Generic[T]):
    """The outcome of evaluating one ``Observation`` against a
    freshness window.

    Attributes:
        status: One of ``FRESH``/``STALE``/``MISSING``.
        observation: The observation this result is about (the
            candidate if fresh, otherwise the retained last-good
            observation, unchanged) -- ``None`` only when ``status``
            is ``MISSING`` (no observation has ever been recorded).
        age_seconds: Seconds between ``observation.observed_at`` and
            the evaluation moment, or ``None`` when ``status`` is
            ``MISSING``.
        is_actionable: ``True`` only for ``FRESH`` -- the single flag
            every downstream caller should branch on before treating
            ``observation.value`` as current.
    """

    status: str
    observation: Optional[Observation[T]]
    age_seconds: Optional[float]
    is_actionable: bool


def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware ``datetime``.

    A naive timestamp (no offset) is treated as UTC -- matches the
    convention every other ISO-8601 timestamp in this codebase
    (``generated_at``, ``created_at``, etc.) already uses.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class DataFreshnessPolicy:
    """Evaluates an ``Observation`` against a configured freshness
    window and decides FRESH vs STALE, retaining the last-good value.

    Attributes:
        freshness_window_seconds: Maximum age, in seconds, an
            observation may have and still count as ``FRESH``. Must be
            a positive number -- callers construct this via
            ``load_data_freshness_policy`` in normal operation.
    """

    freshness_window_seconds: float

    def evaluate(
        self,
        candidate: Optional[Observation[T]],
        *,
        now: datetime,
        last_good: Optional[Observation[T]] = None,
    ) -> FreshnessResult[T]:
        """Decide whether ``candidate`` is fresh, and what to carry
        forward when it is not.

        Args:
            candidate: The newest observation available this tick, or
                ``None`` when this tick produced no new observation at
                all (e.g. market closed, fetch skipped by gating).
            now: The evaluation moment (timezone-aware).
            last_good: The most recent observation previously accepted
                as ``FRESH`` (typically supplied by the caller from its
                own persisted state) -- carried forward unchanged when
                ``candidate`` is absent or itself stale.

        Returns:
            A ``FreshnessResult``:

            * ``candidate`` present and its age <= window -> ``FRESH``,
              ``observation=candidate``, ``is_actionable=True``.
            * ``candidate`` present but older than the window -> the
              candidate is discarded (never used as current data);
              result is ``STALE`` and carries ``last_good`` forward
              unchanged (its own ``observed_at`` is preserved, not
              reset to ``now``).
            * ``candidate`` is ``None`` -> same ``STALE``-with-carry-
              forward behavior, using ``last_good``.
            * both ``candidate`` and ``last_good`` are ``None`` ->
              ``MISSING`` (nothing has ever been observed) --
              ``observation=None``, ``age_seconds=None``,
              ``is_actionable=False``.
        """
        if candidate is not None:
            age_seconds = (now - _parse_iso8601(candidate.observed_at)).total_seconds()
            if 0 <= age_seconds <= self.freshness_window_seconds:
                return FreshnessResult(
                    status=FRESH,
                    observation=candidate,
                    age_seconds=age_seconds,
                    is_actionable=True,
                )

        if last_good is not None:
            retained_age = (now - _parse_iso8601(last_good.observed_at)).total_seconds()
            return FreshnessResult(
                status=STALE,
                observation=last_good,
                age_seconds=retained_age,
                is_actionable=False,
            )

        return FreshnessResult(
            status=MISSING,
            observation=None,
            age_seconds=None,
            is_actionable=False,
        )


#: Default freshness window (seconds) applied when the operator has
#: not configured ``DATA_FRESHNESS_WINDOW_SECONDS``. 15 minutes is a
#: conservative default for end-of-day-oriented IDX paper trading --
#: comfortably longer than one scheduler tick interval, short enough
#: that a genuinely stalled provider is still caught the same session.
DEFAULT_FRESHNESS_WINDOW_SECONDS: float = 900.0


def load_data_freshness_policy(env_get=None) -> DataFreshnessPolicy:
    """Build a ``DataFreshnessPolicy`` from
    ``DATA_FRESHNESS_WINDOW_SECONDS`` (defaults to
    ``DEFAULT_FRESHNESS_WINDOW_SECONDS`` when unset).

    Args:
        env_get: Optional ``Callable[[str, float], float]`` (defaults
            to ``Core.config.config.get_float``) -- same test-injection
            convention as ``Business.idx_market_calendar.
            load_idx_market_calendar``.
    """
    if env_get is None:
        from Core.config import config as _config

        env_get = _config.get_float
    window = env_get("DATA_FRESHNESS_WINDOW_SECONDS", DEFAULT_FRESHNESS_WINDOW_SECONDS)
    if window is None or window <= 0:
        window = DEFAULT_FRESHNESS_WINDOW_SECONDS
    return DataFreshnessPolicy(freshness_window_seconds=float(window))