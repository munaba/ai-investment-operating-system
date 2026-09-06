from __future__ import annotations

from typing import List, Optional

from Database.models import JournalEntry
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class JournalRepository(BasePersistenceRepository):
    """Persists and queries ``journal_entries`` rows (Phase C --
    "Personal Risk Ledger + Decision Journal").

    PERSISTENCE ONLY, mirroring ``DecisionBriefRepository``: stores and
    retrieves exactly what ``Services.journal_service.JournalService``
    supplies. Does NOT:

    * decide whether a decision is ``ACCEPTED``/``RISK_REJECTED`` --
      that is ``Business.risk_ledger_policy.RiskLedgerPolicy``'s job,
    * compute ``planned_r``/``realized_r`` -- ``JournalService``
      supplies both, verbatim, when genuinely calculable,
    * ever create a paper order, ``Trade``, or ``Position``.

    ``create()`` is append-only for the decision itself, exactly like
    ``DecisionBriefRepository.create``. ``record_outcome()`` is the one
    deliberate exception (see ``Database.models.JournalEntry``): it
    updates only the five outcome columns of an already-created row,
    never the decision fields, and is intended to be called at most
    once per entry.
    """

    def create(
        self,
        *,
        brief_id: int,
        symbol: str,
        decision: str,
        decided_at: str,
        risk_policy_status: str,
        created_at: str,
        note: Optional[str] = None,
        risk_policy_reason: Optional[str] = None,
        planned_r: Optional[float] = None,
    ) -> JournalEntry:
        """Create a new journal entry row, outcome fields ``NULL``.

        Args:
            brief_id: The ``DecisionBrief.brief_id`` this decision is
                linked to. FK-enforced.
            symbol: The symbol, copied from the linked brief.
            decision: One of ``"TAKE"``/``"SKIP"``/``"WAIT"``.
            decided_at: ISO-8601 timestamp of the decision. Required,
                caller-supplied.
            risk_policy_status: ``"ACCEPTED"`` or ``"RISK_REJECTED"``,
                the verbatim ``RiskLedgerPolicy`` verdict.
            created_at: ISO-8601 timestamp this row was written.
            note: Optional free-text reason/note from the person.
            risk_policy_reason: Explanation for a ``RISK_REJECTED``
                verdict, or ``None``.
            planned_r: The linked brief's ``risk_reward_ratio``,
                verbatim, or ``None``.

        Returns:
            The newly created :class:`Database.models.JournalEntry`.

        Raises:
            RepositoryError: If the underlying statement fails (e.g.
                ``brief_id`` does not reference an existing brief).
        """
        result = self._execute(
            """
            INSERT INTO journal_entries
                (brief_id, symbol, decision, decided_at, note,
                 risk_policy_status, risk_policy_reason, planned_r, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brief_id,
                symbol,
                decision,
                decided_at,
                note,
                risk_policy_status,
                risk_policy_reason,
                planned_r,
                created_at,
            ),
        )
        return JournalEntry(
            entry_id=result.lastrowid,
            brief_id=brief_id,
            symbol=symbol,
            decision=decision,
            decided_at=decided_at,
            risk_policy_status=risk_policy_status,
            created_at=created_at,
            note=note,
            risk_policy_reason=risk_policy_reason,
            planned_r=planned_r,
        )

    def record_outcome(
        self,
        entry_id: int,
        *,
        outcome_status: str,
        closed_at: str,
        exit_price: Optional[float] = None,
        realized_r: Optional[float] = None,
    ) -> Optional[JournalEntry]:
        """Fill in the outcome of an already-created journal entry.

        Updates only the outcome columns
        (``outcome_status``/``exit_price``/``realized_r``/
        ``closed_at``) of the row identified by ``entry_id`` -- never
        the decision fields written by ``create()``.

        Args:
            entry_id: The journal entry to update.
            outcome_status: One of ``"OPEN"``/``"CLOSED_WIN"``/
                ``"CLOSED_LOSS"``/``"CLOSED_BREAKEVEN"``.
            closed_at: ISO-8601 timestamp of this close/update.
            exit_price: Real, caller-supplied exit price, if known.
            realized_r: Real R multiple, if genuinely calculable --
                never fabricated by this repository.

        Returns:
            The updated :class:`Database.models.JournalEntry`, or
            ``None`` if ``entry_id`` does not exist.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        if self.get_by_id(entry_id) is None:
            return None

        self._execute(
            """
            UPDATE journal_entries
            SET outcome_status = ?,
                exit_price = ?,
                realized_r = ?,
                closed_at = ?
            WHERE entry_id = ?
            """,
            (outcome_status, exit_price, realized_r, closed_at, entry_id),
        )
        return self.get_by_id(entry_id)

    def get_by_id(self, entry_id: int) -> Optional[JournalEntry]:
        """Return the journal entry with ``entry_id``, or ``None``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM journal_entries WHERE entry_id = ?",
            (entry_id,),
        )
        return self._row_to_entry(result.rows[0]) if result.rows else None

    def list_by_symbol(self, symbol: str) -> List[JournalEntry]:
        """Return every journal entry for ``symbol``, oldest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM journal_entries WHERE symbol = ? ORDER BY entry_id ASC",
            (symbol,),
        )
        return [self._row_to_entry(row) for row in result.rows]

    def list_by_brief_id(self, brief_id: int) -> List[JournalEntry]:
        """Return every journal entry linked to ``brief_id``, oldest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM journal_entries WHERE brief_id = ? ORDER BY entry_id ASC",
            (brief_id,),
        )
        return [self._row_to_entry(row) for row in result.rows]

    def list_all(self) -> List[JournalEntry]:
        """Return every journal entry, oldest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM journal_entries ORDER BY entry_id ASC")
        return [self._row_to_entry(row) for row in result.rows]

    @staticmethod
    def _row_to_entry(row) -> JournalEntry:
        return JournalEntry(
            entry_id=row["entry_id"],
            brief_id=row["brief_id"],
            symbol=row["symbol"],
            decision=row["decision"],
            decided_at=row["decided_at"],
            risk_policy_status=row["risk_policy_status"],
            created_at=row["created_at"],
            note=row["note"],
            risk_policy_reason=row["risk_policy_reason"],
            planned_r=row["planned_r"],
            outcome_status=row["outcome_status"],
            exit_price=row["exit_price"],
            realized_r=row["realized_r"],
            closed_at=row["closed_at"],
        )