"""AccountBalanceService -- Sprint 4 STEP 7, extended by Activation 3.5
STEP 1 and Activation 3.5 STEP 3.

Applies a already-recorded ``Trade`` (Sprint 4 STEP 6, produced by
``Business.execution_service.ExecutionService``) to its owning
``Account``'s cash balance.

Scope (STEP 7 baseline, LOCKED; formula extended by Activation 3.5
STEP 1 to include ``fee``/``tax``):

* reads the current ``Account`` via ``AccountRepository``;
* computes ``gross_value = trade.quantity * trade.fill_price``;
* ``BUY``  -> ``cash = cash - gross_value - trade.fee - trade.tax``;
* ``SELL`` -> ``cash = cash + gross_value - trade.fee - trade.tax``;
* persists the result via ``AccountRepository.update_balances``.

Activation 3.5 STEP 3 note: the ``BUY`` "how much cash does this trade
need" arithmetic (``gross_value + fee + tax``) is now factored out into
the module-level ``compute_buy_required_cash()`` function below, so
this is the *only* place that formula is written. ``apply_trade()``'s
own guard calls it exactly as before (behaviourally unchanged -- pure
extraction, same three floats, same sum). ``Business.
paper_trading_engine.PaperTradingEngine``'s pre-trade "available cash"
gate imports and calls the same function so its rejection contract
cannot silently drift from this service's -- see that module's gate 8
for the other caller. This is additive only: no new pipeline, no
change to this service's own responsibility (it still only applies an
already-created ``Trade``'s cash impact; it does not decide whether a
not-yet-created order should be allowed to proceed).

Activation 3.5 STEP 1 note: ``fee``/``tax`` are read straight off the
already-persisted ``Trade`` (computed upstream by
``Business.execution_service.ExecutionService``/
``Business.execution_policy_config.ExecutionPolicy`` -- Activation
3.3). This service still does not compute a fee or a tax itself; it
only applies whatever value the ``Trade`` row already carries. This is
purely a formula extension of the existing ``apply_trade()`` method --
no new method, no new collaborator, no new pipeline.

``available_cash``/``total_cash`` (LOCKED DECISION 1): these are not
new fields -- ``Database.models.Account`` and the ``accounts`` table
(Sprint 4 STEP 1, LOCKED) only have ``cash``/``equity``/
``buying_power``. Both blueprint terms map onto the single existing
``cash`` field. No schema change, no new migration, no new field.

``equity``/``buying_power`` (LOCKED DECISION 2): because
``AccountRepository.update_balances`` (LOCKED, Sprint 4 STEP 1) takes
all three of ``cash``/``equity``/``buying_power`` together -- there is
no partial-update method -- this service always reads the Account's
*current* ``equity``/``buying_power`` first and passes them straight
back through unchanged. It never recomputes either of them itself:

* ``equity`` is portfolio valuation, reserved for a future STEP;
* ``buying_power`` is margin/leverage, reserved for a future STEP.

Recomputing either here would mean STEP 7 silently absorbing a later
STEP's responsibility, which is exactly the boundary violation the
Pre-Implementation Review called out and locked against.

Strictly DILARANG (forbidden) in this STEP, per the same review:
unrealized P/L, realized P/L, equity computation, buying-power
computation, fee computation, tax computation, touching ``Position``,
touching ``Portfolio``. None of those are implemented here, and this
service holds no reference to any repository/service that could do
them (no ``PositionRepository``, no ``TradeRepository`` -- the
``Trade`` is supplied by the caller, already created by STEP 6, never
created or fetched by this service).

Insufficient cash on a ``BUY`` (``gross_value + fee + tax > cash``)
raises ``ValidationError`` and leaves the Account untouched -- no
partial write, no repository call. Per the Activation 3.5 roadmap's
unqualified "cash tidak boleh negatif", a ``SELL`` whose ``fee``/
``tax`` would still drive the resulting cash negative (e.g. a fee/tax
larger than the sale proceeds) is rejected the same way -- also no
partial write, no repository call. In ordinary operation ``fee``/
``tax`` are much smaller than ``gross_value`` on a SELL, so this branch
is a defensive guard, not an expected path.

Repository dependency (LOCKED): ``AccountRepository`` only.
"""

from __future__ import annotations

from Core.exceptions import ValidationError
from Database.models import Account, Trade
from Repository.persistence.account_repository import AccountRepository

#: Trade actions this service knows how to apply. Mirrors
#: ``Business.order_lifecycle_service._VALID_ACTIONS`` -- kept as a
#: separate local tuple rather than importing that private name, same
#: as every other Sprint 4 STEP keeps its own domain checks local.
_VALID_ACTIONS = ("BUY", "SELL")


