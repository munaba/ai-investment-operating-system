"""Production migration for the ``ranking_snapshots`` table (Sprint 5 STEP 3).

Persistence only -- see ``Repository.persistence.snapshot_repository.
SnapshotRepository`` docstring for the full scope boundary (no
``RankingEngine`` invocation, no ``WatchlistScanner``/Tool/
``AnalysisPipeline`` reads, no ranking computation, no recommendation
generation here or there; this STEP only stores whatever
``RankedSymbol``-shaped state a caller supplies, after ``RankingEngine.
rank()`` has already produced it).

``snapshot_id`` is a surrogate ``INTEGER PRIMARY KEY AUTOINCREMENT``,
mirroring ``trades.trade_id``/``positions.position_id``/
``orders.order_id`` rather than ``accounts.account_id``: a ranking
snapshot has no stable natural key of its own -- the same ``symbol``
reappears across many distinct scans over time (``scan_time`` +
``symbol`` is the closest thing to a natural key, and even that is
only unique per scan run, never enforced here as a UNIQUE constraint
since re-running a scan and re-persisting the same symbol/scan_time
pair is not this STEP's concern to prevent).

Version=10 (LOCKED DECISION): versions 6-9 are already reserved
(``analysis_snapshots``, ``recommendations``, ``portfolio_snapshots``,
``daily_performance`` -- see ``Database.migrations_accounts`` for the
full allocation table) for a different, ERD-defined schema
(``instrument_id`` FK / ``analysis_type`` / ``payload_json``) tied to
a future AI-analysis-payload store, not yet implemented. This table
stores something distinct: the already-flattened output of
``Business.ranking_engine.RankingEngine.rank()`` (``RankedSymbol``:
``symbol``/``recommendation``/``confidence``/``priority``/``rank``),
timestamped per scan. Reusing version=6 or the name
``analysis_snapshots`` for this different schema would both violate
the existing "Do not reuse" reservation and collide with that future
table's name once it is actually built. version=10 is therefore the
first free slot after the entire 1-9 reserved range, leaving 6-9
untouched for their originally reserved purpose.

Table name is ``ranking_snapshots``, not ``analysis_snapshots`` (that
name is reserved for the different ERD schema above) and not the
generic ``snapshots`` (ambiguous with the unrelated Sprint 2
AutonomousHost snapshot/restore concept in ``Docs.AIOS_Roadmap``) --
the name states exactly what this table holds: one row per symbol per
``RankingEngine`` run.

Immutable / append-only (LOCKED design decision, mirrors ``trades``):
no ``update``/``delete`` statement or index supports mutation here --
see ``Repository.persistence.snapshot_repository.SnapshotRepository``
for the enforced absence of any update/delete method.

Two indexes, both structural (not business logic), mirroring the
exact reasoning behind ``idx_trades_account_id``/``idx_trades_order_id``:

* ``(scan_time)`` -- supports ``list_by_scan_time``: "every ranked
  symbol from this scan run".
* ``(symbol)`` -- supports a future "history for this symbol across
  scans" query; cheap to add now, not exercised by any query this
  STEP's locked scope requires yet.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from every
other ``Database.migrations_*`` module (different, already-applied or
separately-reserved versions), mirroring the same pattern.

Not wired to ``Core.composition_root`` or ``main.py`` for migration
*execution* (same scope decision as accounts/watchlist/positions/
orders/trades): no automatic migration run at startup. A caller passes
``SNAPSHOTS_MIGRATIONS`` to ``MigrationRunner(database).apply(
SNAPSHOTS_MIGRATIONS)`` explicitly -- see ``run_snapshot_migrations.py``.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table,
# see Database.migrations_accounts for the full reserved list):
#   1 = watchlist, 2 = accounts, 3 = positions, 4 = orders, 5 = trades,
#   6 = analysis_snapshots, 7 = recommendations, 8 = portfolio_snapshots,
#   9 = daily_performance -- all reserved, untouched by this file.
#   10 = ranking_snapshots (this file, Sprint 5 STEP 3, LOCKED DECISION:
#   deliberately NOT version=6 -- see module docstring for the full
#   reasoning on why the reserved 6-9 range does not fit this schema).
SNAPSHOTS_MIGRATIONS = (
    Migration(
        version=10,
        name="create_ranking_snapshots_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS ranking_snapshots (
                snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time       TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                recommendation  TEXT NOT NULL,
                confidence      TEXT NOT NULL,
                priority        INTEGER NOT NULL,
                rank            INTEGER NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_scan_time
            ON ranking_snapshots (scan_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_symbol
            ON ranking_snapshots (symbol)
            """,
        ],
    ),
    # version=11 (Activation 2.7): extends the SAME canonical table
    # rather than creating analysis_snapshots/recommendations as new,
    # competing tables -- per Activation 2.7's own "gunakan storage
    # canonical yang sudah ada bila memungkinkan" / "jangan
    # menduplikasi data" requirements, and because one RankingEngine
    # run over one symbol already IS one analysis + one recommendation
    # + one ranking, all produced together and consumed together --
    # splitting them into separate tables would need a join key that
    # doesn't add any information a single row doesn't already carry.
    #
    # New columns:
    #   status                TEXT NOT NULL DEFAULT 'success'
    #       -- 'success' or 'error'. Existing rows (all pre-v11, all
    #       already-successful snapshots) backfill to 'success'.
    #   score                 INTEGER NULL
    #   score_breakdown_json  TEXT NULL   -- json.dumps(ScoreBreakdown)
    #   evidence_summary      TEXT NULL   -- the real WatchlistAnalysisSkill
    #                                        summary text, never fabricated
    #   error_message         TEXT NULL   -- populated only for status='error'
    #
    # recommendation/confidence/priority/rank become NULLable: an
    # error row (a symbol RankingEngine's own filter excluded) has no
    # recommendation/confidence/priority/rank to report -- forcing
    # those NOT NULL would mean either fabricating a value for a
    # symbol that never produced one, or not persisting the error row
    # at all (silently losing it again, the exact problem this
    # Activation exists to fix).
    #
    # SQLite's ALTER TABLE cannot relax an existing NOT NULL column
    # nor add a NOT NULL column without a default over existing rows
    # in one step, so this migration uses the standard SQLite
    # rebuild-in-place technique: rename the old table out of the way,
    # create the new (v11) shape under the original name, copy every
    # existing row across (defaulting the five new columns), drop the
    # renamed original, then recreate both indexes. All of this runs
    # inside the single nested SAVEPOINT ``MigrationRunner.apply()``
    # already wraps each migration in, so a failure partway through
    # rolls back cleanly -- no separate transaction handling is added
    # here.
    Migration(
        version=11,
        name="extend_ranking_snapshots_for_status_and_analysis",
        up_statements=[
            "ALTER TABLE ranking_snapshots RENAME TO ranking_snapshots_v10",
            """
            CREATE TABLE ranking_snapshots (
                snapshot_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time             TEXT NOT NULL,
                symbol                TEXT NOT NULL,
                status                TEXT NOT NULL DEFAULT 'success',
                recommendation        TEXT,
                confidence            TEXT,
                priority              INTEGER,
                rank                  INTEGER,
                score                 INTEGER,
                score_breakdown_json  TEXT,
                evidence_summary      TEXT,
                error_message         TEXT
            )
            """,
            """
            INSERT INTO ranking_snapshots (
                snapshot_id, scan_time, symbol, status,
                recommendation, confidence, priority, rank,
                score, score_breakdown_json, evidence_summary, error_message
            )
            SELECT
                snapshot_id, scan_time, symbol, 'success',
                recommendation, confidence, priority, rank,
                NULL, NULL, NULL, NULL
            FROM ranking_snapshots_v10
            """,
            "DROP TABLE ranking_snapshots_v10",
            """
            CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_scan_time
            ON ranking_snapshots (scan_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_symbol
            ON ranking_snapshots (symbol)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ranking_snapshots_status
            ON ranking_snapshots (status)
            """,
        ],
    ),
)