"""IDXMarketCalendar -- Phase D (Proactive IDX Scheduler Routine).

Timezone + trading-session classification for the Indonesia Stock
Exchange (Bursa Efek Indonesia / IDX), used exclusively by the Phase D
scheduler (``Orchestration.idx_daily_scheduler.IDXDailyScheduler``) to
decide *when* a scheduled job is allowed to run and whether a given
moment counts as "market open" for fetch/alert gating purposes.

Explicitly OUT of scope, mirroring the existing
``Business.us_market_policy.USMarketCalendar`` boundary:

* This module does NOT gate paper-trading order submission. IDX order
  submission in ``Business.paper_trading_engine.PaperTradingEngine``
  is completely unaffected -- Phase D never touches that engine or
  its pre-trade gates.
* This module does NOT connect to a broker or exchange calendar feed.
  It is a *computed, best-effort* session clock, exactly like
  ``USMarketCalendar`` already is for the US market.

Mirrors ``USMarketCalendar``'s stateless-value-object shape: every
method is a pure function of its arguments plus this module's
constants (and, for holidays, an explicitly caller-supplied set --
see ``KNOWN_LIMITATIONS`` below for why no holiday dates are computed
here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import FrozenSet, Optional

#: IANA timezone name for the IDX trading session. A plain string,
#: constructed lazily via ``IDXMarketCalendar.timezone()`` -- same
#: "don't fail import in a tzdata-less environment" reasoning as
#: ``Business.us_market_policy.US_MARKET_TIMEZONE_NAME``.
IDX_MARKET_TIMEZONE_NAME: str = "Asia/Jakarta"

#: Best-effort, single (non-Friday-variant) IDX session boundaries,
#: WIB (Asia/Jakarta, UTC+7, no DST). Public, well-known IDX trading
#: hours: a pre-opening call-auction window, two regular sessions
#: split by a midday break, and a short closing-auction window after
#: Session II. These are the ordinary Monday-Thursday hours; IDX has
#: historically run a shorter Friday Session I/II and has adjusted
#: hours during Ramadan -- neither variant is modeled here (see
#: ``KNOWN_LIMITATIONS``).
PRE_MARKET_OPEN: time = time(8, 45)
SESSION_1_OPEN: time = time(9, 0)
SESSION_1_CLOSE: time = time(12, 0)
SESSION_2_OPEN: time = time(13, 30)
SESSION_2_CLOSE: time = time(15, 49)
POST_CLOSE_END: time = time(16, 0)

SESSION_CLOSED: str = "closed"
SESSION_PRE_MARKET: str = "pre_market"
SESSION_REGULAR: str = "regular"
SESSION_LUNCH_BREAK: str = "lunch_break"
SESSION_AFTER_HOURS: str = "after_hours"

#: Explicit, never-silently-dropped limitations of this calendar --
#: same "report, don't work around" convention
#: ``Business.us_market_policy.KNOWN_LIMITATIONS`` already uses.
KNOWN_LIMITATIONS: tuple[str, ...] = (
    "This calendar has NO algorithmic Indonesian public-holiday "
    "calendar (unlike USMarketCalendar's computed US federal-holiday "
    "rules) -- Indonesian national holidays include lunar/Hijri dates "
    "(Idul Fitri, Idul Adha, Isra Mikraj, Maulid Nabi, etc.) and "
    "government-declared joint-leave (cuti bersama) days that this "
    "module has no formula for and will not guess. Without operator- "
    "supplied dates (via the 'holiday_dates' constructor argument or "
    "the IDX_MARKET_HOLIDAYS env var read by "
    "'load_idx_market_calendar()'), only Saturday/Sunday are treated "
    "as non-trading days.",
    "Only a single (Monday-Thursday-style) session schedule is "
    "modeled. IDX's historically shorter Friday Session I/II and any "
    "Ramadan-adjusted hours are NOT represented -- every trading day "
    "uses the same SESSION_1_OPEN/CLOSE and SESSION_2_OPEN/CLOSE "
    "boundaries regardless of weekday or calendar date.",
    "This is a computed approximation, not a feed from IDX/KSEI/a "
    "broker. One-off exchange-declared closures or early closes are "
    "not represented unless the operator adds that date to "
    "'holiday_dates'.",
)


def _parse_holiday_env(raw: str) -> FrozenSet[date]:
    """Parse a comma-separated ``YYYY-MM-DD`` list into a ``frozenset``.

    Malformed entries are skipped (never raise) -- an operator typo in
    an optional env var must never crash the scheduler; a skipped date
    simply falls back to "not a holiday" (still correctly rejected by
    the weekend check if it happens to also be a weekend).
    """
    dates: set[date] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            year_str, month_str, day_str = token.split("-")
            dates.add(date(int(year_str), int(month_str), int(day_str)))
        except (ValueError, TypeError):
            continue
    return frozenset(dates)


@dataclass(frozen=True)
class IDXMarketCalendar:
    """Timezone + session policy for the Indonesia Stock Exchange.

    Stateless value object -- every method is a pure function of its
    arguments, this instance's ``holiday_dates``, and this module's
    constants. Constructing an instance performs no I/O.

    Attributes:
        timezone_name: IANA timezone name. Defaults to
            ``IDX_MARKET_TIMEZONE_NAME`` ("Asia/Jakarta").
        holiday_dates: Caller-supplied set of non-trading dates (IDX
            holidays / cuti bersama), in addition to weekends. Empty
            by default -- see ``KNOWN_LIMITATIONS``. Never computed by
            this class.
    """

    timezone_name: str = IDX_MARKET_TIMEZONE_NAME
    holiday_dates: FrozenSet[date] = field(default_factory=frozenset)

    def timezone(self):
        """Return the ``zoneinfo.ZoneInfo`` for this calendar's timezone."""
        from zoneinfo import ZoneInfo

        return ZoneInfo(self.timezone_name)

    def is_trading_day(self, day: date) -> bool:
        """Return whether ``day`` is a trading day: a weekday, not a
        caller-declared holiday.

        Args:
            day: The calendar date to check (naive -- interpreted as a
                date in this calendar's timezone).

        Returns:
            ``True`` if ``day`` is Monday-Friday and not present in
            ``self.holiday_dates``.
        """
        if day.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return day not in self.holiday_dates

    def to_local(self, moment: datetime) -> datetime:
        """Convert ``moment`` to this calendar's timezone.

        A naive ``datetime`` is treated as already being local (mirrors
        ``datetime.astimezone``'s own behavior for naive input), same
        convention ``USMarketCalendar.session()`` uses.
        """
        return moment.astimezone(self.timezone()) if moment.tzinfo else moment

    def local_date(self, moment: datetime) -> date:
        """Return the IDX-local calendar date for ``moment``.

        This is the "trading date" every Phase D job's idempotency key
        is scoped to -- never the caller's own (possibly UTC) date.
        """
        return self.to_local(moment).date()

    def session(self, moment: datetime) -> str:
        """Classify ``moment`` into an IDX trading session.

        Args:
            moment: A timezone-aware ``datetime`` (a naive one is
                treated as already local -- see ``to_local``).

        Returns:
            One of ``SESSION_CLOSED``/``SESSION_PRE_MARKET``/
            ``SESSION_REGULAR``/``SESSION_LUNCH_BREAK``/
            ``SESSION_AFTER_HOURS``.
        """
        local = self.to_local(moment)
        if not self.is_trading_day(local.date()):
            return SESSION_CLOSED
        local_time = local.time()
        if PRE_MARKET_OPEN <= local_time < SESSION_1_OPEN:
            return SESSION_PRE_MARKET
        if SESSION_1_OPEN <= local_time < SESSION_1_CLOSE:
            return SESSION_REGULAR
        if SESSION_1_CLOSE <= local_time < SESSION_2_OPEN:
            return SESSION_LUNCH_BREAK
        if SESSION_2_OPEN <= local_time < SESSION_2_CLOSE:
            return SESSION_REGULAR
        if SESSION_2_CLOSE <= local_time < POST_CLOSE_END:
            return SESSION_AFTER_HOURS
        return SESSION_CLOSED

    def is_market_open(self, moment: datetime) -> bool:
        """Return whether ``moment`` falls within an active (fetchable)
        regular trading session.

        Convenience wrapper: ``self.session(moment) == SESSION_REGULAR``.
        Used by the Phase D scheduler as the single source of truth for
        "may this tick fetch fresh market data".
        """
        return self.session(moment) == SESSION_REGULAR


def load_idx_market_calendar(env_get=None) -> IDXMarketCalendar:
    """Build an ``IDXMarketCalendar`` reading holiday overrides from
    the ``IDX_MARKET_HOLIDAYS`` env var (comma-separated ``YYYY-MM-DD``
    dates), if present.

    Args:
        env_get: Optional ``Callable[[str, str], str]`` (defaults to
            ``Core.config.config.get_str`` when omitted) -- injected so
            tests never need to mutate real process env. Mirrors the
            existing "config indirection for testability" convention
            used elsewhere in this codebase (e.g.
            ``Business.us_market_policy.load_us_fee_policy``).

    Returns:
        A fresh ``IDXMarketCalendar`` (never cached/singleton -- a
        second call after an env change reflects it immediately).
    """
    if env_get is None:
        from Core.config import config as _config

        env_get = _config.get_str
    raw = env_get("IDX_MARKET_HOLIDAYS", "") or ""
    return IDXMarketCalendar(holiday_dates=_parse_holiday_env(raw))