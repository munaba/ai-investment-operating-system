from __future__ import annotations

from typing import Any, Callable, TypeVar

from Core.exceptions import RepositoryError
from Repository.base_repository import BaseRepository

_T = TypeVar("_T")


class BaseExternalRepository(BaseRepository):
    """Contract shared by every repository backed by an external data provider.

    Concrete external repositories (e.g. a future ``StockDataRepository``
    wrapping ``yfinance``) receive their client/SDK module via constructor
    injection and never hard-code which provider they talk to at this
    layer -- this base class has no knowledge of ``yfinance`` or any other
    specific provider.

    Provides one protected helper, ``_call``, which invokes a
    provider-specific callable and translates whatever it raises into a
    ``RepositoryError`` (preserving the original exception via
    ``from exc``/``__cause__``). No ``get_history()``, ``fetch()``, or
    other generic/domain-shaped method is provided here -- concrete
    repositories define their own methods and call through ``_call``.

    ``health_check()`` is intentionally left abstract (inherited from
    ``BaseRepository``, not implemented here): each external provider has
    its own notion of "reachable" (e.g. a lightweight ping vs. a minimal
    real request), so there is no single default that fits all of them.
    """

    def __init__(self, client: Any) -> None:
        """Initialize with the external client/SDK module to use, via constructor injection.

        Args:
            client: The provider-specific client/module this repository
                calls through (e.g. a ``yfinance``-compatible module).
                Intentionally untyped beyond ``Any`` -- this base class
                does not know or care which provider it is.
        """
        self._client = client

    def _call(self, func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        """Invoke a provider-specific callable, translating failures.

        Args:
            func: The callable to invoke (typically a method/attribute of
                ``self._client``).
            *args: Positional arguments passed through to ``func``.
            **kwargs: Keyword arguments passed through to ``func``.

        Returns:
            Whatever ``func`` returns, unchanged.

        Raises:
            RepositoryError: If ``func`` raises. The original exception is
                preserved as ``__cause__``.
        """
        try:
            return func(*args, **kwargs)
        except RepositoryError:
            # Already translated (e.g. by a nested repository call) -- do not
            # wrap a RepositoryError inside another RepositoryError.
            raise
        except Exception as exc:  # noqa: BLE001 - normalize any provider/SDK failure
            raise RepositoryError(
                f"External call failed: {getattr(func, '__name__', func)!r}",
                details={"error": str(exc)},
            ) from exc