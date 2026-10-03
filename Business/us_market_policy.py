"""USMarketPolicy -- Activation 9.1 (US paper market adapter, broker-free scope).

Collects exactly the US-market components the Activation 9.1 brief asks
for that can be proven *without* a broker connection -- symbol format,
USD paper account currency/asset-class, fractional-share policy, US fee
policy, and timezone/market-calendar policy. Everything else the
Activation 9 roadmap section lists (pre-market/after-hours order
routing, real commission/fee computation, currency conversion,
settlement, data provider, broker adapter, tax-reporting metadata) is
explicitly OUT of scope for 9.1 -- each of those needs a broker/data
API this Activation is not allowed to assume or invent (per the 9.1
brief: "No broker/API/network").

Wiring status (updated, Activation 9.3 STEP 1): ``USFeePolicy`` and
``USFractionalSharePolicy`` are now consulted by the live trade path
for ``market == "us"`` -- see ``resolve_fee_tax()`` at the bottom of
this module, called from both ``Business.paper_trading_engine.
PaperTradingEngine`` (pre-trade gate 6 quantity check / gate 8
required-cash fee lookup) and ``Business.execution_service.
ExecutionService.execute_order()`` (the actual persisted
``Trade.fee``/``Trade.tax``), so the two stay guaranteed consistent
(both resolve fee/tax through this one function). ``market == "idx"``
and ``market == "crypto"`` are completely unaffected: both still
resolve fee/tax from the shared ``Business.execution_policy_config.
ExecutionPolicy`` exactly as before this STEP -- ``resolve_fee_tax()``
only branches to ``USFeePolicy`` when ``market == "us"``, everything
else falls through to the original IDX/crypto-shared behavior
byte-for-byte. Neither ``PaperTradingEngine`` nor ``ExecutionService``
gained a new stored constructor collaborator for this -- both already
have every value ``resolve_fee_tax()`` needs (the market string, the
order/trade action, and their existing ``ExecutionPolicy`` instance),
so this module's policy objects are loaded fresh, per call, via
``load_us_fee_policy()``/``load_us_fractional_share_policy()`` --
never cached at import time or on either collaborator, which is also
why a test that monkeypatches ``US_*``/``EXECUTION_*`` env vars
between calls sees the change immediately, with no engine/service
rebuild required.

Wiring status (updated, Activation 9.4): ``USMarketCalendar`` and
``US_ORDER_ALLOWED_SESSIONS`` are now consulted by the live trade path
for ``market == "us"`` as well -- see the new pre-trade gate 17 in
``Business.paper_trading_engine.PaperTradingEngine._run_pre_trade_
validation``. That gate parses the caller-supplied ``executed_at``
(the same ISO-8601 string ``submit_order()`` already threads through
to ``ExecutionService`` -- this module still generates no timestamp
of its own, and neither does the engine), classifies it via
``USMarketCalendar().session()``, and rejects unless the result is in
``US_ORDER_ALLOWED_SESSIONS``. ``market == "idx"`` and
``market == "crypto"`` are completely unaffected -- the new gate is
skipped entirely for both, exactly like gate 6's existing
``market == "us"`` branch.

Components in this module:

1.  ``is_valid_us_symbol`` / ``US_SYMBOL_PATTERN`` -- symbol format.
    US common-stock/ETF tickers on NYSE/Nasdaq are 1-5 uppercase
    letters, optionally followed by a single share-class suffix
    (``.B`` or ``-B`` style, e.g. ``BRK.B``/``BRK-B``,
    ``BF.B``/``BF-B``). This is public ticker-convention knowledge,
    not a broker endpoint -- no specific broker's symbology (e.g.
    OSI/OCC option symbols, a specific vendor's suffix dialect) is
    assumed.

2.  ``USFractionalSharePolicy`` -- fractional-share *policy* (a
    configurable value object), not a claim that any specific broker
    supports it. Defaults are conservative (fractional shares
    disabled, whole-share precision) precisely because Activation 8.1
    (broker adapter audit) found no broker connected in this codebase
    -- this module cannot confirm any broker's actual fractional-share
    support, minimum increment, or minimum notional, so it does not
    guess one. An operator (or a future 9.2 broker-adapter Activation
    that DOES have confirmed broker capabilities) overrides the
    defaults explicitly.

3.  ``USFeePolicy`` -- US fee *policy* (commission rate + regulatory
    fee rate placeholders), mirroring ``Business.
    execution_policy_config.ExecutionPolicy``'s own "define the
    parameter, do not compute anything with it yet" discipline
    exactly. Defaults to ``0.0``/``0.0`` (many US brokers advertise
    zero-commission equity trading, and this module does not assume
    which, if any, regulatory pass-through fee a specific broker
    charges) -- not a claim about any real broker's fee schedule.

4.  ``USMarketCalendar`` -- timezone + regular/pre-market/after-hours
    session boundaries + a best-effort NYSE/Nasdaq holiday calendar
    computed from well-documented, public holiday-observance rules
    (fixed-date federal holidays with the standard Saturday-shifts-
    back / Sunday-shifts-forward observance rule, floating Monday
    holidays, and Good Friday via the standard Gregorian Easter
    algorithm). This is a *computed approximation* of the exchange
    calendar, not a feed from an exchange or broker -- it does NOT
    know about one-off, non-recurring closures (e.g. a market closed
    for a national day of mourning) or any given year's early-close
    schedule (typically 1:00pm ET on the day before/after certain
    holidays). Both limitations are reported explicitly via
    ``USMarketCalendar.KNOWN_LIMITATIONS`` -- never silently assumed
    complete, same convention ``ReconciliationEngine`` already uses
    for its own ``not_verifiable`` list.

USD paper account: this module does NOT create the account itself
(that is a bootstrap/persistence concern) -- see
``Core.bootstrap.ensure_default_us_account`` for the account-creation
half of Activation 9.1, which reuses ``Database.account_constants.
ACCOUNT_ASSET_CLASSES``'s existing ``"stock_us"`` value (already
present in that tuple before this Activation -- confirmed by reading
the file, not added by this Activation) and the existing
``AccountRepository`` create-if-absent pattern
``ensure_default_crypto_account`` already established.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from Business.crypto_fee_policy import TAKER, load_crypto_fee_policy
from Business.execution_policy_config import ExecutionPolicy
from Core.config import config

# ---------------------------------------------------------------------------
# 1. Symbol format
# ---------------------------------------------------------------------------

#: 1-5 uppercase letters, optionally followed by a single-letter
#: share-class suffix: a literal ``.`` or ``-`` then exactly one
#: uppercase letter (covers both the "dot" and "dash" share-class
#: notations in common use, e.g. ``BRK.B``/``BRK-B``, ``BF.B``/
#: ``BF-B``). Deliberately a SINGLE letter, not 1-2: real US
#: share-class suffixes are one letter (A/B/...); a 2-letter suffix is
#: how IDX country-suffix symbols look instead (e.g. ``BBCA.JK``) --
#: allowing 2 letters here would silently accept an IDX-style symbol
#: as if it were a valid US one, exactly the "jangan mencampur ...
#: IDX dengan US" mistake the roadmap warns against, just applied to
#: symbol format instead of fee/lot. No options/futures/broker-vendor
#: symbology is matched either -- this Activation has no confirmed
#: source for those.
US_SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]{1,5}([.\-][A-Z])?$")


def is_valid_us_symbol(symbol: str) -> bool:
    """Return whether ``symbol`` matches the US common-stock/ETF ticker format.

    Case-insensitive on input (the pattern itself only matches
    uppercase, so lowercase/mixed-case input is upper-cased before
    matching) -- mirrors how ``Core.market_config.is_crypto_symbol``
    already treats symbol case in this codebase, so callers do not
    need to normalize case themselves before calling either function.

    Args:
        symbol: The candidate ticker symbol, in any case.

    Returns:
        ``True`` if ``symbol.upper()`` matches ``US_SYMBOL_PATTERN``,
        ``False`` otherwise (including for ``None`` or any non-``str``,
        treated defensively as "not valid" rather than raising --
        same defensive-typing convention ``is_crypto_symbol`` uses).
    """
    if not isinstance(symbol, str) or not symbol:
        return False
    return US_SYMBOL_PATTERN.match(symbol.upper()) is not None


# ---------------------------------------------------------------------------
# 2. Fractional-share policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class USFractionalSharePolicy:
    """Configurable fractional-share policy (value object, not a broker claim).

    Attributes:
        enabled: Whether fractional-share quantities are permitted at
            all. Defaults to ``False`` -- see module docstring for why
            this Activation does not default to "on" without a
            confirmed broker capability.
        min_quantity: The smallest tradable quantity, in shares. Only
            meaningful when ``enabled`` is ``True``. Defaults to
            ``1.0`` (whole-share minimum), matching ``enabled=False``.
        quantity_precision: Number of decimal places a quantity may be
            expressed to. Only meaningful when ``enabled`` is ``True``.
            Defaults to ``0`` (whole shares only), matching
            ``enabled=False``.
    """

    enabled: bool = False
    min_quantity: float = 1.0
    quantity_precision: int = 0

    def is_quantity_allowed(self, quantity: float) -> bool:
        """Return whether ``quantity`` is permitted under this policy.

        Pure arithmetic check only -- does not touch any account,
        order, or position. A quantity is allowed when it is
        positive, at least ``min_quantity``, and representable exactly
        at ``quantity_precision`` decimal places (checked via
        ``round(quantity, quantity_precision) == quantity`` so a
        caller passing e.g. ``0.1`` when ``quantity_precision == 0``
        is rejected rather than silently truncated).

        Args:
            quantity: The candidate order quantity, in shares.

        Returns:
            ``True`` if the quantity satisfies every check above,
            ``False`` otherwise.
        """
        if quantity <= 0:
            return False
        if quantity < self.min_quantity:
            return False
        if round(quantity, self.quantity_precision) != quantity:
            return False
        if not self.enabled and quantity != int(quantity):
            return False
        return True


def load_us_fractional_share_policy() -> USFractionalSharePolicy:
    """Load ``USFractionalSharePolicy`` from environment configuration.

    Env vars read (all optional; each falls back independently to the
    conservative default documented on ``USFractionalSharePolicy``):

        US_FRACTIONAL_SHARES_ENABLED      (bool,  default False)
        US_FRACTIONAL_MIN_QUANTITY        (float, default 1.0)
        US_FRACTIONAL_QUANTITY_PRECISION  (int,   default 0)

    Namespaced ``US_*`` (not ``EXECUTION_*``) deliberately: these are
    not read by ``Business.execution_policy_config.load_execution_policy``
    and must never collide with, or be confused for, that module's IDX
    ``EXECUTION_*`` variables.

    Returns:
        A ``USFractionalSharePolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config``'s typed getters if one of the env
            vars above is set to a value of the wrong type.
    """
    return USFractionalSharePolicy(
        enabled=config.get_bool("US_FRACTIONAL_SHARES_ENABLED", False),
        min_quantity=config.get_float("US_FRACTIONAL_MIN_QUANTITY", 1.0),
        quantity_precision=config.get_int("US_FRACTIONAL_QUANTITY_PRECISION", 0),
    )


# ---------------------------------------------------------------------------
# 3. US fee policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class USFeePolicy:
    """Configurable US fee policy (value object, computes nothing itself).

    Mirrors ``Business.execution_policy_config.ExecutionPolicy``'s own
    "define the parameter, do not apply a formula yet" discipline: no
    method on this class multiplies a rate by an order/trade value --
    that arithmetic is explicitly out of 9.1 scope (it belongs to
    whichever future STEP wires a US execution path).

    Attributes:
        commission_rate: Placeholder per-trade commission rate.
            Defaults to ``0.0`` (many US brokers advertise
            zero-commission equity trading; this default does not
            assert that as fact for any specific, connected broker --
            no broker is connected in this codebase).
        regulatory_fee_rate: Placeholder SELL-side regulatory
            pass-through fee rate (US equities: SEC Section 31 fee /
            FINRA TAF are the two well-known examples, both SELL-only,
            mirroring why ``ExecutionPolicy.sell_tax_rate`` has no
            BUY-side counterpart on IDX either). Defaults to ``0.0``.
    """

    commission_rate: float = 0.0
    regulatory_fee_rate: float = 0.0


def load_us_fee_policy() -> USFeePolicy:
    """Load ``USFeePolicy`` from environment configuration.

    Env vars read (all optional; each falls back independently to
    ``0.0``):

        US_COMMISSION_RATE       (float, default 0.0)
        US_REGULATORY_FEE_RATE   (float, default 0.0)

    Namespaced ``US_*`` for the same reason ``load_us_fractional_share_
    policy`` is -- never read by, and never overlapping with,
    ``Business.execution_policy_config.load_execution_policy``'s
    ``EXECUTION_*`` variables.

    Returns:
        A ``USFeePolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config.get_float`` if a var above is set to
            a non-numeric value.
    """
    return USFeePolicy(
        commission_rate=config.get_float("US_COMMISSION_RATE", 0.0),
        regulatory_fee_rate=config.get_float("US_REGULATORY_FEE_RATE", 0.0),
    )


# ---------------------------------------------------------------------------
# 4. Timezone / market-calendar policy
# ---------------------------------------------------------------------------

#: IANA timezone name for the US equity market session. A plain string
#: rather than an eagerly-constructed ``zoneinfo.ZoneInfo`` so importing
#: this module never fails in an environment without the ``tzdata``
#: package installed (stdlib ``zoneinfo`` falls back to the system
#: timezone database, which is not guaranteed present on every
#: platform) -- callers that need the tz object call
#: ``USMarketCalendar.timezone()`` explicitly, at the point of use,
#: same lazy-construction shape ``Database.database_config.
#: DatabaseConfig.from_env`` already uses for its own optional
#: dependencies.
US_MARKET_TIMEZONE_NAME: str = "America/New_York"

#: Regular session: 9:30 AM - 4:00 PM Eastern Time (NYSE/Nasdaq
#: published regular trading hours -- public, static exchange-rule
#: knowledge, not a broker-specific value).
REGULAR_SESSION_OPEN: time = time(9, 30)
REGULAR_SESSION_CLOSE: time = time(16, 0)

#: Pre-market / after-hours windows. These are the commonly published
#: NYSE/Nasdaq extended-hours boundaries -- NOT a claim that any
#: specific connected broker actually routes orders in these windows
#: (per the roadmap: "pre-market/after-hours policy" is listed
#: separately from this Activation's broker-free scope; this module
#: only records the session *time boundaries*, it does not implement
#: order-routing behavior for them).
PRE_MARKET_OPEN: time = time(4, 0)
AFTER_HOURS_CLOSE: time = time(20, 0)

SESSION_CLOSED: str = "closed"
SESSION_PRE_MARKET: str = "pre_market"
SESSION_REGULAR: str = "regular"
SESSION_AFTER_HOURS: str = "after_hours"

#: Explicit, never-silently-dropped limitations of the computed holiday
#: calendar below -- same "report, don't work around" convention
#: ``Business.reconciliation_engine.NOT_VERIFIABLE_CASH_HISTORY`` /
#: ``NOT_VERIFIABLE_PORTFOLIO_VALUATION`` already use in this codebase.
KNOWN_LIMITATIONS: tuple[str, ...] = (
    "us_market_holidays()/is_us_market_open() compute a BEST-EFFORT NYSE/"
    "Nasdaq holiday calendar from public, static holiday-observance rules "
    "(fixed-date federal holidays with standard weekend-shift observance, "
    "floating Monday holidays, and Good Friday via the Gregorian Easter "
    "algorithm). This is NOT sourced from an exchange/broker calendar feed "
    "-- no such feed is wired to this module (Activation 8.1 audit found "
    "no broker connected in this codebase).",
    "One-off, non-recurring exchange closures (e.g. a market closed for a "
    "national day of mourning) are NOT represented -- this module has no "
    "source for them and does not invent one.",
    "Scheduled early-close days (typically 1:00pm ET on/around certain "
    "holidays) are NOT represented -- every trading day this module "
    "reports as open uses the full REGULAR_SESSION_OPEN/CLOSE boundaries "
    "regardless of the calendar date.",
)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the date of the ``n``-th occurrence of ``weekday`` in ``month``.

    ``weekday`` follows ``date.weekday()`` convention (Monday=0 ... Sunday=6).
    ``n`` is 1-indexed (1 == first occurrence). Used for floating Monday
    holidays (MLK Day, Washington's Birthday, Memorial Day, Labor Day) and
    Thanksgiving (4th Thursday).
    """
    first_of_month = date(year, month, 1)
    offset = (weekday - first_of_month.weekday()) % 7
    first_occurrence = first_of_month + timedelta(days=offset)
    return first_occurrence + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the date of the LAST occurrence of ``weekday`` in ``month``.

    Used for Memorial Day (last Monday of May).
    """
    if month == 12:
        first_of_next_month = date(year + 1, 1, 1)
    else:
        first_of_next_month = date(year, month + 1, 1)
    last_day_of_month = first_of_next_month - timedelta(days=1)
    offset = (last_day_of_month.weekday() - weekday) % 7
    return last_day_of_month - timedelta(days=offset)


def _easter_sunday(year: int) -> date:
    """Return the Gregorian-calendar Easter Sunday date for ``year``.

    Standard "anonymous Gregorian algorithm" (a.k.a. Meeus/Jones/Butcher
    algorithm) -- public, deterministic, well-documented arithmetic, not a
    lookup table or external source.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(holiday: date) -> date:
    """Apply the standard US federal weekend-observance shift.

    Saturday -> observed the preceding Friday; Sunday -> observed the
    following Monday; any other weekday is observed on the actual date.
    """
    if holiday.weekday() == 5:  # Saturday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday
        return holiday + timedelta(days=1)
    return holiday


