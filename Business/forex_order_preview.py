"""ForexOrderPreview -- Activation 11.7 (compose the four Forex risk
foundations, paper-only scope, read-only preview).

Pure *composer*, not a fifth policy: this module owns no pair
universe, no pip-size rule, no directional rule, no margin formula,
and no maximum-loss formula of its own. It calls the four already-
LOCKED, already-tested policy modules built in Activation 11.2/11.4/
11.5/11.6 and assembles their results into one immutable snapshot of
what a hypothetical Forex order *would* look like:

    * ``Business.forex_pip_policy``       (Activation 11.2) -- pip
      size, pip value, and the single pair-universe source of truth.
    * ``Business.forex_stop_loss_policy`` (Activation 11.5) -- side
      validation and stop-loss directional validity.
    * ``Business.forex_max_loss_policy``  (Activation 11.4) -- maximum
      loss.
    * ``Business.forex_margin_policy``    (Activation 11.6) --
      required margin at the LOCKED 1:1 paper leverage.

This module deliberately does NOT redefine ``SUPPORTED_PIP_VALUE_PAIRS``,
a pip-size formula, a margin formula, or a maximum-loss formula --
every numeric result below is the direct return value of one of the
four calls above, never recomputed here. The one piece of logic this
module *does* own is orchestration: choosing which of the four
policies to call, in a fail-fast order, and shaping their outputs into
a single read-only record.

Governed entirely by ``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md`` -- this module introduces no
new locked decision of its own. It is NOT wired into
``Business.paper_trading_engine.PaperTradingEngine``, ``main.py``, or
any account/schema, and it does not create a ``Trade``, a ``Position``,
or mutate any balance/margin -- ``preview_forex_order`` is a pure
function with no side effects, callable purely for its return value.
That wiring -- and the separate reconciliation step the Activation 11
Acceptance Gate still requires -- is later, out of scope work.

Side convention: the exact ``"BUY"``/``"SELL"`` two-value convention
already used throughout this repository for ``Order.action``/
``Trade.action`` (``Business.position_manager._VALID_ACTIONS``,
re-exported here as ``Business.forex_stop_loss_policy.VALID_SIDES`` --
not redefined). Validated and normalized by
``Business.forex_stop_loss_policy.validate_stop_loss``, not by this
module.

No spread, no commission, no rollover, no swap -- those are separate,
later roadmap concerns and are excluded from
``Business.forex_max_loss_policy.calculate_maximum_loss`` itself; this
composer does not add them back in.

No leverage parameter -- required margin is fixed at the LOCKED 1:1
paper leverage (Activation 11.1 Decision B), exactly as
``Business.forex_margin_policy.calculate_required_margin`` already
enforces; this module does not add a second leverage knob.

Precision handling -- ``Decimal`` end-to-end, no float round-trip:
every numeric field on ``ForexOrderPreview`` is either a ``Decimal``
returned directly by one of the four composed policy calls, or
``entry_price``/``stop_loss``/``quantity`` converted once via
``Decimal(str(x))`` (the same idiom every composed policy already
uses) purely to echo the caller's own inputs back on the result --
never a ``Decimal`` -> ``float`` -> ``Decimal`` round-trip, and never
an intermediate value rounded before being stored.

Immutability: ``ForexOrderPreview`` is a frozen ``dataclass`` --
assigning to any of its fields after construction raises
``dataclasses.FrozenInstanceError`` (a subclass of ``AttributeError``).
No module-level cache, no mutable global, nothing retained between
calls -- like every module it composes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from Business.forex_margin_policy import calculate_required_margin
from Business.forex_max_loss_policy import calculate_maximum_loss
from Business.forex_pip_policy import _normalize_pair, calculate_pip_value, get_pip_size
from Business.forex_stop_loss_policy import validate_stop_loss

__all__ = ["ForexOrderPreview", "preview_forex_order"]


@dataclass(frozen=True)
class ForexOrderPreview:
    """Immutable, read-only snapshot of a hypothetical Forex order's risk figures.

    Every numeric field is a ``Decimal``, USD-denominated where
    applicable (``pip_value``, ``required_margin``, ``maximum_loss`` --
    see ``Business.forex_pip_policy.PIP_VALUE_CURRENCY``). Nothing on
    this object is derived independently of the four composed policy
    calls in ``preview_forex_order`` -- see that function and the
    module docstring.

    Attributes:
        pair: The normalized, canonical ``"BASE/QUOTE"`` pair (e.g.
            ``"EUR/USD"``), as returned by
            ``Business.forex_pip_policy._normalize_pair``.
        side: The normalized side, ``"BUY"`` or ``"SELL"``.
        entry_price: The order's entry price, echoed back as a
            ``Decimal``.
        stop_loss: The order's stop-loss price, echoed back as a
            ``Decimal``.
        quantity: The order's quantity in base-currency units, echoed
            back as a ``Decimal``.
        pip_size: From ``Business.forex_pip_policy.get_pip_size``.
        pip_value: From ``Business.forex_pip_policy.calculate_pip_value``,
            in USD.
        required_margin: From
            ``Business.forex_margin_policy.calculate_required_margin``,
            in USD, at the LOCKED 1:1 paper leverage.
        maximum_loss: From
            ``Business.forex_max_loss_policy.calculate_maximum_loss``,
            in USD.
    """

    pair: str
    side: str
    entry_price: Decimal
    stop_loss: Decimal
    quantity: Decimal
    pip_size: Decimal
    pip_value: Decimal
    required_margin: Decimal
    maximum_loss: Decimal


def preview_forex_order(
    pair: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    quantity: float,
) -> ForexOrderPreview:
    """Compose the four Forex risk foundations into one read-only preview.

    Calls, in this order, each composed policy remaining solely
    responsible for its own invariant (no validation is manually
    re-implemented here):

        1. ``Business.forex_pip_policy._normalize_pair`` -- validates
           ``pair`` is well-formed and normalizes it to canonical
           ``"BASE/QUOTE"`` form. Does NOT yet confirm pair *support*
           (see step 4).
        2. ``Business.forex_stop_loss_policy.validate_stop_loss`` --
           validates ``side`` (``"BUY"``/``"SELL"``), that
           ``entry_price``/``stop_loss`` are strictly positive real
           numbers, and that ``stop_loss`` is directionally correct
           for ``side``.
        3. ``Business.forex_pip_policy.get_pip_size`` -- pip size for
           the normalized pair.
        4. ``Business.forex_pip_policy.calculate_pip_value`` --
           validates the normalized pair is in
           ``SUPPORTED_PIP_VALUE_PAIRS`` and that ``quantity`` is a
           strictly positive real number, and returns the USD pip
           value.
        5. ``Business.forex_margin_policy.calculate_required_margin``
           -- USD required margin at 1:1.
        6. ``Business.forex_max_loss_policy.calculate_maximum_loss`` --
           USD maximum loss.
        7. Assembles the immutable ``ForexOrderPreview`` result.

    This function performs no independent numeric computation of its
    own -- every ``Decimal`` on the returned object other than the
    echoed-back ``entry_price``/``stop_loss``/``quantity`` inputs is
    the direct return value of one of the calls above.

    Args:
        pair: The currency pair, e.g. ``"EUR/USD"`` or ``"eurusd"``.
            Must normalize to a pair in
            ``Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS``.
        side: ``"BUY"`` or ``"SELL"`` (case-insensitive, surrounding
            whitespace tolerated).
        entry_price: The order's entry price. Must be strictly
            positive.
        stop_loss: The order's stop-loss price. Must be strictly
            positive and directionally correct for ``side``.
        quantity: The order's quantity, in base-currency units. Must
            be strictly positive.

    Returns:
        An immutable ``ForexOrderPreview`` with every field populated
        from the four composed policies.

    Raises:
        ValidationError: if ``pair`` is malformed or normalizes to an
            unsupported pair, if ``side`` is not ``"BUY"``/``"SELL"``,
            if ``entry_price``/``stop_loss``/``quantity`` is not a
            strictly positive real number, or if ``stop_loss`` is not
            directionally correct for ``side`` -- each raised, and
            unmodified, by the composed policy function responsible
            for that invariant.
    """
    # 1. Pair well-formedness + normalization (pair *support* is
    #    confirmed separately, below, by calculate_pip_value -- this
    #    module does not duplicate SUPPORTED_PIP_VALUE_PAIRS).
    normalized_pair = _normalize_pair(pair)

    # 2. Side + price positivity + stop-loss directional validity, all
    #    owned by forex_stop_loss_policy.
    validate_stop_loss(side, entry_price, stop_loss)
    normalized_side = side.strip().upper()

    # 3/4. Pip size and pip value -- pip value's call is also where
    #      pair *support* and quantity positivity are validated.
    pip_size = get_pip_size(normalized_pair)
    pip_value = calculate_pip_value(normalized_pair, quantity)

    # 5. Required margin at the LOCKED 1:1 paper leverage.
    required_margin = calculate_required_margin(normalized_pair, entry_price, quantity)

    # 6. Maximum loss (unsigned stop-loss-distance risk).
    maximum_loss = calculate_maximum_loss(normalized_pair, entry_price, stop_loss, quantity)

    # 7. Assemble the immutable result. entry_price/stop_loss/quantity
    #    are echoed back as Decimal (Decimal(str(x)), never through
    #    float) purely for the caller's convenience -- every other
    #    field above already came straight from a composed policy.
    return ForexOrderPreview(
        pair=normalized_pair,
        side=normalized_side,
        entry_price=Decimal(str(entry_price)),
        stop_loss=Decimal(str(stop_loss)),
        quantity=Decimal(str(quantity)),
        pip_size=pip_size,
        pip_value=pip_value,
        required_margin=required_margin,
        maximum_loss=maximum_loss,
    )