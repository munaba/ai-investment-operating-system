from __future__ import annotations

# Single source of truth for Positions domain values.
#
# Both Repository.persistence.position_repository.PositionRepository
# (Python-level validation) and Database.migrations_positions
# (SQL CHECK constraint, generated from this same tuple at import
# time) read from here. Nothing else defines this value separately.
# Mirrors the same single-source-of-truth pattern used by
# Database.account_constants for ACCOUNT_MODES/ACCOUNT_ASSET_CLASSES.
#
# Trade-off: once POSITIONS_MIGRATIONS (version=3) has been applied to
# a real database, its CHECK constraint is baked into that table's
# schema as-is. Changing this tuple later does NOT retroactively
# change an already-applied table -- it requires a new migration
# (ALTER TABLE / recreate), same as any other schema change. Do not
# edit version=3 after it has been applied anywhere.
#
# Only "open"/"closed" exist at this STEP (Sprint 4 STEP 2:
# persistence only). Any additional lifecycle state (e.g. a
# "partially_closed" status) is a business-logic decision for a later
# STEP, not introduced speculatively here.
POSITION_STATUSES: tuple[str, ...] = ("open", "closed")

# Single source of truth for Position.direction (Activation 11.11,
# persistence groundwork for Activation 11.10's LOCKED Forex
# persistence decision). Mirrors POSITION_STATUSES exactly: both
# Repository.persistence.position_repository.PositionRepository
# (Python-level validation) and Database.migrations_positions (SQL
# CHECK constraint, generated from this same tuple at import time)
# read from here.
#
# "LONG"/"SHORT" only, at this STEP. "LONG" is every existing
# position's implicit, unwritten direction today (this codebase has
# no short-position concept anywhere prior to this column existing --
# see Activation 11.10 Decision B/C) -- it is the DEFAULT value new
# rows and pre-existing migrated rows both receive. "SHORT" is added
# now purely as persistence groundwork for a future Forex short-open
# STEP (Business.position_manager.PositionManager is NOT modified by
# this STEP -- no code path produces "SHORT" yet).
POSITION_DIRECTIONS: tuple[str, ...] = ("LONG", "SHORT")