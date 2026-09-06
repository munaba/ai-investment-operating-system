"""FailureRateEngine -- Activation 7 (PAPER VALIDATION), ``failure rate``
dimension of the Live Readiness Gate.

The roadmap ("Master Prompt (Roadmap).md", ACTIVATION 7 - PAPER
VALIDATION, "Minimum validation dimensions") lists ``failure rate`` as
one of the gate metrics to combine with closed-trade count, market
condition variety, data quality, net performance, drawdown, and
reconciliation error -- explicitly instructing NOT to gate on a single
time-based condition alone. This module implements ONLY the
measurement itself: a read-only ``failure_rate`` computed from outcome
data this codebase already records and persists. It does not define,
apply, or wire any pass/fail threshold, does not touch the decision
table (``Business.reconciliation_engine``'s formulas, any trading
gate, or ``Core`` decision policy), and adds no scheduler and no new
data provider.

Two already-existing, already-recorded outcome sources are used,
exactly as they already are today -- nothing new is persisted and no
existing schema/formula changes:

* Scan outcomes -- ``Database.models.RankingSnapshot.status``.
  Activation 2.7 (migration version=11) already records, for every
  symbol in every scan, whether ``RankingEngine``/
  ``WatchlistAnalysisSkill`` produced a usable result
  (``status="success"``) or the symbol was excluded because its
  underlying data/analysis failed (``status="error"``, with
  ``error_message`` set) -- see that dataclass's docstring. This is
  the concrete, already-recorded form of the roadmap's "failed data
  tidak menghasilkan signal" system-validation line item.
* Order outcomes -- ``Database.models.Order.status``. Of the eight
  values in ``Database.order_constants.ORDER_STATUSES``, ``REJECTED``
  is the one that unambiguously means "this order failed" (the order
  was validated/attempted and did not fill because of a hard failure
  -- e.g. the kill switch, cash, or lot-size check in
  ``Business.paper_trading_engine.PaperTradingEngine``). ``CANCELLED``
  and ``EXPIRED`` are lifecycle outcomes with a different, non-failure
  meaning (a caller/clock ended the order, not a system failure) and
  are deliberately NOT counted here -- this module does not invent a
  new definition of "order failure" beyond the one status the schema
  already treats as a hard rejection. ``NEW``/``VALIDATED``/``PENDING``/
  ``PARTIALLY_FILLED`` are open, not-yet-resolved states and are
  likewise excluded from both the numerator and the denominator (this
  engine measures the failure rate of orders whose outcome is already
  known, not of orders still in flight).

Read-only (mirrors ``Business.reconciliation_engine.ReconciliationEngine``):
depends on ``SnapshotRepository``/``OrderRepository`` only, and only
via their already-existing ``list_all()`` methods. No ``create``/
``update``/``update_status`` call anywhere in this module.

Public API: exactly one public method, ``calculate()``, taking no
argument (reads the full recorded history through the two injected
repositories) and returning a ``FailureRateResult``. No threshold, no
pass/fail verdict, no acceptance-gate decision -- this engine reports
the measured rate only; deciding what rate is acceptable is explicitly
out of this STEP's scope (the roadmap's "Live Readiness Gate" is a
human/product decision made elsewhere, not a value baked into this
engine).
"""

from __future__ import annotations

from dataclasses import dataclass

from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.snapshot_repository import SnapshotRepository

#: The one ``RankingSnapshot.status`` value that means the scan failed
#: for that symbol (Activation 2.7). The only other value the schema
#: allows is ``"success"``.
_SCAN_STATUS_ERROR = "error"

#: The one ``Order.status`` value counted as an order failure. See
#: module docstring for why ``CANCELLED``/``EXPIRED`` are excluded.
_ORDER_STATUS_REJECTED = "REJECTED"

#: Order statuses that represent an outcome already resolved one way
#: or another (i.e. not still in flight). Only these are counted in
#: the order failure rate's denominator -- see module docstring.
_ORDER_STATUSES_RESOLVED = frozenset(
    {"FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED", "EXPIRED"}
)


@dataclass
class FailureRateResult:
    """One ``FailureRateEngine.calculate()`` outcome.

    Scan and order failure rates are reported separately (they measure
    different things -- data/analysis failures vs. order-execution
    failures) as well as combined, since the roadmap's "failure rate"
    line item does not distinguish between them. Every ``*_total`` is
    the size of that measurement's denominator (see module docstring
    for exactly which rows are counted); every ``*_rate`` is
    ``failures / total``, or ``0.0`` when ``total`` is ``0`` (no
    recorded outcomes yet -- never a ``ZeroDivisionError``, and never
    treated as a 100% or 0% failure rate by assumption).
    """

    scan_total: int
    scan_failures: int
    scan_failure_rate: float
    order_total: int
    order_failures: int
    order_failure_rate: float
    combined_total: int
    combined_failures: int
    combined_failure_rate: float


class FailureRateEngine:
    """Computes ``failure_rate`` from real recorded scan/order outcomes.

    Pure read-only business object -- no repository write call, no
    threshold, no scheduler, no new data provider. See module
    docstring for the exact formulas and data sources.
    """

    def __init__(
        self,
        snapshot_repository: SnapshotRepository,
        order_repository: OrderRepository,
    ) -> None:
        """Initialize the engine.

        Args:
            snapshot_repository: Read-only source for recorded scan
                outcomes (``RankingSnapshot`` rows).
            order_repository: Read-only source for recorded order
                outcomes (``Order`` rows).
        """
        self._snapshot_repository = snapshot_repository
        self._order_repository = order_repository

    def calculate(self) -> FailureRateResult:
        """Compute scan/order/combined failure rates from every
        recorded outcome currently persisted.

        Returns:
            A :class:`FailureRateResult`. Reads the full history via
            ``SnapshotRepository.list_all()`` / ``OrderRepository.
            list_all()`` -- never filtered to a window, never
            estimated, never mutated.
        """
        snapshots = self._snapshot_repository.list_all()
        orders = self._order_repository.list_all()

        scan_total = len(snapshots)
        scan_failures = sum(
            1 for snapshot in snapshots if snapshot.status == _SCAN_STATUS_ERROR
        )
        scan_failure_rate = self._rate(scan_failures, scan_total)

        resolved_orders = [
            order for order in orders if order.status in _ORDER_STATUSES_RESOLVED
        ]
        order_total = len(resolved_orders)
        order_failures = sum(
            1 for order in resolved_orders if order.status == _ORDER_STATUS_REJECTED
        )
        order_failure_rate = self._rate(order_failures, order_total)

        combined_total = scan_total + order_total
        combined_failures = scan_failures + order_failures
        combined_failure_rate = self._rate(combined_failures, combined_total)

        return FailureRateResult(
            scan_total=scan_total,
            scan_failures=scan_failures,
            scan_failure_rate=scan_failure_rate,
            order_total=order_total,
            order_failures=order_failures,
            order_failure_rate=order_failure_rate,
            combined_total=combined_total,
            combined_failures=combined_failures,
            combined_failure_rate=combined_failure_rate,
        )

    @staticmethod
    def _rate(failures: int, total: int) -> float:
        if total == 0:
            return 0.0
        return failures / total