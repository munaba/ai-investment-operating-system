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

        Only transient network/timeout errors are retried. Everything else
        (ValueError, TypeError, KeyError, AttributeError, NotImplementedError,
        RuntimeError, etc.) is raised immediately as a permanent failure.
        """
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
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

                if not self._is_transient(exc):
                    raise RepositoryError(
                        f"External call failed permanently: {getattr(func, "__name__", func)!r}",
                        details={"error": str(exc)},
                    ) from exc

                if attempt == max_attempts - 1:
                    break

        raise RepositoryError(
            f"External call failed after {max_attempts} attempts: {getattr(func, "__name__", func)!r}",
            details={"error": str(last_exc)},
        ) from last_exc

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """Return True only for transient network/timeout errors."""
        import http.client  # noqa: PLC0415
        import socket  # noqa: PLC0415
        import urllib.error  # noqa: PLC0415

        transient_types = (
            TimeoutError,
            ConnectionError,
            ConnectionResetError,
            ConnectionAbortedError,
            ConnectionRefusedError,
            BrokenPipeError,
            OSError,
            socket.timeout,
            http.client.RemoteDisconnected,
            urllib.error.URLError,
        )
        if isinstance(exc, transient_types):
            return True

        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        if isinstance(status, int) and (status == 429 or 500 <= status <= 599):
            return True

        msg = str(exc).lower()
        return any(
            phrase in msg
            for phrase in (
                "timed out",
                "connection reset",
                "connection refused",
                "connection aborted",
                "broken pipe",
                "remote disconnect",
                "urlopen error",
                "http 5",
                "http 429",
            )
        )
