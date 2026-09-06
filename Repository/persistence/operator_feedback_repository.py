"""``OperatorFeedbackRepository`` -- Phase H Task 4 ("Operator Feedback
+ Final Review Record").

PERSISTENCE ONLY, mirroring ``ObservationWindowRepository``: stores and
retrieves exactly what ``Services.sustained_use_final_review_service.
SustainedUseFinalReviewService`` supplies. Never validates a rating
range, never infers a concern label, never decides which window a
feedback row belongs to -- those are the service's job, one layer up.
This repository only records what the operator already gave.

Append-only rows (one per ``create``, never overwritten or deleted) --
an operator may record feedback for the same window more than once.
Restart-safe: a saved row survives a fresh repository instance over
the same on-disk database file, exactly like every other persistence
repository in this codebase.
"""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

from Database.models import OperatorFeedback
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class OperatorFeedbackRepository(BasePersistenceRepository):
    """Persists and retrieves ``operator_feedback`` rows."""

    def create(
        self,
        *,
        observation_window_id: int,
        recorded_at: str,
        operator_rating: Optional[int] = None,
        alert_usefulness: Optional[str] = None,
        data_reliability_feedback: Optional[str] = None,
        decision_quality_feedback: Optional[str] = None,
        workflow_usability_feedback: Optional[str] = None,
        free_text: Optional[str] = None,
        concerns: Optional[Sequence[str]] = None,
        operator_label: Optional[str] = None,
    ) -> OperatorFeedback:
        """Insert a new operator feedback row.

        ``feedback_id`` is repository-generated (autoincrement), never
        caller-supplied -- mirrors ``DecisionBriefRepository.create``.
        Does not check whether ``observation_window_id`` refers to a
        real window; that belongs to
        ``SustainedUseFinalReviewService.record_feedback``, one layer
        up.

        Args:
            observation_window_id: The window this feedback concerns,
                exactly as given.
            recorded_at: ISO-8601 UTC timestamp of this call. Required,
                caller-supplied -- this repository does not
                auto-generate it.
            operator_rating: Optional overall usefulness rating,
                exactly as given.
            alert_usefulness: Optional free-text/label feedback,
                exactly as given.
            data_reliability_feedback: Optional free-text/label
                feedback, exactly as given.
            decision_quality_feedback: Optional free-text/label
                feedback, exactly as given.
            workflow_usability_feedback: Optional free-text/label
                feedback, exactly as given.
            free_text: Optional open-ended comment, exactly as given.
            concerns: Optional sequence of operator-selected concern/
                limitation labels, exactly as given. Persisted as a
                JSON-encoded list; ``None``/empty persists as ``"[]"``.
            operator_label: Optional operator identifier/label, exactly
                as given.

        Returns:
            The newly persisted :class:`Database.models.OperatorFeedback`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        concerns_json = json.dumps(list(concerns) if concerns else [])
        result = self._execute(
            """
            INSERT INTO operator_feedback
                (observation_window_id, recorded_at, operator_rating,
                 alert_usefulness, data_reliability_feedback,
                 decision_quality_feedback, workflow_usability_feedback,
                 free_text, concerns, operator_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_window_id,
                recorded_at,
                operator_rating,
                alert_usefulness,
                data_reliability_feedback,
                decision_quality_feedback,
                workflow_usability_feedback,
                free_text,
                concerns_json,
                operator_label,
            ),
        )
        feedback_id = result.lastrowid
        return OperatorFeedback(
            feedback_id=feedback_id,
            observation_window_id=observation_window_id,
            recorded_at=recorded_at,
            operator_rating=operator_rating,
            alert_usefulness=alert_usefulness,
            data_reliability_feedback=data_reliability_feedback,
            decision_quality_feedback=decision_quality_feedback,
            workflow_usability_feedback=workflow_usability_feedback,
            free_text=free_text,
            concerns=concerns_json,
            operator_label=operator_label,
        )

    def get_by_id(self, feedback_id: int) -> Optional[OperatorFeedback]:
        """Return the exact row for ``feedback_id``, or ``None``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM operator_feedback WHERE feedback_id = ?",
            (feedback_id,),
        )
        return self._row_to_feedback(result.rows[0]) if result.rows else None

    def list_by_window(self, observation_window_id: int) -> List[OperatorFeedback]:
        """Return every feedback row for ``observation_window_id``,
        ordered by ``feedback_id`` ascending (oldest first).

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM operator_feedback WHERE observation_window_id = ? "
            "ORDER BY feedback_id ASC",
            (observation_window_id,),
        )
        return [self._row_to_feedback(row) for row in result.rows]

    def list_all(self) -> List[OperatorFeedback]:
        """Return every feedback row ever recorded, ordered by
        ``feedback_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM operator_feedback ORDER BY feedback_id ASC")
        return [self._row_to_feedback(row) for row in result.rows]

    @staticmethod
    def _row_to_feedback(row) -> OperatorFeedback:
        return OperatorFeedback(
            feedback_id=row["feedback_id"],
            observation_window_id=row["observation_window_id"],
            recorded_at=row["recorded_at"],
            operator_rating=row["operator_rating"],
            alert_usefulness=row["alert_usefulness"],
            data_reliability_feedback=row["data_reliability_feedback"],
            decision_quality_feedback=row["decision_quality_feedback"],
            workflow_usability_feedback=row["workflow_usability_feedback"],
            free_text=row["free_text"],
            concerns=row["concerns"],
            operator_label=row["operator_label"],
        )