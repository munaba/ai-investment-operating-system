"""ObservationWindowRepository -- Phase H Task 1 ("Observation Window +
Sustained-Use Review Record").

PERSISTENCE ONLY, mirroring ``DecisionBriefRepository``: stores and
retrieves exactly what ``Services.observation_window_service.
ObservationWindowService`` supplies. Never decides whether opening a
new window is allowed while another is already active, never validates
a date range, never selects a window automatically -- those are the
service's job, one layer up. This repository only records what the
operator already decided.

Append-only rows (one per ``open``, never overwritten), plus one
in-place transition per row (``ACTIVE`` -> ``CLOSED`` on ``close``).
Restart-safe: a saved row survives a fresh repository instance over
the same on-disk database file, exactly like every other persistence
repository in this codebase.
"""

from __future__ import annotations

from typing import List, Optional

from Database.models import ObservationWindow
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: Status values a ``operator_observation_windows`` row may hold. Not a
#: Python ``Enum`` -- mirrors ``SchedulerStateRepository``'s plain
#: string constant convention.
STATUS_ACTIVE: str = "ACTIVE"
STATUS_CLOSED: str = "CLOSED"


class ObservationWindowRepository(BasePersistenceRepository):
    """Persists and retrieves ``operator_observation_windows`` rows."""

    def create(
        self,
        *,
        start_at: str,
        end_at: str,
        timezone: str,
        created_at: str,
        note: Optional[str] = None,
    ) -> ObservationWindow:
        """Insert a new window row with ``status="ACTIVE"``.

        ``window_id`` is repository-generated (autoincrement), never
        caller-supplied -- mirrors ``DecisionBriefRepository.create``.
        Does not check whether another ``ACTIVE`` row already exists;
        that gate belongs to ``ObservationWindowService.open``, which
        calls :meth:`get_active` first.

        Args:
            start_at: Operator-supplied start date/time, exactly as
                given.
            end_at: Operator-supplied end date/time, exactly as given.
            timezone: The timezone ``start_at``/``end_at`` are
                expressed in, exactly as given.
            created_at: ISO-8601 UTC timestamp of this call. Required,
                caller-supplied -- this repository does not
                auto-generate it.
            note: Optional free-text operator label.

        Returns:
            The newly persisted :class:`Database.models.ObservationWindow`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            INSERT INTO operator_observation_windows
                (start_at, end_at, timezone, note, status, created_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (start_at, end_at, timezone, note, STATUS_ACTIVE, created_at),
        )
        window_id = result.lastrowid
        return ObservationWindow(
            window_id=window_id,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            note=note,
            status=STATUS_ACTIVE,
            created_at=created_at,
            closed_at=None,
        )

    def get_by_id(self, window_id: int) -> Optional[ObservationWindow]:
        """Return the exact row for ``window_id``, or ``None``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM operator_observation_windows WHERE window_id = ?",
            (window_id,),
        )
        return self._row_to_window(result.rows[0]) if result.rows else None

    def get_active(self) -> Optional[ObservationWindow]:
        """Return the single ``ACTIVE`` window, or ``None`` if none is
        currently open.

        At most one row is ever ``ACTIVE`` (enforced by
        ``ObservationWindowService.open``, not this query) -- if more
        than one somehow exists, the most recently created is
        returned, never silently averaged or merged.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM operator_observation_windows "
            "WHERE status = ? ORDER BY window_id DESC LIMIT 1",
            (STATUS_ACTIVE,),
        )
        return self._row_to_window(result.rows[0]) if result.rows else None

    def close(self, window_id: int, *, closed_at: str) -> Optional[ObservationWindow]:
        """Transition ``window_id`` from ``ACTIVE`` to ``CLOSED`` in
        place, preserving every other column (including ``created_at``,
        ``start_at``, ``end_at``, ``timezone``) unchanged.

        Args:
            window_id: The window to close.
            closed_at: ISO-8601 UTC timestamp of this close. Required,
                caller-supplied.

        Returns:
            The updated :class:`Database.models.ObservationWindow`, or
            ``None`` if no row exists with ``window_id``. Does not
            check whether the row was already ``ACTIVE`` -- that check
            belongs to ``ObservationWindowService.close``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        existing = self.get_by_id(window_id)
        if existing is None:
            return None
        self._execute(
            "UPDATE operator_observation_windows SET status = ?, closed_at = ? WHERE window_id = ?",
            (STATUS_CLOSED, closed_at, window_id),
        )
        return self.get_by_id(window_id)

    def list_all(self) -> List[ObservationWindow]:
        """Return every window ever recorded, ordered by ``window_id``
        ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM operator_observation_windows ORDER BY window_id ASC")
        return [self._row_to_window(row) for row in result.rows]

    @staticmethod
    def _row_to_window(row) -> ObservationWindow:
        return ObservationWindow(
            window_id=row["window_id"],
            start_at=row["start_at"],
            end_at=row["end_at"],
            timezone=row["timezone"],
            note=row["note"],
            status=row["status"],
            created_at=row["created_at"],
            closed_at=row["closed_at"],
        )
