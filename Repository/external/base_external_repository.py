from __future__ import annotations

import inspect
import random
import time
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

    def _call(
        self,
        func: Callable[..., _T],
        *args: Any,
        timeout: float | None = 30.0,
        max_attempts: int = 3,
        backoff_base: float = 2.0,
        **kwargs: Any,
    ) -> _T:
        """Invoke a provider-specific callable with timeout and retry.

        Args:
            func: The callable to invoke (typically a method/attribute of
                ``self._client``).
            *args: Positional arguments passed through to ``func``.
            timeout: Optional timeout in seconds to pass to underlying client
                (if the client supports a ``timeout`` kwarg). Default 30.
            max_attempts: Maximum number of attempts before raising.
                Default 3 (original + 2 retries).
            backoff_base: Base for exponential backoff: delay = backoff_base ** (attempt - 1)
                with jitter ``* (1 + uniform(0, 0.3))`` added before sleep.
                Default 2.0 (1s, ~2.3s, ~4.6s with jitter on retry sleeps).
            **kwargs: Keyword arguments passed through to ``func``, updated with
                ``timeout`` if not already present and the client signature expects it.

        Returns:
            Whatever ``func`` returns, unchanged.

        Raises:
            RepositoryError: If ``func`` raises after exhausting retries.
                The original exception is preserved as ``__cause__``.
        """
        # If client signature expects a `timeout` kwarg, inject it unless already given
        sig = inspect.signature(func)
        if "timeout" in sig.parameters and "timeout" not in kwargs and timeout is not None:
            kwargs["timeout"] = timeout

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                backoff = backoff_base ** (attempt - 1)
                jitter = 1.0 + random.uniform(0.0, 0.3)
                time.sleep(backoff * jitter)

            try:
                return func(*args, **kwargs)
            except RepositoryError:
                # Already translated (e.g. by a nested repository call) -- do not
                # wrap a RepositoryError inside another RepositoryError.
                raise
            except Exception as exc:  # noqa: BLE001 - normalize any provider/SDK failure
                last_exc = exc
                if attempt == max_attempts - 1:
                    break

        raise RepositoryError(
            f"External call failed after {max_attempts} attempts: {getattr(func, '__name__', func)!r}",
            details={"error": str(last_exc)},
        ) from last_exc