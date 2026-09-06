"""ExecutionPolicy -- Activation 3.3 STEP 2 (Implementasi Atomik).

Single source of truth for the execution-related parameters listed in
this Activation's scope:

    * IDX lot size
    * buy fee (rate)
    * sell fee (rate)
    * sell tax (rate)
    * optional slippage (enabled flag + rate)
    * buying power policy

Before this Activation these values were either a dedicated constant
(``Database.account_constants.IDX_LOT_SIZE_SHARES``, read by
``Business.paper_trading_engine.PaperTradingEngine``) or a bare
literal written directly at a call site (``fee=0.0``/``tax=0.0`` in
``Business.execution_service.ExecutionService.execute_order`` -- see
that module's docstring, "LOCKED DECISION, STEP 6 review", for why the
literal was put there in the first place). Activation 3.3 STEP 2
collects all of them into one canonical ``ExecutionPolicy`` value
object so a future Activation that implements the real fee/tax/
slippage *formula* has exactly one place to change a parameter --
never a bare number scattered across the business layer.

Explicitly LOCKED for this STEP (per the brief -- "implementasi
atomik", not a fee/tax/slippage engine):

* this module does not compute anything -- no ``amount * rate``, no
  rounding, no cash/position mutation. It only defines *what* the
  parameters are and *where* they are read from;
* ``ExecutionService``/``PaperTradingEngine`` do not gain any new
  arithmetic in this STEP -- they gain a policy reference and stop
  writing/reading their number as a private literal;
* the "buying power policy" field is defined here (canonical, per the
  Activation's declared scope) but is NOT yet consulted by
  ``PaperTradingEngine``'s "available cash" pre-trade gate -- that
  gate's formula (``account.cash < quantity * requested_price``) is
  Activation 3.1/3.2 territory and this STEP does not touch it. The
  field exists so a *future* Activation that makes buying-power
  behaviour configurable (e.g. "does the cash check reserve fees
  up-front?") has a canonical place to add that switch, without this
  STEP inventing a formula it was told not to implement yet.

Backward compatibility (LOCKED, per the brief's Ketentuan 6): every
default below reproduces the exact runtime behaviour that existed
immediately before this Activation --

    * ``lot_size`` defaults to ``Database.account_constants.
      IDX_LOT_SIZE_SHARES`` (still ``100``, still defined in exactly
      one place -- this module does not redeclare the literal ``100``,
      it imports the existing constant so the number itself continues
      to live in exactly one place, now with exactly one *consumer
      path* on top of it);
    * ``buy_fee_rate``/``sell_fee_rate``/``sell_tax_rate`` default to
      ``0.0``, reproducing ``ExecutionService``'s old hardcoded
      ``fee=0.0``/``tax=0.0`` for every trade regardless of side;
    * ``slippage_enabled`` defaults to ``False`` and ``slippage_rate``
      defaults to ``0.0`` -- Sprint 4's documented "no slippage" model
      (see ``ExecutionService`` module docstring) is unchanged;
    * ``buying_power_policy`` defaults to ``"cash_only"``, naming the
      cash-only comparison ``PaperTradingEngine`` gate 8 already
      performs today -- no new policy value is applied yet.

A deployment that sets none of the ``EXECUTION_*`` env vars below
therefore behaves byte-for-byte identically to before this Activation.

Values are read from environment variables via the existing
``Core.config.config`` singleton -- the same pattern
``Core.approval_config.build_approval_port``,
``Database.database_config.DatabaseConfig.from_env``, and
``Business.ranking_weights_config.load_ranking_weights`` already use
in this codebase. This module does not introduce a new configuration
mechanism, per Ketentuan 3 ("gunakan mekanisme config/domain yang
sudah dipakai project").
"""

from __future__ import annotations

from dataclasses import dataclass

from Core.config import config
from Database.account_constants import IDX_LOT_SIZE_SHARES

#: Activation 3.3 defaults. Kept here, once, as the documented
#: baseline -- every consumer that used to hardcode one of these
#: values now reads it from an ``ExecutionPolicy`` instance instead.
_DEFAULT_LOT_SIZE: int = IDX_LOT_SIZE_SHARES
_DEFAULT_BUY_FEE_RATE: float = 0.0
_DEFAULT_SELL_FEE_RATE: float = 0.0
_DEFAULT_SELL_TAX_RATE: float = 0.0
_DEFAULT_SLIPPAGE_ENABLED: bool = False
_DEFAULT_SLIPPAGE_RATE: float = 0.0

#: Named buying-power comparison strategies. Only one exists today --
#: "cash_only" -- naming the exact comparison
#: ``PaperTradingEngine``'s gate 8 already performs
#: (``account.cash < quantity * requested_price``). Not consulted by
#: any gate yet (see module docstring); recorded here so the *name*
#: of today's implicit behaviour is canonical from this STEP onward,
#: ready for a future Activation to add a second strategy and a real
#: switch.
BUYING_POWER_POLICY_CASH_ONLY: str = "cash_only"

