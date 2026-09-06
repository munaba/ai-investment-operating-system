from __future__ import annotations

from typing import List, Optional

from Database.models import RankingSnapshot
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class SnapshotRepository(BasePersistenceRepository):
    """Persists and queries ``RankingSnapshot`` rows -- one append-only
    record of what ``Business.ranking_engine.RankingEngine.rank()``
    produced for one symbol at one ``scan_time``.

    Sprint 5 STEP 3 scope: PERSISTENCE ONLY. This repository stores
    and retrieves whatever ``scan_time``/``symbol``/``recommendation``/
    ``confidence``/``priority``/``rank`` values a caller supplies. It
    does NOT:

    * run ``RankingEngine`` or call ``RankingEngine.rank()``,
    * read ``WatchlistScanner``, any Tool, or ``Core.analysis_pipeline``,
    * compute a ranking, a score, or a priority,
    * produce, validate, or derive a ``recommendation``,
    * update or delete a previously recorded snapshot.

    All ranking/recommendation computation is business logic that has
    already happened by the time a caller invokes ``create`` here --
    exactly the same division of responsibility ``TradeRepository``
    already establishes relative to ``ExecutionService``.

    Immutable / append-only (LOCKED design decision, mirrors
    ``TradeRepository``): this repository exposes no ``update``/
    ``delete``/``replace``/``modify`` method of any kind. Once a
    ``RankingSnapshot`` row is inserted it can never be changed or
    removed through this repository -- any future correction must be
    represented as an additional row, never an in-place mutation. See
    ``Database.models.RankingSnapshot`` for the full rationale.

    ``snapshot_id`` is a caller-agnostic, repository-generated
    surrogate integer -- mirrors ``TradeRepository``/
    ``PositionRepository``/``OrderRepository``, not
    ``AccountRepository``: a ranking snapshot's natural key
    (``scan_time`` + ``symbol``) is not enforced unique here, since
    this STEP has no requirement to reject or dedupe re-persisted
    scans.

    ``scan_time`` is a required, caller-supplied value -- this
    repository does not auto-generate it (unlike ``created_at``/
    ``updated_at`` on ``Account``/``Position``/``Order``, which record
    persistence-lifecycle time). ``scan_time`` is a business fact
    (when the scan this ranking came from ran), and deciding that
    value is the caller's job, exactly like ``executed_at`` on
    ``Trade``.
    """

    def create(
        self,
        scan_time: str,
        symbol: str,
        recommendation: Optional[str] = None,
        confidence: Optional[str] = None,
        priority: Optional[int] = None,
        rank: Optional[int] = None,
        *,
        status: str = "success",
        score: Optional[int] = None,
        score_breakdown_json: Optional[str] = None,
        evidence_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> RankingSnapshot:
        """Create a new, immutable ranking snapshot row.

        Args:
            scan_time: ISO-8601 timestamp of the scan run this ranking
                came from. Required, caller-supplied -- see class
                docstring for why this is not auto-generated.
            symbol: The ranked symbol/ticker.
            recommendation: Caller-supplied recommendation label (e.g.
                ``"BUY"``/``"SELL"``). ``None`` for an error row (see
                ``status``). Not validated or derived here.
            confidence: Caller-supplied confidence label, or ``None``
                for an error row.
            priority: Caller-supplied priority value, or ``None`` for
                an error row.
            rank: Caller-supplied rank value, or ``None`` for an error
                row.
            status: ``"success"`` (default) or ``"error"``. Activation
                2.7: a symbol that ``RankingEngine`` excluded is still
                persisted, with ``status="error"`` and
                ``error_message`` set, instead of silently vanishing.
            score: The ``RankedSymbol.score`` this row's recommendation
                came from, if any (``None`` for an error row).
            score_breakdown_json: ``json.dumps`` of the
                ``ScoreBreakdown`` behind ``score``, if any.
            evidence_summary: The real ``summary`` text
                ``WatchlistAnalysisSkill`` produced for this symbol,
                forwarded by identity -- never fabricated here.
            error_message: Why this symbol was excluded, for
                ``status="error"`` rows only.

        Returns:
            The newly created :class:`Database.models.RankingSnapshot`,
            including the ``snapshot_id`` assigned by the database.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            INSERT INTO ranking_snapshots
                (scan_time, symbol, status, recommendation, confidence,
                 priority, rank, score, score_breakdown_json,
                 evidence_summary, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_time,
                symbol,
                status,
                recommendation,
                confidence,
                priority,
                rank,
                score,
                score_breakdown_json,
                evidence_summary,
                error_message,
            ),
        )
        return RankingSnapshot(
            snapshot_id=result.lastrowid,
            scan_time=scan_time,
            symbol=symbol,
            recommendation=recommendation,
            confidence=confidence,
            priority=priority,
            rank=rank,
            status=status,
            score=score,
            score_breakdown_json=score_breakdown_json,
            evidence_summary=evidence_summary,
            error_message=error_message,
        )

    def get_by_id(self, snapshot_id: int) -> Optional[RankingSnapshot]:
        """Return the ranking snapshot with ``snapshot_id``, or ``None``
        if absent.

        Activation 5.6 addition (additive only): mirrors every other
        repository's own ``get_by_id`` (``AccountRepository``/
        ``PositionRepository``/``OrderRepository``/``TradeRepository``)
        -- a plain, single-row lookup by primary key, no new query
        shape. Added because Activation 5.6 (Strategy Attribution)
        needs to resolve the real ``RankingSnapshot`` a ``Trade``'s
        signal attribution points at (via ``Order.
        analysis_snapshot_id``), and no such lookup existed on this
        repository before now -- every pre-existing method here reads
        by ``scan_time`` instead. Performs no validation, join, or
        aggregation of any kind.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM ranking_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        return self._row_to_snapshot(result.rows[0]) if result.rows else None

    def list_latest(self) -> List[RankingSnapshot]:
        """Return every ranking snapshot from the most recent
        ``scan_time`` present in the table, ordered by ``rank``
        ascending.

        Returns an empty list if the table has no rows.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            SELECT * FROM ranking_snapshots
            WHERE scan_time = (SELECT MAX(scan_time) FROM ranking_snapshots)
            ORDER BY rank ASC
            """
        )
        return [self._row_to_snapshot(row) for row in result.rows]

    def list_by_scan_time(self, scan_time: str) -> List[RankingSnapshot]:
        """Return every ranking snapshot recorded for ``scan_time``,
        ordered by ``rank`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM ranking_snapshots WHERE scan_time = ? ORDER BY rank ASC",
            (scan_time,),
        )
        return [self._row_to_snapshot(row) for row in result.rows]

    def list_all(self) -> List[RankingSnapshot]:
        """Return every ranking snapshot, ordered by ``snapshot_id``
        ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id ASC")
        return [self._row_to_snapshot(row) for row in result.rows]

    def list_errors_by_scan_time(self, scan_time: str) -> List[RankingSnapshot]:
        """Return every ``status="error"`` snapshot recorded for
        ``scan_time`` (Activation 2.7), ordered by ``snapshot_id``
        ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM ranking_snapshots WHERE scan_time = ? AND status = 'error' "
            "ORDER BY snapshot_id ASC",
            (scan_time,),
        )
        return [self._row_to_snapshot(row) for row in result.rows]

    @staticmethod
    def _row_to_snapshot(row) -> RankingSnapshot:
        keys = row.keys() if hasattr(row, "keys") else {}
        return RankingSnapshot(
            snapshot_id=row["snapshot_id"],
            scan_time=row["scan_time"],
            symbol=row["symbol"],
            recommendation=row["recommendation"],
            confidence=row["confidence"],
            priority=row["priority"],
            rank=row["rank"],
            status=row["status"] if "status" in keys else "success",
            score=row["score"] if "score" in keys else None,
            score_breakdown_json=row["score_breakdown_json"] if "score_breakdown_json" in keys else None,
            evidence_summary=row["evidence_summary"] if "evidence_summary" in keys else None,
            error_message=row["error_message"] if "error_message" in keys else None,
        )