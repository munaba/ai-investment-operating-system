"""``SustainedUseFinalReviewService`` -- Phase H Task 4 ("Operator
Feedback + Final Review Record").

Ties together three already-complete, LOCKED pieces of Phase H:

    * Task 1's ``Repository.persistence.observation_window_repository.
      ObservationWindowRepository`` -- which real window is under
      review.
    * Task 2's ``Services.sustained_use_review_service.
      SustainedUseReviewService`` -- the real, honest, possibly-partial
      evidence for that window.
    * this task's own two new persistence records --
      ``Repository.persistence.operator_feedback_repository.
      OperatorFeedbackRepository`` (real, explicitly-given operator
      feedback) and ``Repository.persistence.
      final_review_record_repository.FinalReviewRecordRepository``
      (the single durable per-window record tying evidence + feedback
      + the eventual human decision together).

This service makes NO CONTINUE/SIMPLIFY/AUTHORIZE_FUTURE_INVESTIGATION
decision itself, ever. ``human_decision`` starts at, and stays,
``"PENDING"`` until a caller explicitly supplies one of the three
other values to :meth:`record_decision` -- there is no default, no
inference from evidence quality, no scoring/recommendation logic
anywhere in this module. This service also never calls an LLM or
provider of any kind (it imports none), so no model output can ever
influence ``human_decision`` even indirectly.

Evidence-insufficiency gate (LOCKED, DERIVED-NOT-FABRICATED): Task 2's
``SustainedUseReviewService`` already unconditionally computes
``AvailabilityEvidence.scheduled_job_count`` -- the real count of
``SchedulerJobRun`` rows recorded inside the window -- regardless of
whether any other collaborator was wired up. A window with
``scheduled_job_count == 0`` has had zero real operating activity
recorded yet, i.e. there is nothing yet for a human to review. This is
the one clear, already-existing insufficiency condition this service
relies on to reject an explicit CONTINUE/SIMPLIFY/
AUTHORIZE_FUTURE_INVESTIGATION decision -- never a fabricated
threshold, never an LLM judgment call, just the same real count Task 3
already prints verbatim in section 2 of its report. ``PENDING`` is
never rejected by this gate (recording/confirming "no decision yet" is
always allowed, including as an explicit way to undo a prior decision).

WRITE SCOPE (STRICT): every write this service performs lands on
exactly two tables -- ``operator_feedback`` and
``final_review_records`` (both new, this task only). This service
holds no reference to, and never calls, any order/trade/position/
risk-limit/account repository, ``PaperTradingEngine``,
``OrderLifecycleService``, ``ExecutionService``, or any risk-policy
component. It never unlocks live/broker execution and never changes
trading configuration or permissions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from Core.exceptions import ValidationError
from Database.models import (
    FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION,
    FINAL_REVIEW_DECISION_CONTINUE,
    FINAL_REVIEW_DECISION_PENDING,
    FINAL_REVIEW_DECISION_SIMPLIFY,
    FinalReviewRecord,
    ObservationWindow,
    OperatorFeedback,
)
from Repository.persistence.final_review_record_repository import FinalReviewRecordRepository
from Repository.persistence.observation_window_repository import ObservationWindowRepository
from Repository.persistence.operator_feedback_repository import OperatorFeedbackRepository
from Services.sustained_use_review_service import (
    SustainedUseReviewResult,
    SustainedUseReviewService,
)

#: The full, LOCKED set of values ``human_decision`` may ever hold.
#: See ``Database.models.FINAL_REVIEW_DECISION_*``.
ALLOWED_DECISIONS = frozenset(
    {
        FINAL_REVIEW_DECISION_PENDING,
        FINAL_REVIEW_DECISION_CONTINUE,
        FINAL_REVIEW_DECISION_SIMPLIFY,
        FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION,
    }
)

#: Decisions that actually close the review loop -- these, and only
#: these, are gated by the evidence-insufficiency check below.
#: ``PENDING`` is deliberately excluded: recording "no decision yet"
#: (including explicitly reverting a prior decision back to it) is
#: always allowed regardless of evidence state.
_DECISIONS_REQUIRING_SUFFICIENT_EVIDENCE = frozenset(
    {
        FINAL_REVIEW_DECISION_CONTINUE,
        FINAL_REVIEW_DECISION_SIMPLIFY,
        FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION,
    }
)


def _known_limitations_to_json(result: SustainedUseReviewResult) -> str:
    """Render ``result.known_limitations`` (a tuple of
    ``EvidenceLimitation``) into a JSON-encoded list of plain strings,
    verbatim -- never summarized, reworded, or dropped.
    """
    return json.dumps(
        [
            f"[{limitation.status}] {limitation.dimension}: {limitation.detail}"
            for limitation in result.known_limitations
        ]
    )


class SustainedUseFinalReviewService:
    """Orchestrates Phase H Task 4's operator-feedback and
    final-review-record workflow for one ``ObservationWindow`` at a
    time.

    Constructor injection only, mirroring ``SustainedUseReviewService``:
    every repository/service collaborator is supplied by the caller,
    never constructed here. Stateless beyond these collaborators --
    safe to reuse across calls, restart-safe since nothing is cached.
    """

    def __init__(
        self,
        observation_window_repository: ObservationWindowRepository,
        sustained_use_review_service: SustainedUseReviewService,
        operator_feedback_repository: OperatorFeedbackRepository,
        final_review_record_repository: FinalReviewRecordRepository,
    ) -> None:
        self._window_repository = observation_window_repository
        self._review_service = sustained_use_review_service
        self._feedback_repository = operator_feedback_repository
        self._record_repository = final_review_record_repository

    # -- window resolution (mirrors SustainedUseReviewService) -------------

    def _resolve_window(self, window_id: Optional[int]) -> ObservationWindow:
        if window_id is not None:
            window = self._window_repository.get_by_id(window_id)
            if window is None:
                raise ValidationError(
                    f"No observation window exists with window_id={window_id}.",
                    details={"window_id": window_id},
                )
            return window

        window = self._window_repository.get_active()
        if window is None:
            raise ValidationError(
                "No observation window is currently ACTIVE, and no window_id "
                "was supplied explicitly.",
                details={},
            )
        return window

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- public API: evidence-linked review record --------------------------

    def load_final_review(self, *, window_id: Optional[int] = None) -> Optional[FinalReviewRecord]:
        """Read-only: return the existing :class:`FinalReviewRecord` for
        the resolved window, or ``None`` if one has never been
        created (i.e. :meth:`refresh_review` / :meth:`record_feedback`
        / :meth:`record_decision` has never run for this window).

        Never writes anything, never calls ``SustainedUseReviewService``.
        Intended for a purely read-only reporting surface (e.g.
        ``python main.py report sustained-use-final``) that must not
        silently create a row as a side effect of being viewed.

        Raises:
            ValidationError: If ``window_id`` was supplied but no such
                window exists, or if ``window_id`` was omitted and no
                window is currently ``ACTIVE``.
        """
        window = self._resolve_window(window_id)
        return self._record_repository.get_by_window(window.window_id)

    def refresh_review(
        self,
        *,
        window_id: Optional[int] = None,
        account_id: Optional[str] = None,
        starting_cash: Optional[float] = None,
    ) -> FinalReviewRecord:
        """Create/update the :class:`FinalReviewRecord` for the
        resolved window from real, freshly-computed evidence and
        real, already-persisted operator feedback.

        Steps (exactly as the Phase H Task 4 roadmap requires):

            1. Load the selected observation window
               (:meth:`_resolve_window`).
            2. Load the latest sustained-use evidence result
               (``SustainedUseReviewService.generate_review`` --
               Task 2, unmodified).
            3. Load operator feedback linked to this window
               (``OperatorFeedbackRepository.list_by_window`` --
               this task).
            4. Create the row if none exists yet (``human_decision``
               starts ``"PENDING"``), or update the existing row's
               evidence-derived columns in place, in either case
               NEVER touching an already-recorded ``human_decision``/
               ``decision_note``/``decided_at``/``decided_by`` (see
               ``FinalReviewRecordRepository.update_evidence``).

        Args:
            window_id: The window to review. Omitted -> the single
                currently ``ACTIVE`` window.
            account_id: Passed through unchanged to
                ``SustainedUseReviewService.generate_review`` --
                optional, scopes account-level evidence dimensions.
            starting_cash: Passed through unchanged to
                ``SustainedUseReviewService.generate_review``.

        Returns:
            The created-or-updated :class:`FinalReviewRecord`.

        Raises:
            ValidationError: If the window cannot be resolved (see
                :meth:`_resolve_window`).
        """
        window = self._resolve_window(window_id)
        review_result = self._review_service.generate_review(
            window_id=window.window_id, account_id=account_id, starting_cash=starting_cash
        )
        return self._refresh_record(window, review_result)

    def _refresh_record(
        self, window: ObservationWindow, review_result: SustainedUseReviewResult
    ) -> FinalReviewRecord:
        feedback_rows = self._feedback_repository.list_by_window(window.window_id)
        feedback_ids_json = json.dumps([row.feedback_id for row in feedback_rows])
        limitations_json = _known_limitations_to_json(review_result)

        existing = self._record_repository.get_by_window(window.window_id)
        now = self._now()
        if existing is None:
            return self._record_repository.create(
                observation_window_id=window.window_id,
                reviewed_at=review_result.generated_at,
                evidence_status=review_result.overall_evidence_status,
                known_limitations=limitations_json,
                operator_feedback_ids=feedback_ids_json,
                created_at=now,
            )
        updated = self._record_repository.update_evidence(
            window.window_id,
            reviewed_at=review_result.generated_at,
            evidence_status=review_result.overall_evidence_status,
            known_limitations=limitations_json,
            operator_feedback_ids=feedback_ids_json,
            updated_at=now,
        )
        assert updated is not None  # existing was just read above
        return updated

    # -- public API: operator feedback ---------------------------------------

    def record_feedback(
        self,
        *,
        window_id: Optional[int] = None,
        operator_rating: Optional[int] = None,
        alert_usefulness: Optional[str] = None,
        data_reliability_feedback: Optional[str] = None,
        decision_quality_feedback: Optional[str] = None,
        workflow_usability_feedback: Optional[str] = None,
        free_text: Optional[str] = None,
        concerns: Optional[Sequence[str]] = None,
        operator_label: Optional[str] = None,
    ) -> OperatorFeedback:
        """Persist one real, explicitly-given piece of operator
        feedback for the resolved window, then refresh that window's
        :class:`FinalReviewRecord` so its ``operator_feedback_ids``
        link stays current (never touching ``human_decision``).

        Every argument is optional except that at least implicitly the
        caller is expected to supply something meaningful -- this
        method does not require any single field, mirroring how real
        operators may only have time to fill in a rating, or only a
        free-text comment, on a given day. Nothing here is inferred:
        a field left ``None`` is stored as ``None``/omitted, never
        defaulted to a guessed value.

        Args:
            window_id: The window this feedback concerns. Omitted ->
                the single currently ``ACTIVE`` window.
            operator_rating: Optional overall usefulness rating,
                exactly as given.
            alert_usefulness: Optional free-text/label feedback.
            data_reliability_feedback: Optional free-text/label
                feedback.
            decision_quality_feedback: Optional free-text/label
                feedback.
            workflow_usability_feedback: Optional free-text/label
                feedback.
            free_text: Optional open-ended comment.
            concerns: Optional sequence of operator-selected concern/
                limitation labels.
            operator_label: Optional operator identifier/label.

        Returns:
            The newly persisted :class:`OperatorFeedback`.

        Raises:
            ValidationError: If the window cannot be resolved.
        """
        window = self._resolve_window(window_id)
        feedback = self._feedback_repository.create(
            observation_window_id=window.window_id,
            recorded_at=self._now(),
            operator_rating=operator_rating,
            alert_usefulness=alert_usefulness,
            data_reliability_feedback=data_reliability_feedback,
            decision_quality_feedback=decision_quality_feedback,
            workflow_usability_feedback=workflow_usability_feedback,
            free_text=free_text,
            concerns=concerns,
            operator_label=operator_label,
        )

        # Keep the final review record's linked-feedback list current.
        # Uses no account_id/starting_cash here (feedback recording is
        # not account-scoped) -- account-level evidence dimensions
        # simply read NOT_AVAILABLE, exactly as SustainedUseReviewService
        # already honestly reports them when no account is supplied.
        review_result = self._review_service.generate_review(window_id=window.window_id)
        self._refresh_record(window, review_result)

        return feedback

    def list_feedback(self, *, window_id: Optional[int] = None) -> List[OperatorFeedback]:
        """Read-only: every operator feedback row recorded for the
        resolved window, oldest first.

        Raises:
            ValidationError: If the window cannot be resolved.
        """
        window = self._resolve_window(window_id)
        return self._feedback_repository.list_by_window(window.window_id)

    # -- public API: the one deliberate human decision -----------------------

    def record_decision(
        self,
        *,
        human_decision: str,
        window_id: Optional[int] = None,
        decision_note: Optional[str] = None,
        decided_by: Optional[str] = None,
        account_id: Optional[str] = None,
        starting_cash: Optional[float] = None,
    ) -> FinalReviewRecord:
        """Record ONE explicit, human-supplied decision on the
        resolved window's :class:`FinalReviewRecord`.

        ``human_decision`` has NO default value in this signature --
        a caller must supply it explicitly every time. This method
        never infers, scores, or recommends a decision; it only ever
        validates and persists exactly the value it was given.

        Evidence is refreshed (via :meth:`refresh_review`'s own logic)
        before the decision is evaluated/recorded, so the
        insufficiency check below always runs against the real,
        current state of the window -- never a stale snapshot.

        Args:
            human_decision: One of ``"PENDING"`` / ``"CONTINUE"`` /
                ``"SIMPLIFY"`` / ``"AUTHORIZE_FUTURE_INVESTIGATION"``
                (see ``Database.models.FINAL_REVIEW_DECISION_*``).
            window_id: The window this decision concerns. Omitted ->
                the single currently ``ACTIVE`` window.
            decision_note: Optional free-text human rationale.
            decided_by: Optional human/operator identifier or label.
            account_id: Passed through unchanged to
                ``SustainedUseReviewService.generate_review`` for the
                evidence refresh this call performs.
            starting_cash: Passed through unchanged to
                ``SustainedUseReviewService.generate_review``.

        Returns:
            The updated :class:`FinalReviewRecord`.

        Raises:
            ValidationError: If ``human_decision`` is not one of the
                four allowed values, if the window cannot be resolved,
                or if ``human_decision`` is CONTINUE/SIMPLIFY/
                AUTHORIZE_FUTURE_INVESTIGATION while this window's
                evidence is insufficient (see module docstring for the
                exact, derived-not-fabricated condition used).
        """
        if human_decision not in ALLOWED_DECISIONS:
            raise ValidationError(
                f"Unknown human_decision {human_decision!r} -- expected one of "
                f"{sorted(ALLOWED_DECISIONS)}. This service never infers a decision; "
                "the caller must supply one of these exact values explicitly.",
                details={"human_decision": human_decision, "allowed": sorted(ALLOWED_DECISIONS)},
            )

        window = self._resolve_window(window_id)
        review_result = self._review_service.generate_review(
            window_id=window.window_id, account_id=account_id, starting_cash=starting_cash
        )

        if human_decision in _DECISIONS_REQUIRING_SUFFICIENT_EVIDENCE:
            if review_result.availability.scheduled_job_count == 0:
                raise ValidationError(
                    f"Cannot record human_decision={human_decision!r} for "
                    f"window_id={window.window_id}: this window's real evidence is "
                    "insufficient for a final decision (availability.scheduled_job_count "
                    "== 0 -- no scheduler job runs have been recorded in this window "
                    "yet). Record human_decision='PENDING' instead, or wait until real "
                    "operating records accrue.",
                    details={
                        "window_id": window.window_id,
                        "human_decision": human_decision,
                        "scheduled_job_count": review_result.availability.scheduled_job_count,
                    },
                )

        # Ensure the row exists and its evidence-derived columns are
        # current before writing the decision on top of it.
        self._refresh_record(window, review_result)

        now = self._now()
        if human_decision == FINAL_REVIEW_DECISION_PENDING:
            decided_at_value: Optional[str] = None
            decided_by_value: Optional[str] = None
            decision_note_value: Optional[str] = None
        else:
            decided_at_value = now
            decided_by_value = decided_by
            decision_note_value = decision_note

        updated = self._record_repository.record_decision(
            window.window_id,
            human_decision=human_decision,
            decision_note=decision_note_value,
            decided_at=decided_at_value,
            decided_by=decided_by_value,
            updated_at=now,
        )
        assert updated is not None  # _refresh_record just guaranteed the row exists
        return updated