def us_market_holidays(year: int) -> frozenset[date]:
    """Return the best-effort computed set of NYSE/Nasdaq holiday dates for ``year``.

    See ``KNOWN_LIMITATIONS`` for exactly what this does and does not
    cover -- this is a computed approximation from public
    holiday-observance rules, not an exchange-sourced calendar.

    Args:
        year: The calendar year to compute holidays for.

    Returns:
        A ``frozenset`` of ``date`` objects, one per observed holiday.
    """
    holidays = {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday_of_month(year, 1, 0, 3),  # MLK Day: 3rd Monday of January
        _nth_weekday_of_month(year, 2, 0, 3),  # Washington's Birthday: 3rd Monday of February
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday_of_month(year, 5, 0),  # Memorial Day: last Monday of May
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),  # Labor Day: 1st Monday of September
        _nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving: 4th Thursday of November
        _observed(date(year, 12, 25)),  # Christmas Day
    }
    if year >= 2022:  # Juneteenth first observed as an NYSE holiday in 2022
        holidays.add(_observed(date(year, 6, 19)))
    return frozenset(holidays)


@dataclass(frozen=True)
class USMarketCalendar:
    """Timezone + regular/pre-market/after-hours session policy for US equities.

    Stateless value object -- every method is a pure function of its
    arguments plus the module-level constants above. Constructing an
    instance performs no I/O, no network call, and no broker lookup.
    """

    timezone_name: str = US_MARKET_TIMEZONE_NAME

    def timezone(self):
        """Return the ``zoneinfo.ZoneInfo`` for this calendar's timezone.

        Constructed lazily (not at import time) -- see the module-level
        ``US_MARKET_TIMEZONE_NAME`` docstring for why.

        Returns:
            A ``zoneinfo.ZoneInfo`` instance for ``self.timezone_name``.
        """
        from zoneinfo import ZoneInfo

        return ZoneInfo(self.timezone_name)

    def is_trading_day(self, day: date) -> bool:
        """Return whether ``day`` is a trading day: a weekday, not a holiday.

        Args:
            day: The calendar date to check (naive -- interpreted as a
                date in this calendar's timezone, not converted from
                any other timezone by this method).

        Returns:
            ``True`` if ``day`` is Monday-Friday and not in
            ``us_market_holidays(day.year)``, ``False`` otherwise.
        """
        if day.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return day not in us_market_holidays(day.year)

    def session(self, moment: datetime) -> str:
        """Classify ``moment`` into a US-equity market session.

        Args:
            moment: A timezone-aware ``datetime``. Converted to this
                calendar's timezone before comparison -- a naive
                ``datetime`` is treated as already being in this
                calendar's timezone (mirrors ``datetime.astimezone``'s
                own behavior for naive input).

        Returns:
            One of ``SESSION_CLOSED``/``SESSION_PRE_MARKET``/
            ``SESSION_REGULAR``/``SESSION_AFTER_HOURS``.
        """
        local = moment.astimezone(self.timezone()) if moment.tzinfo else moment
        if not self.is_trading_day(local.date()):
            return SESSION_CLOSED
        local_time = local.time()
        if PRE_MARKET_OPEN <= local_time < REGULAR_SESSION_OPEN:
            return SESSION_PRE_MARKET
        if REGULAR_SESSION_OPEN <= local_time < REGULAR_SESSION_CLOSE:
            return SESSION_REGULAR
        if REGULAR_SESSION_CLOSE <= local_time < AFTER_HOURS_CLOSE:
            return SESSION_AFTER_HOURS
        return SESSION_CLOSED

    def is_regular_session_open(self, moment: datetime) -> bool:
        """Return whether ``moment`` falls within the regular trading session.

        Convenience wrapper: ``self.session(moment) == SESSION_REGULAR``.

        Args:
            moment: A timezone-aware ``datetime`` (see ``session``).

        Returns:
            ``True`` iff the regular session (9:30-16:00 ET, trading
            days only) is open at ``moment``.
        """
        return self.session(moment) == SESSION_REGULAR


