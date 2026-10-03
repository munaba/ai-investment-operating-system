from __future__ import annotations

# Single source of truth for Orders domain values.
#
# Both Repository.persistence.order_repository.OrderRepository
# (Python-level validation) and Database.migrations_orders (SQL CHECK
# constraint, generated from this same tuple at import time) read from
# here. Nothing else defines this value separately. Mirrors the same
# single-source-of-truth pattern used by Database.account_constants
# (ACCOUNT_MODES/ACCOUNT_ASSET_CLASSES) and Database.position_constants
# (POSITION_STATUSES).
#
# Trade-off: once ORDERS_MIGRATIONS (version=4) has been applied to a
# real database, its CHECK constraint is baked into that table's
# schema as-is. Changing this tuple later does NOT retroactively
# change an already-applied table -- it requires a new migration
# (ALTER TABLE / recreate), same as any other schema change. Do not
# edit version=4 after it has been applied anywhere.
#
# This is the full state machine from the Sprint 4 blueprint, LOCKED
# as of Pre-Implementation Review -- not just the subset this STEP's
# persistence layer happens to exercise today. PARTIALLY_FILLED is
# included even though no business logic produces it yet (Sprint 4
# does not implement partial fills): the status domain and the
# eventual order lifecycle are one and the same decision, and splitting
# them would require a second CHECK-constraint migration later purely
# to add a value that was already known and approved. See
# Database.models.Order for the matching filled_quantity rationale.
ORDER_STATUSES: tuple[str, ...] = (
    "NEW",
    "VALIDATED",
    "PENDING",
    "PARTIALLY_FILLED",
    "FILLED",
    "REJECTED",
    "CANCELLED",
    "EXPIRED",
)