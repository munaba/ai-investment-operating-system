from __future__ import annotations

from typing import List, Optional

from Database.models import RiskLimits
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: The one and only row this repository ever reads or writes. Personal
#: risk limits are singular for the whole person/account, not
#: per-symbol or per-account -- mirrors why there is exactly one
#: ``RiskLimits`` row rather than a table keyed some other way.
_DEFAULT_ROW_ID = "default"


class RiskLimitsRepository(BasePersistenceRepository):
    """Persists and retrieves the single ``risk_limits`` row (Phase C --
    "Personal Risk Ledger").

    PERSISTENCE ONLY, mirroring ``DecisionBriefRepository``: stores and
    retrieves exactly what the caller supplies. Never computes a
    limit, never validates a trade against it, never decides whether a
    decision is allowed -- that is
    ``Business.risk_ledger_policy.RiskLedgerPolicy``'s job, one layer
    up, in ``Services.journal_service.JournalService``.

    Mutable singleton row (unlike ``DecisionBriefRepository``/
    ``SnapshotRepository``'s append-only design): ``save()`` is an
    upsert against the fixed ``id='default'`` row, mirroring
    ``AccountRepository.update_balances``'s "one row, updated in
    place" shape. Restart-safe: a saved row survives a fresh
    repository instance over the same on-disk database file.
    """

    def save(
        self,
        *,
        reference_capital: float,
        max_risk_per_trade_percent: float,
        max_daily_loss: float,
        max_trades_per_day: int,
        loss_streak_cooldown: int,
        updated_at: str,
        allowed_symbols: Optional[List[str]] = None,
    ) -> RiskLimits:
        """Create or overwrite the single ``risk_limits`` row.

        Args:
            reference_capital: The capital base ``max_risk_per_trade_percent``
                is evaluated against. Real, caller-supplied -- never
                read off a live ``Account.equity``.
            max_risk_per_trade_percent: Max fraction of
                ``reference_capital`` a single TAKE's
                ``DecisionBrief.risk_amount`` may consume.
            max_daily_loss: Max cumulative realized-loss dollars
                allowed in one calendar day before further TAKEs are
                rejected.
            max_trades_per_day: Max number of ACCEPTED TAKE decisions
                allowed in one calendar day.
            loss_streak_cooldown: Number of consecutive realized
                losses that, once reached, blocks further TAKEs.
            updated_at: ISO-8601 timestamp of this save. Required,
                caller-supplied -- this repository does not
                auto-generate it.
            allowed_symbols: Optional allowlist of symbols a TAKE may
                target. ``None``/empty means no restriction.

        Returns:
            The saved :class:`Database.models.RiskLimits`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        allowed_symbols_text = ",".join(s.upper() for s in allowed_symbols) if allowed_symbols else None

        # Explicit "does the singleton row already exist" check rather
        # than a SQL upsert, mirroring this codebase's existing
        # mutable-row convention (see ``AccountRepository.create`` vs.
        # ``update_balances``: two distinct statements, never a single
        # ``ON CONFLICT`` clause).
        if self.get_current() is None:
            self._execute(
                """
                INSERT INTO risk_limits
                    (id, reference_capital, max_risk_per_trade_percent, max_daily_loss,
                     max_trades_per_day, loss_streak_cooldown, allowed_symbols, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _DEFAULT_ROW_ID,
                    reference_capital,
                    max_risk_per_trade_percent,
                    max_daily_loss,
                    max_trades_per_day,
                    loss_streak_cooldown,
                    allowed_symbols_text,
                    updated_at,
                ),
            )
        else:
            self._execute(
                """
                UPDATE risk_limits
                SET reference_capital = ?,
                    max_risk_per_trade_percent = ?,
                    max_daily_loss = ?,
                    max_trades_per_day = ?,
                    loss_streak_cooldown = ?,
                    allowed_symbols = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    reference_capital,
                    max_risk_per_trade_percent,
                    max_daily_loss,
                    max_trades_per_day,
                    loss_streak_cooldown,
                    allowed_symbols_text,
                    updated_at,
                    _DEFAULT_ROW_ID,
                ),
            )
        return RiskLimits(
            id=_DEFAULT_ROW_ID,
            reference_capital=reference_capital,
            max_risk_per_trade_percent=max_risk_per_trade_percent,
            max_daily_loss=max_daily_loss,
            max_trades_per_day=max_trades_per_day,
            loss_streak_cooldown=loss_streak_cooldown,
            allowed_symbols=[s.upper() for s in allowed_symbols] if allowed_symbols else None,
            updated_at=updated_at,
        )

    def get_current(self) -> Optional[RiskLimits]:
        """Return the current ``risk_limits`` row, or ``None`` if no
        limits have ever been saved.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM risk_limits WHERE id = ?",
            (_DEFAULT_ROW_ID,),
        )
        return self._row_to_limits(result.rows[0]) if result.rows else None

    @staticmethod
    def _row_to_limits(row) -> RiskLimits:
        allowed_symbols_text = row["allowed_symbols"]
        allowed_symbols = allowed_symbols_text.split(",") if allowed_symbols_text else None
        return RiskLimits(
            id=row["id"],
            reference_capital=row["reference_capital"],
            max_risk_per_trade_percent=row["max_risk_per_trade_percent"],
            max_daily_loss=row["max_daily_loss"],
            max_trades_per_day=row["max_trades_per_day"],
            loss_streak_cooldown=row["loss_streak_cooldown"],
            allowed_symbols=allowed_symbols,
            updated_at=row["updated_at"],
        )