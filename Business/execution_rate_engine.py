"""ExecutionRateEngine -- Activation 7 (PAPER VALIDATION), ``execution
rate`` dimension of the Strategy validation minimum dimensions.

The roadmap ("Master Prompt (Roadmap).md", ACTIVATION 7 - PAPER
VALIDATION, "Minimum validation dimensions" -> "Strategy validation")
lists ``execution rate`` with no formula attached. The ACTIVATION 7 --
EXECUTION RATE ONLY audit (see conversation) examined every source
that already represents a valid signal/attempt, a submitted order, and
an executed/filled order, and found:

* a **signal-to-order** execution rate (submitted orders / actionable
  signals) is NOT reliably computable with currently persisted data:
  ``PaperTradingEngine.submit_order()`` runs 12 pre-trade gates
  *before* ``OrderLifecycleService.create_order()`` is ever called
  (see that module's docstring) -- a pre-trade-gate rejection raises
  ``ValidationError`` with no ``Order`` row and no other persisted
  trace at all, so the true attempt count is structurally
  under-countable from persisted state. Separately,
  ``Order.analysis_snapshot_id`` (the only signal<->order link,
  Activation 5.1) is populated only by the CLI ``paper buy``/``paper
  sell`` path and is optional everywhere else, so grouping orders back
  to signals would also under-count. Closing this gap would require
  changing what ``PaperTradingEngine``/the trading flow persists,
  which is explicitly out of this module's scope.
* an **order-level** execution rate IS fully supported by data that is
  already persisted today, using only ``Order.status`` (see
  ``Database.order_constants.ORDER_STATUSES`` / ``Database.models.
  Order``'s already-LOCKED ``FILLED`` contract, the same one
  ``Business.reconciliation_engine.ReconciliationEngine`` and
  ``Business.failure_rate_engine.FailureRateEngine`` already read).
  This module implements ONLY that definition.

    execution_rate = filled_orders / resolved_orders

where ``resolved_orders`` is every order whose outcome is no longer in
flight -- ``FILLED``, ``PARTIALLY_FILLED``, ``REJECTED``,
``CANCELLED``, ``EXPIRED`` -- mirroring
``Business.failure_rate_engine.FailureRateEngine``'s own
``_ORDER_STATUSES_RESOLVED`` denominator exactly (an order still
``NEW``/``VALIDATED``/``PENDING`` has no outcome yet and is excluded
from both numerator and denominator, same reasoning as that engine).
``filled_orders`` counts ``status == "FILLED"`` only --
``PARTIALLY_FILLED`` is counted separately
(``partially_filled_orders``) and is deliberately NOT folded into the
numerator: it is a resolved-but-incomplete outcome, not a full
execution, and this codebase does not yet implement partial fills
(``Database.models.Order`` docstring) so this field is expected to be
``0`` on all data produced by the current pipeline -- reported rather
than assumed away.

This is deliberately the mirror image of ``FailureRateEngine``'s order
side, not its arithmetic complement: ``execution_rate`` +
``FailureRateEngine.order_failure_rate`` does NOT sum to ``1.0``
whenever ``CANCELLED``/``EXPIRED``/``PARTIALLY_FILLED`` orders exist,
since those count toward the shared ``resolved`` denominator without
being counted as either a failure or an execution by either engine.

Read-only (mirrors ``ReconciliationEngine``/``FailureRateEngine``):
depends on ``OrderRepository`` only, and only via its already-existing
``list_all()`` method. No ``create``/``update``/``update_status`` call
anywhere in this module, no new repository method, no migration.

Public API: exactly one public method, ``calculate()``, taking no
argument and returning an ``ExecutionRateResult``. No threshold, no
pass/fail verdict, no acceptance-gate decision, no scheduler, no new
provider -- this engine reports the measured rate only.
"""

from __future__ import annotations

from dataclasses import dataclass

from Repository.persistence.order_repository import OrderRepository

#: The one ``Order.status`` value that means a full execution.
_ORDER_STATUS_FILLED = "FILLED"

#: A resolved-but-incomplete outcome -- reported separately, never
#: folded into ``filled_orders``. See module docstring.
_ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"

#: Order statuses that represent an outcome already resolved one way
#: or another (i.e. not still in flight). Mirrors
#: ``Business.failure_rate_engine._ORDER_STATUSES_RESOLVED`` exactly
#: -- the two engines share the same denominator definition.
_ORDER_STATUSES_RESOLVED = frozenset(
    {"FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED", "EXPIRED"}
)


@dataclass
class ExecutionRateResult:
    """One ``ExecutionRateEngine.calculate()`` outcome.

    ``resolved_total`` is the size of the denominator (every order
    whose outcome is no longer in flight -- see module docstring for
    exactly which statuses that includes). ``filled_orders`` /
    ``partially_filled_orders`` / ``non_executed_orders`` partition
    ``resolved_total`` exactly (they sum to it).
    ``execution_rate`` is ``filled_orders / resolved_total``, or
    ``0.0`` when ``resolved_total`` is ``0`` (no resolved orders yet
    -- never a ``ZeroDivisionError``, and never treated as a 100% or
    0% rate by assumption).
    """

    resolved_total: int
    filled_orders: int
    partially_filled_orders: int
    non_executed_orders: int
    execution_rate: float


class ExecutionRateEngine:
    """Computes order-level ``execution_rate`` from real recorded
    order outcomes.

    Pure read-only business object -- no threshold, no scheduler, no
    new data provider. See module docstring for the exact formula and
    data source, and for why a signal-to-order definition is a
    documented GAP this engine does not attempt to close.
    """

    def __init__(self, order_repository: OrderRepository) -> None:
        """Initialize the engine.

        Args:
            order_repository: Read-only source for recorded order
                outcomes (``Order`` rows).
        """
        self._order_repository = order_repository

    def calculate(self) -> ExecutionRateResult:
        """Compute the order-level execution rate from every recorded
        order outcome currently persisted.

        Returns:
            An :class:`ExecutionRateResult`. Reads the full history via
            ``OrderRepository.list_all()`` -- never filtered to a
            window, never estimated, never mutated.
        """
        orders = self._order_repository.list_all()

        resolved_orders = [
            order for order in orders if order.status in _ORDER_STATUSES_RESOLVED
        ]
        resolved_total = len(resolved_orders)
        filled_orders = sum(
            1 for order in resolved_orders if order.status == _ORDER_STATUS_FILLED
        )
        partially_filled_orders = sum(
            1
            for order in resolved_orders
            if order.status == _ORDER_STATUS_PARTIALLY_FILLED
        )
        non_executed_orders = resolved_total - filled_orders - partially_filled_orders

        execution_rate = (
            0.0 if resolved_total == 0 else filled_orders / resolved_total
        )

        return ExecutionRateResult(
            resolved_total=resolved_total,
            filled_orders=filled_orders,
            partially_filled_orders=partially_filled_orders,
            non_executed_orders=non_executed_orders,
            execution_rate=execution_rate,
        )