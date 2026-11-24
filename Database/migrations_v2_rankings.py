"""Migration for ``v2_rankings``: one row per (market, signal date, stock).

Version 35, the next free slot after ``migrations_scheduler``/v34 in the
single global version sequence. Applied manually like every other domain
(``python run_v2_ranking_migrations.py``) and listed in
``Database.migration_registry`` so ``init``/``doctor`` know about it.

Each run of ``python main.py v2 rank`` stores the whole ranking for its
signal date (the last completed close): every stock's rank and score,
whether the date is a rebalance date, and whether the stock was one of the
picks. ``weights_json`` holds the factor weights used that day (identical
on every row of a date), so a ranking can be explained later.
"""
from __future__ import annotations

from .migrations import Migration

V2_RANKINGS_MIGRATIONS = (
    Migration(
        version=35,
        name="create_v2_rankings_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS v2_rankings (
                market         TEXT NOT NULL,
                signal_date    TEXT NOT NULL,
                symbol         TEXT NOT NULL,
                rank           INTEGER NOT NULL,
                score          REAL NOT NULL,
                is_rebalance   INTEGER NOT NULL,
                picked         INTEGER NOT NULL,
                model_version  TEXT NOT NULL,
                weights_json   TEXT,
                created_at     TEXT NOT NULL,
                PRIMARY KEY (market, signal_date, symbol)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_v2_rankings_rebalance
                ON v2_rankings (market, is_rebalance, signal_date)
            """,
        ],
    ),
)