# ---------------------------------------------------------------------------
# 4b. Pre-market/after-hours order-submission policy (Activation 9.4)
# ---------------------------------------------------------------------------

#: The set of ``SESSION_*`` values a US paper order is currently
#: permitted to be submitted in. Activation 9.1/9.3 deliberately left
#: this undecided (see the ``PRE_MARKET_OPEN``/``AFTER_HOURS_CLOSE``
#: comment above: "does NOT implement order-routing behavior for
#: them"). Activation 9.4 closes that gap with the smallest, safest
#: default the roadmap allows: only the REGULAR session is permitted.
#: ``SESSION_PRE_MARKET``/``SESSION_AFTER_HOURS``/``SESSION_CLOSED``
#: are all rejected -- not because any specific broker forbids
#: extended-hours orders, but because this codebase has no confirmed
#: broker contract (Activation 8.1 audit) that says otherwise, and the
#: roadmap brief is explicit that an *unconfirmed* session must fail
#: safe, never be silently treated as regular. A single frozenset,
#: not a boolean per session, so a future Activation that DOES confirm
#: a broker's extended-hours contract only has to add the relevant
#: ``SESSION_*`` value here -- the consuming gate in
#: ``Business.paper_trading_engine`` never needs to change.
US_ORDER_ALLOWED_SESSIONS: frozenset[str] = frozenset({SESSION_REGULAR})