def compute_buy_required_cash(gross_value: float, fee: float, tax: float) -> float:
    """Cash a ``BUY`` needs: ``gross_value + fee + tax``.

    Single source of truth for this sum (Activation 3.5 STEP 3). Two
    callers use it:

    * ``AccountBalanceService.apply_trade()`` below, against the
      ``fee``/``tax`` actually persisted on the ``Trade`` being
      applied;
    * ``Business.paper_trading_engine.PaperTradingEngine``'s
      pre-trade "available cash" gate, against the ``fee``/``tax``
      the *same* ``Trade`` will carry once
      ``Business.execution_service.ExecutionService`` creates it
      (read from the identical ``ExecutionPolicy`` instance the
      composition root already hands to both collaborators).

    Kept a plain function (not a method) since it owns no state and
    both callers are otherwise unrelated classes -- mirrors how this
    module already keeps ``_VALID_ACTIONS`` as a free-standing
    constant rather than hanging it off the class.

    Args:
        gross_value: ``quantity * fill_price`` (or, pre-trade,
            ``quantity * requested_price``).
        fee: The fee that will apply to this trade.
        tax: The tax that will apply to this trade (``0.0`` for BUY
            on IDX -- see ``ExecutionPolicy``).

    Returns:
        ``gross_value + fee + tax``, unrounded, exactly as this
        service has always computed it.
    """
    return gross_value + fee + tax


class AccountBalanceService:
    """Applies a single ``Trade``'s cash impact to its ``Account``.

    Depends on ``AccountRepository`` only -- no other repository, no
    Service, no Skill, no Tool. Never opens a transaction itself.
    """

    def __init__(self, account_repository: AccountRepository) -> None:
        """Initialize the service.

        Args:
            account_repository: Used to read the current Account and
                to persist its updated cash balance. Stored by
                reference only.
        """
        self._account_repository = account_repository

    def apply_trade(self, trade: Trade) -> Account:
        """Debit or credit ``trade.account_id``'s cash for ``trade``.

        Args:
            trade: An already-created, immutable ``Trade`` (Sprint 4
                STEP 6). ``trade.quantity * trade.fill_price`` is the
                trade value applied to cash; ``trade.action`` decides
                the direction. This method never creates, fetches, or
                mutates a ``Trade`` itself.

        Returns:
            The ``Account`` as it now stands after the update --
            ``cash`` changed, ``equity``/``buying_power`` unchanged
            from what was already stored.

        Raises:
            ValidationError: If ``trade.account_id`` does not exist,
                if ``trade.action`` is not ``"BUY"``/``"SELL"``, if a
                ``BUY``'s ``gross_value + fee + tax`` exceeds the
                account's current ``cash`` (insufficient funds), or if
                a ``SELL``'s ``fee``/``tax`` would drive the resulting
                cash negative. In every case, no repository write
                happens.
            RepositoryError: If any underlying repository call fails.
        """
        if trade.action not in _VALID_ACTIONS:
            raise ValidationError(
                f"Cannot apply trade {trade.trade_id}: unknown action '{trade.action}'",
                details={"trade_id": trade.trade_id, "action": trade.action},
            )

        account = self._account_repository.get_by_id(trade.account_id)
        if account is None:
            raise ValidationError(
                f"Account {trade.account_id} not found",
                details={"account_id": trade.account_id},
            )

        gross_value = trade.quantity * trade.fill_price

        if trade.action == "BUY":
            required_cash = compute_buy_required_cash(gross_value, trade.fee, trade.tax)
            if required_cash > account.cash:
                raise ValidationError(
                    f"Insufficient cash for account {trade.account_id}: "
                    f"required {required_cash} (gross_value {gross_value} + fee "
                    f"{trade.fee} + tax {trade.tax}) exceeds cash {account.cash}",
                    details={
                        "account_id": trade.account_id,
                        "cash": account.cash,
                        "gross_value": gross_value,
                        "fee": trade.fee,
                        "tax": trade.tax,
                        "required_cash": required_cash,
                    },
                )
            new_cash = account.cash - required_cash
        else:  # SELL
            new_cash = account.cash + gross_value - trade.fee - trade.tax
            if new_cash < 0:
                raise ValidationError(
                    f"Insufficient cash for account {trade.account_id}: "
                    f"applying SELL (gross_value {gross_value} - fee {trade.fee} - "
                    f"tax {trade.tax}) would drive cash negative from {account.cash}",
                    details={
                        "account_id": trade.account_id,
                        "cash": account.cash,
                        "gross_value": gross_value,
                        "fee": trade.fee,
                        "tax": trade.tax,
                        "resulting_cash": new_cash,
                    },
                )

        self._account_repository.update_balances(
            account_id=account.account_id,
            cash=new_cash,
            equity=account.equity,
            buying_power=account.buying_power,
        )

        # Re-fetch rather than hand-construct the return value, mirroring
        # Business.order_lifecycle_service.OrderLifecycleService.transition_status
        # -- ``updated_at`` is repository-owned (bumped inside
        # ``update_balances``), so this method must not fabricate it.
        return self._account_repository.get_by_id(account.account_id)