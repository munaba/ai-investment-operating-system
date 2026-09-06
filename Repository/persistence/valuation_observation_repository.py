from __future__ import annotations

from typing import Optional

from Database.models import ValuationObservation
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class ValuationObservationRepository(BasePersistenceRepository):
    """Persists and retrieves the single most-recent
    :class:`Database.models.ValuationObservation` row per
    ``(account_id, symbol)`` (Phase G Task 3).

    PERSISTENCE ONLY, mirroring ``PortfolioSnapshotRepository``/
    ``RiskLimitsRepository``: stores and retrieves exactly what the
    caller supplies. Never fetches a market price itself, never
    decides freshness -- that is
    ``Business.data_freshness_policy.DataFreshnessPolicy``'s job, one
    layer up, in ``Business.unrealized_pnl_engine.UnrealizedPnLEngine``.

    Mutable row per key (unlike ``PortfolioSnapshotRepository``'s
    append-only design, mirrors ``RiskLimitsRepository.save``): each
    ``(account_id, symbol)`` has at most one row, overwritten in place
    on every new observation -- this is a "last known good" cache, not
    a history. Restart-safe: a recorded observation survives a fresh
    repository instance over the same on-disk database file.
    """

    def record(
        self,
        account_id: str,
        symbol: str,
        price: float,
        observed_at: str,
        source: str,
    ) -> ValuationObservation:
        """Create or overwrite the ``(account_id, symbol)`` observation row.

        Args:
            account_id: The account this observation's position
                belongs to.
            symbol: The ticker this observation is for.
            price: The observed market price. Persisted exactly as
                supplied -- never recomputed here.
            observed_at: ISO-8601 UTC timestamp of the moment
                ``price`` was genuinely obtained. Required,
                caller-supplied -- this repository does not
                auto-generate it (mirrors ``PortfolioSnapshotRepository.
                create``'s ``timestamp`` contract).
            source: Free-text label identifying where this
                observation came from.

        Returns:
            The recorded :class:`Database.models.ValuationObservation`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        # Explicit "does this (account_id, symbol) row already exist"
        # check rather than a SQL upsert, mirroring
        # ``RiskLimitsRepository.save``'s existing mutable-row
        # convention -- never a single ``ON CONFLICT`` clause.
        if self.get(account_id, symbol) is None:
            self._execute(
                """
                INSERT INTO valuation_observations
                    (account_id, symbol, price, observed_at, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, symbol, price, observed_at, source),
            )
        else:
            self._execute(
                """
                UPDATE valuation_observations
                SET price = ?, observed_at = ?, source = ?
                WHERE account_id = ? AND symbol = ?
                """,
                (price, observed_at, source, account_id, symbol),
            )
        return ValuationObservation(
            account_id=account_id,
            symbol=symbol,
            price=price,
            observed_at=observed_at,
            source=source,
        )

    def get(self, account_id: str, symbol: str) -> Optional[ValuationObservation]:
        """Return the most recent observation for ``(account_id, symbol)``,
        or ``None`` if none has ever been recorded.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM valuation_observations WHERE account_id = ? AND symbol = ?",
            (account_id, symbol),
        )
        if not result.rows:
            return None
        row = result.rows[0]
        return ValuationObservation(
            account_id=row["account_id"],
            symbol=row["symbol"],
            price=row["price"],
            observed_at=row["observed_at"],
            source=row["source"],
        )