# ---------------------------------------------------------------------------
# 5. Per-market fee/tax selection (Activation 9.3 STEP 1)
# ---------------------------------------------------------------------------

#: Action string this function treats as "BUY". Deliberately a literal,
#: re-declared rather than imported -- mirrors
#: ``Business.paper_trading_engine._BUY`` / ``Business.execution_
#: service._BUY``, both of which already re-declare this same literal
#: instead of importing a private constant across modules (see either
#: module's own docstring for why). This is the ONE place fee/tax
#: selection logic lives now (Activation 9.3 STEP 1 Requirement 1) --
#: both callers pass their own action string in, they do not each
#: re-implement the BUY/SELL branch.
_BUY = "BUY"


def resolve_fee_tax(
    market: str,
    action: str,
    execution_policy: ExecutionPolicy,
    symbol: str | None = None,
    execution_liquidity: str = TAKER,
) -> tuple[float, float]:
    """Resolve the effective ``(fee, tax)`` rate pair for one order/trade.

    Single source of truth for fee/tax selection, called by both
    ``Business.paper_trading_engine.PaperTradingEngine`` (pre-trade
    gate 8 required-cash calculation) and ``Business.execution_
    service.ExecutionService.execute_order()`` (the fee/tax actually
    persisted on the ``Trade``) -- so the two are structurally
    guaranteed to agree, never two independently-maintained copies of
    the same branch (Activation 9.3 STEP 1 Requirement 1/4, extended
    by Activation 10.4 Requirement 4 for crypto maker/taker).

    Args:
        market: The active market identifier, lower-case (e.g.
            ``"idx"``/``"us"``/``"crypto"``) -- both callers already
            compute this the same way (``os.getenv("AIOS_MARKET",
            "idx").strip().lower() or "idx"``), re-stated here rather
            than re-derived, so this function has no opinion on
            *where* the market string comes from, only on what to do
            with it once given.
        action: ``"BUY"`` or ``"SELL"`` (the order/trade's own action
            string, compared against the literal ``"BUY"`` -- any
            other value is treated as SELL-side, mirroring both
            callers' pre-existing ``action == _BUY`` convention).
        execution_policy: The canonical IDX-specific
            ``Business.execution_policy_config.ExecutionPolicy``
            instance the caller already holds. Used verbatim,
            unchanged, whenever ``market == "idx"`` (or any market
            other than ``"us"``/``"crypto"``) -- this function never
            mutates or re-derives it. No longer consulted for
            ``market == "crypto"`` as of Activation 10.4 -- see below
            (Requirement 3 / IDX-US-crypto isolation).
        symbol: The traded symbol, only used (and only required) when
            ``market == "crypto"``, to select the per-symbol
            ``Business.crypto_fee_policy.CryptoFeePolicy`` via
            ``load_crypto_fee_policy(symbol)``. Ignored for every
            other market. Defaults to ``None``.
        execution_liquidity: ``"maker"`` or ``"taker"`` (see
            ``Business.crypto_fee_policy.MAKER``/``TAKER``), only used
            when ``market == "crypto"`` to select which of
            ``CryptoFeePolicy.maker_fee_rate``/``taker_fee_rate``
            applies (via ``CryptoFeePolicy.fee_rate_for``). Defaults
            to ``Business.crypto_fee_policy.TAKER`` -- the current
            paper order path (``paper buy``/``paper sell``, both
              market-style fills) has no maker-capable order type yet,
            so every current production call site is implicitly
            taker unless a caller explicitly opts into ``"maker"``
            (see ``Business.crypto_fee_policy`` module docstring's
            "Maker/taker representation" section). Ignored for every
            other market.

    Returns:
        ``(fee, tax)`` as a 2-tuple of ``float``.

        For ``market == "us"``: fee is ``USFeePolicy.commission_rate``
        (applies to both BUY and SELL, per that field's own
        docstring); tax is ``0.0`` on BUY and
        ``USFeePolicy.regulatory_fee_rate`` on SELL (SEC Section 31 /
        FINRA TAF are both SELL-only, mirroring why IDX's
        ``sell_tax_rate`` has no BUY-side counterpart either).
        ``USFeePolicy`` is loaded fresh via ``load_us_fee_policy()``
        on every call -- never cached -- so a test that changes
        ``US_COMMISSION_RATE``/``US_REGULATORY_FEE_RATE`` between
        calls sees the new value immediately (Requirement 6).

        For ``market == "crypto"`` (Activation 10.4): fee is
        ``CryptoFeePolicy.fee_rate_for(execution_liquidity)`` -- the
        maker or taker rate, selected as described above -- for both
        BUY and SELL alike (crypto maker/taker fees apply
        symmetrically on either side of the book, unlike IDX's/US's
        SELL-only tax leg); tax is always ``0.0`` (the crypto fee
        model for this Activation is maker/taker fee, not a stock-
        style sell tax -- see ``Business.crypto_fee_policy`` module
        docstring and the Activation 10.4 brief's Requirement 5).
        ``CryptoFeePolicy`` is loaded fresh via
        ``load_crypto_fee_policy(symbol)`` on every call -- never
        cached -- mirroring ``USFeePolicy``'s own contract above, so a
        test that changes ``CRYPTO_<SYMBOL>_MAKER_FEE_RATE``/
        ``CRYPTO_<SYMBOL>_TAKER_FEE_RATE`` between calls sees the new
        value immediately. This branch no longer falls through to
        ``execution_policy`` (the pre-10.4 crypto behavior, which
        silently reused IDX's ``buy_fee_rate``/``sell_fee_rate``/
        ``sell_tax_rate`` -- exactly the leak Activation 10.4
        Requirement 3 closes).

        For any other ``market`` (``"idx"`` or anything else): fee/tax
        come from ``execution_policy`` exactly as ``PaperTradingEngine``
        gate 8 and ``ExecutionService.execute_order()`` already
        computed them before Activation 9.3 STEP 1 --
        ``buy_fee_rate``/``sell_fee_rate`` by action, ``0.0``/
        ``sell_tax_rate`` for tax. Byte-for-byte unchanged for IDX;
        this is the fallback branch, not a new default.
    """
    if market == "us":
        us_fee_policy = load_us_fee_policy()
        fee = us_fee_policy.commission_rate
        tax = 0.0 if action == _BUY else us_fee_policy.regulatory_fee_rate
        return fee, tax

    if market == "crypto":
        crypto_fee_policy = load_crypto_fee_policy(symbol if symbol is not None else "")
        fee = crypto_fee_policy.fee_rate_for(execution_liquidity)
        tax = 0.0
        return fee, tax

    fee = execution_policy.buy_fee_rate if action == _BUY else execution_policy.sell_fee_rate
    tax = 0.0 if action == _BUY else execution_policy.sell_tax_rate
    return fee, tax