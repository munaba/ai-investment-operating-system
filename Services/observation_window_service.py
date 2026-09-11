"""``ObservationWindowService`` -- Phase H Task 1 ("Observation Window
+ Sustained-Use Review Record").

Lets an operator explicitly select a stretch of time to review real
operating records over -- the necessary first step before Phase H's
eventual written evidence review and continue/simplify/authorize
decision. This service invents nothing about *when* that window
should be: it never picks a period automatically, never infers a
"good" window from data, and never reads any trading table (journal,
paper review, portfolio snapshots, scheduler/Telegram audit) itself.
It persists only the operator's own explicit selection, via
``Repository.persistence.observation_window_repository.
ObservationWindowRepository``.

This service holds no reference to ``PaperTradingEngine``/
``OrderLifecycleService``/``ExecutionService``/any risk-policy
component and calls none of them -- opening, reading, or closing an
observation window never creates a paper order, a ``Trade``, a
``Position``, or modifies any risk limit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Database.models import ObservationWindow
from Repository.persistence.observation_window_repository import (
    STATUS_ACTIVE,
    ObservationWindowRepository,
)


class ObservationWindowService:
    """Orchestrates one open/read/close request against
    ``ObservationWindowRepository``.

    Constructor injection only, mirroring ``JournalService``:
    ``window_repository`` is this service's sole collaborator.
    Stateless beyond it -- safe to reuse across calls.
    """

    def __init__(self, window_repository: ObservationWindowRepository) -> None:
        self._window_repository = window_repository

    def open(
        self,
        *,
        start_at: str,
        end_at: str,
        timezone_name: str,
        note: Optional[str] = None,
    ) -> ObservationWindow:
        """Open a new observation window, explicitly selected by the
        operator.

        Never inferred: ``start_at``/``end_at``/``timezone_name`` are
        exactly the values the operator supplied, persisted verbatim.

        Args:
            start_at: Operator-supplied start date/time (ISO-8601,
                e.g. ``"2026-08-01T00:00:00"``).
            end_at: Operator-supplied end date/time (ISO-8601), must be
                strictly after ``start_at``.
            timezone_name: The timezone ``start_at``/``end_at`` are
                expressed in (e.g. ``"Asia/Jakarta"``). Required,
                non-empty -- never defaulted or guessed.
            note: Optional free-text operator label for this window.

        Returns:
            The newly persisted, ``ACTIVE`` :class:`Database.models.ObservationWindow`.

        Raises:
            ValueError: If ``timezone_name`` is empty, if ``start_at``/
                ``end_at`` cannot be parsed as ISO-8601 date/times, if
                ``end_at`` is not strictly after ``start_at``, or if
                another window is already ``ACTIVE`` -- a second
                window may not be opened while one is open; the
                operator must close it first (deterministic rejection,
                never an automatic close/replace).
            RepositoryError: If the underlying statement fails.
        """
        if not timezone_name or not timezone_name.strip():
            raise ValueError("timezone_name is required and must be non-empty.")

        start_dt = self._parse_datetime(start_at, "start_at")
        end_dt = self._parse_datetime(end_at, "end_at")
        if end_dt <= start_dt:
            raise ValueError(f"end_at ({end_at!r}) must be strictly after start_at ({start_at!r}).")

        existing_active = self._window_repository.get_active()
        if existing_active is not None:
            raise ValueError(
                f"An observation window is already ACTIVE (window_id={existing_active.window_id}, "
                f"opened {existing_active.created_at}). Close it explicitly before opening another."
            )

        created_at = datetime.now(timezone.utc).isoformat()
        return self._window_repository.create(
            start_at=start_at,
            end_at=end_at,
            timezone=timezone_name,
            created_at=created_at,
            note=note,
        )

    def get_current(self) -> Optional[ObservationWindow]:
        """Read-only: return the single currently ``ACTIVE`` window, or
        ``None`` if no window is open.

        Never selects or infers a window -- returns exactly whatever
        the operator most recently opened and has not yet closed.
        """
        return self._window_repository.get_active()

    def close(self, window_id: Optional[int] = None) -> ObservationWindow:
        """Explicitly close an observation window.

        Args:
            window_id: The window to close. If omitted, closes the
                single currently ``ACTIVE`` window.

        Returns:
            The updated, ``CLOSED`` :class:`Database.models.ObservationWindow`.
            Original ``start_at``/``end_at``/``timezone``/``created_at``
            are preserved unchanged.

        Raises:
            ValueError: If ``window_id`` was omitted and no window is
                currently ``ACTIVE``; if ``window_id`` was supplied but
                no such window exists; or if the window identified is
                not currently ``ACTIVE`` (already closed).
            RepositoryError: If the underlying statement fails.
        """
        if window_id is None:
            active = self._window_repository.get_active()
            if active is None:
                raise ValueError("No observation window is currently ACTIVE to close.")
            window_id = active.window_id

        target = self._window_repository.get_by_id(window_id)
        if target is None:
            raise ValueError(f"No observation window exists with window_id={window_id}.")
        if target.status != STATUS_ACTIVE:
            raise ValueError(f"Observation window {window_id} is already {target.status}, not ACTIVE.")

        closed_at = datetime.now(timezone.utc).isoformat()
        updated = self._window_repository.close(window_id, closed_at=closed_at)
        assert updated is not None  # existence just confirmed above; no concurrent delete path exists
        return updated

    def list_all(self) -> List[ObservationWindow]:
        """Read-only: every window ever recorded, oldest first."""
        return self._window_repository.list_all()

    @staticmethod
    def _parse_datetime(value: str, field_name: str) -> datetime:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid ISO-8601 date/time, got {value!r}.") from exc
