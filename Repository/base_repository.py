from __future__ import annotations

from abc import ABC, abstractmethod


class BaseRepository(ABC):
    """Contract shared by every repository implementation.

    Mirrors the shape of ``Providers.BaseProvider``, ``Services.BaseService``,
    and ``Database.base_database.BaseDatabase`` in this framework: callers
    depend only on this interface, never on a concrete repository.

    Repositories only fetch/persist data -- they do not implement business
    logic, do not perform domain transformation, and do not return
    ``Services.ServiceResult``. Provider/database-specific exceptions are
    translated into ``Core.exceptions.RepositoryError`` before propagating
    to callers.

    This base is deliberately minimal: only the contract that is true of
    *every* repository, regardless of whether it talks to a database or an
    external API, belongs here. Anything specific to one kind of repository
    (e.g. transactions for persistence, provider modules for external data)
    belongs on the more specific base class instead.
    """

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether this repository is currently able to serve requests.

        Implementations should never raise -- any failure should be caught
        internally and reflected as a ``False`` return value, mirroring
        ``BaseProvider.health_check()``, ``BaseService.health_check()``, and
        ``BaseDatabase.health_check()``.

        Returns:
            ``True`` if the repository is healthy, ``False`` otherwise.
        """
        raise NotImplementedError