_DEFAULT_BUYING_POWER_POLICY: str = BUYING_POWER_POLICY_CASH_ONLY


@dataclass(frozen=True)
class ExecutionPolicy:
    """Canonical execution-parameter value object.

    Immutable (``frozen=True``), mirroring ``Business.
    ranking_weights_config.RankingWeights``: an ``ExecutionPolicy``
    instance is a value snapshot handed to one ``ExecutionService``/
    ``PaperTradingEngine`` at construction time, not a live, mutable
    settings object other code can reach in and change out from under
    an in-flight call.

    Attributes:
        lot_size: IDX minimum tradable lot size, in shares. Consumed
            by ``PaperTradingEngine``'s "IDX lot size valid" pre-trade
            gate. Default reproduces
            ``Database.account_constants.IDX_LOT_SIZE_SHARES``.
        buy_fee_rate: Placeholder fee parameter for BUY trades.
            Default ``0.0`` reproduces ``ExecutionService``'s old
            hardcoded ``fee=0.0``. No formula is applied to this rate
            yet -- see module docstring.
        sell_fee_rate: Placeholder fee parameter for SELL trades.
            Same default/behaviour note as ``buy_fee_rate``.
        sell_tax_rate: Placeholder tax parameter for SELL trades.
            Default ``0.0`` reproduces ``ExecutionService``'s old
            hardcoded ``tax=0.0``. IDX does not tax BUY trades, hence
            no ``buy_tax_rate`` field -- mirrors the domain, not an
            oversight.
        slippage_enabled: Whether an execution-price slippage model is
            active. Default ``False`` reproduces Sprint 4's documented
            "no slippage" model. Not consulted by any computation yet.
        slippage_rate: Placeholder slippage parameter, only meaningful
            once ``slippage_enabled`` is ``True`` and a future
            Activation implements the slippage formula. Default
            ``0.0``.
        buying_power_policy: Name of the buying-power comparison
            strategy. Default ``"cash_only"`` names
            ``PaperTradingEngine`` gate 8's existing comparison; not
            yet consulted by that gate (see module docstring).
    """

    lot_size: int = _DEFAULT_LOT_SIZE
    buy_fee_rate: float = _DEFAULT_BUY_FEE_RATE
    sell_fee_rate: float = _DEFAULT_SELL_FEE_RATE
    sell_tax_rate: float = _DEFAULT_SELL_TAX_RATE
    slippage_enabled: bool = _DEFAULT_SLIPPAGE_ENABLED
    slippage_rate: float = _DEFAULT_SLIPPAGE_RATE
    buying_power_policy: str = _DEFAULT_BUYING_POWER_POLICY


def load_execution_policy() -> ExecutionPolicy:
    """Load ``ExecutionPolicy`` from environment configuration.

    This is the one canonical place ``ExecutionService`` and
    ``PaperTradingEngine`` (via their constructor defaults) and any
    operator/deployment reads/sets execution parameters from -- "satu
    source of truth" (Activation 3.3 Ketentuan 1).

    Env vars read (all optional; each falls back independently to
    Activation 3.3's documented default, which reproduces pre-3.3
    runtime behaviour exactly if left unset):

        EXECUTION_LOT_SIZE             (int,   default 100)
        EXECUTION_BUY_FEE_RATE         (float, default 0.0)
        EXECUTION_SELL_FEE_RATE        (float, default 0.0)
        EXECUTION_SELL_TAX_RATE        (float, default 0.0)
        EXECUTION_SLIPPAGE_ENABLED     (bool,  default False)
        EXECUTION_SLIPPAGE_RATE        (float, default 0.0)
        EXECUTION_BUYING_POWER_POLICY  (str,   default "cash_only")

    Returns:
        An ``ExecutionPolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config``'s typed getters if one of the env
            vars above is set to a value of the wrong type.
    """
    return ExecutionPolicy(
        lot_size=config.get_int("EXECUTION_LOT_SIZE", _DEFAULT_LOT_SIZE),
        buy_fee_rate=config.get_float("EXECUTION_BUY_FEE_RATE", _DEFAULT_BUY_FEE_RATE),
        sell_fee_rate=config.get_float("EXECUTION_SELL_FEE_RATE", _DEFAULT_SELL_FEE_RATE),
        sell_tax_rate=config.get_float("EXECUTION_SELL_TAX_RATE", _DEFAULT_SELL_TAX_RATE),
        slippage_enabled=config.get_bool("EXECUTION_SLIPPAGE_ENABLED", _DEFAULT_SLIPPAGE_ENABLED),
        slippage_rate=config.get_float("EXECUTION_SLIPPAGE_RATE", _DEFAULT_SLIPPAGE_RATE),
        buying_power_policy=config.get_str(
            "EXECUTION_BUYING_POWER_POLICY", _DEFAULT_BUYING_POWER_POLICY
        ),
    )
