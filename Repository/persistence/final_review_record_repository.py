"""``FinalReviewRecordRepository`` -- Phase H Task 4 ("Operator
Feedback + Final Review Record").

PERSISTENCE ONLY, mirroring ``ObservationWindowRepository``: stores and
retrieves exactly what ``Services.sustained_use_final_review_service.
SustainedUseFinalReviewService`` supplies. Never decides what evidence
status a window has, never selects which feedback to link, never picks
a human decision -- those are the service's job, one layer up. This
repository only records what the service already assembled/was told.

Exactly one row per ``observation_window_id`` (a unique index enforces
this at the database level, mirroring ``risk_limits``'s single-row
convention rather than an append-only history), updated in place by
``update_evidence``/``record_decision``. Restart-safe: a saved row
survives a fresh repository instance over the same on-disk database
file, exactly like every other persistence repository in this
codebase.
"""

from __future__ import annotations

from typing import List, Optional

from Database.models import FinalReviewRecord
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: The one human_decision value a freshly created row may ever start
#: at. Every other value is only ever reached through an explicit,
#: caller-supplied ``record_decision`` call -- never inferred here or
#: in the service layer.
DECISION_PENDING: str = "PENDING"


class FinalReviewRecordRepository(BasePersistenceRepository):
    """Persists and retrieves ``final_review_records`` rows."""

    def get_by_window(self, observation_window_id: int) -> Optional[FinalReviewRecord]:
        """Return the single row for ``observation_window_id``, or
        ``None`` if no final review has ever been created for it.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM final_review_records WHERE observation_window_id = ?",
            (observation_window_id,),
        )
        return self._row_to_record(result.rows[0]) if result.rows else None

    def get_by_id(self, review_id: int) -> Optional[FinalReviewRecord]:
        """Return the exact row for ``review_id``, or ``None``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM final_review_records WHERE review_id = ?",
            (review_id,),
        )
        return self._row_to_record(result.rows[0]) if result.rows else None

    def create(
        self,
        *,
        observation_window_id: int,
        reviewed_at: str,
        evidence_status: str,
        known_limitations: str,
        operator_feedback_ids: str,
        created_at: str,
    ) -> FinalReviewRecord:
        """Insert a new final review row with ``human_decision="PENDING"``.

        Does not check whether a row already exists for
        ``observation_window_id`` -- that gate belongs to
        ``SustainedUseFinalReviewService``, which calls
        :meth:`get_by_window` first and calls :meth:`update_evidence`
        instead when one already exists.

        Args:
            observation_window_id: The window this review concerns.
            reviewed_at: ISO-8601 UTC timestamp evidence was last
                assembled, caller-supplied.
            evidence_status: Verbatim
                ``SustainedUseReviewResult.overall_evidence_status``.
            known_limitations: JSON-encoded list of known-limitation
                strings, verbatim.
            operator_feedback_ids: JSON-encoded list of linked
                ``OperatorFeedback.feedback_id`` values, verbatim.
            created_at: ISO-8601 UTC timestamp of this call.

        Returns:
            The newly persisted :class:`Database.models.FinalReviewRecord`.

        Raises:
            RepositoryError: If the underlying statement fails (including
                a unique-constraint violation if a row already exists
                for this window).
        """
        result = self._execute(
            """
            INSERT INTO final_review_records
                (observation_window_id, reviewed_at, evidence_status,
                 known_limitations, operator_feedback_ids, human_decision,
                 decision_note, decided_at, decided_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                observation_window_id,
                reviewed_at,
                evidence_status,
                known_limitations,
                operator_feedback_ids,
                DECISION_PENDING,
                created_at,
                created_at,
            ),
        )
        review_id = result.lastrowid
        return FinalReviewRecord(
            review_id=review_id,
            observation_window_id=observation_window_id,
            reviewed_at=reviewed_at,
            evidence_status=evidence_status,
            known_limitations=known_limitations,
            operator_feedback_ids=operator_feedback_ids,
            human_decision=DECISION_PENDING,
            decision_note=None,
            decided_at=None,
            decided_by=None,
            created_at=created_at,
            updated_at=created_at,
        )

    def update_evidence(
        self,
        observation_window_id: int,
        *,
        reviewed_at: str,
        evidence_status: str,
        known_limitations: str,
        operator_feedback_ids: str,
        updated_at: str,
    ) -> Optional[FinalReviewRecord]:
        """Refresh the evidence-derived columns of an existing row in
        place, preserving ``human_decision``/``decision_note``/
        ``decided_at``/``decided_by``/``created_at`` unchanged.

        Never touches ``human_decision`` -- refreshing evidence (e.g.
        after more operating records accrue) never advances or resets
        a decision; that only ever happens via :meth:`record_decision`.

        Returns:
            The updated :class:`Database.models.FinalReviewRecord`, or
            ``None`` if no row exists for ``observation_window_id``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        existing = self.get_by_window(observation_window_id)
        if existing is None:
            return None
        self._execute(
            """
            UPDATE final_review_records
            SET reviewed_at = ?, evidence_status = ?, known_limitations = ?,
                operator_feedback_ids = ?, updated_at = ?
            WHERE observation_window_id = ?
            """,
            (
                reviewed_at,
                evidence_status,
                known_limitations,
                operator_feedback_ids,
                updated_at,
                observation_window_id,
            ),
        )
        return self.get_by_window(observation_window_id)

    def record_decision(
        self,
        observation_window_id: int,
        *,
        human_decision: str,
        decision_note: Optional[str],
        decided_at: str,
        decided_by: Optional[str],
        updated_at: str,
    ) -> Optional[FinalReviewRecord]:
        """Set the explicit human decision on an existing row in place,
        preserving every evidence-derived column unchanged.

        Does not validate ``human_decision`` against the allowed
        vocabulary or check evidence sufficiency -- both belong to
        ``SustainedUseFinalReviewService.record_decision``, one layer
        up. This repository only ever writes exactly what it is told.

        Returns:
            The updated :class:`Database.models.FinalReviewRecord`, or
            ``None`` if no row exists for ``observation_window_id``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        existing = self.get_by_window(observation_window_id)
        if existing is None:
            return None
        self._execute(
            """
            UPDATE final_review_records
            SET human_decision = ?, decision_note = ?, decided_at = ?,
                decided_by = ?, updated_at = ?
            WHERE observation_window_id = ?
            """,
            (
                human_decision,
                decision_note,
                decided_at,
                decided_by,
                updated_at,
                observation_window_id,
            ),
        )
        return self.get_by_window(observation_window_id)

    def list_all(self) -> List[FinalReviewRecord]:
        """Return every final review row ever created, ordered by
        ``review_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM final_review_records ORDER BY review_id ASC")
        return [self._row_to_record(row) for row in result.rows]

    @staticmethod
    def _row_to_record(row) -> FinalReviewRecord:
        return FinalReviewRecord(
            review_id=row["review_id"],
            observation_window_id=row["observation_window_id"],
            reviewed_at=row["reviewed_at"],
            evidence_status=row["evidence_status"],
            known_limitations=row["known_limitations"],
            operator_feedback_ids=row["operator_feedback_ids"],
            human_decision=row["human_decision"],
            decision_note=row["decision_note"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )