"""Production migration for the ``valuation_observations`` table
(Phase G, Task 3 -- "Valuation Freshness + Paper Review Inputs").

Version=28 (LOCKED DECISION): the next free slot after
``Database.migrations_brief_approvals`` version=27, per the same "grep
every ``Database/migrations_*.py`` ``version=`` literal before
choosing it" convention every prior domain migration documents.

Purpose (Phase G Task 3): the only market-price pipeline in this
codebase (``Orchestration.market_price_tool.MarketPriceTool``, reused
unchanged by ``Business.unrealized_pnl_engine.UnrealizedPnLEngine``)
carries no real market timestamp and caches nothing -- every call
either succeeds with a live price or fails outright. There is
therefore nothing durable a caller can fall back on across a restart
to tell "the provider is down right now, but here is the last price
we genuinely observed, and here is exactly when we observed it" apart
from what this table adds: one row per ``(account_id, symbol)``
holding the most recent successfully-observed price, its real
``observed_at`` timestamp, and its ``source`` label. Nothing else.

This table does NOT replace, duplicate, or second-guess
``UnrealizedPnLEngine``'s live formula -- it is a narrow, additive
"last-good observation" cache the engine consults only when a live
fetch fails, per ``Business.data_freshness_policy.DataFreshnessPolicy``
(the same, already-existing, LOCKED freshness-decision module built
for exactly this "carry the last-good value forward, never fabricate"
purpose).

Columns:

* ``account_id`` / ``symbol`` -- composite primary key. One row per
  position's valuation input; a later observation for the same
  ``(account_id, symbol)`` overwrites the row in place (this is a
  "last known good" cache, not an append-only audit log -- unlike
  ``portfolio_snapshots``/``trades``, history of every past price is
  not the concern here, only "what is the most recent one we can
  trust").
* ``price`` -- the observed market price, exactly as returned by
  ``MarketPriceTool`` at observation time. Never fabricated,
  interpolated, or adjusted.
* ``observed_at`` -- ISO-8601 UTC timestamp of the moment this price
  was genuinely obtained (mirrors the ``created_at``/``updated_at``/
  ``UnrealizedPnLEngine.market_timestamp`` convention already used
  throughout this codebase). Preserved verbatim on every read; never
  rewritten to "now" by a caller that is merely re-reading a stale row.
* ``source`` -- free-text label identifying where the observation came
  from (e.g. ``"market_price_tool"``), carried through for audit
  purposes only, mirroring ``Business.data_freshness_policy.
  Observation.source``.

Mutable-in-place (deliberate departure from the append-only convention
used by ``trades``/``portfolio_snapshots``/``brief_approvals``): this
is a cache of the single latest observation per symbol, not a history.
``Repository.persistence.valuation_observation_repository.
ValuationObservationRepository.record`` does an explicit "does this
``(account_id, symbol)`` row already exist" check followed by
``INSERT`` or ``UPDATE`` -- mirroring this codebase's existing
mutable-row convention (see ``Repository.persistence.
risk_limits_repository.RiskLimitsRepository.save``), never a single
``ON CONFLICT`` clause.

Not wired to ``Core.composition_root``, ``main.py``, or
``Database.migration_registry.MIGRATION_MODULES`` -- same scope
decision already made for every domain added after Activation 7
Blocker #4 (see ``Database.migrations_brief_approvals`` for the
precedent list). A caller applies
``VALUATION_OBSERVATIONS_MIGRATIONS`` explicitly via
``MigrationRunner(database).apply(VALUATION_OBSERVATIONS_MIGRATIONS)``.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table):
#   ... 16 = order_approvals, 19 = decision_briefs, 25/26 =
#   telegram_control, 27 = brief_approvals -- 28 is the first free slot
#   after 1-27, confirmed by grepping every Database/migrations_*.py
#   `version=` literal before choosing it.
VALUATION_OBSERVATIONS_MIGRATIONS = (
    Migration(
        version=28,
        name="create_valuation_observations_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS valuation_observations (
                account_id   TEXT NOT NULL REFERENCES accounts(account_id),
                symbol       TEXT NOT NULL,
                price        REAL NOT NULL,
                observed_at  TEXT NOT NULL,
                source       TEXT NOT NULL,
                PRIMARY KEY (account_id, symbol)
            )
            """,
        ],
    ),
)
