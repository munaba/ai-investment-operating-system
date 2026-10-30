from __future__ import annotations

import inspect
import random
import time
from typing import Any, Callable, TypeVar

from Core.exceptions import RepositoryError
from Repository.base_repository import BaseRepository

_T = TypeVar("_T")


def _status_code(exc: BaseException) -> int | None:
    """Extract HTTP status code from an exception, if any."""
    import urllib.error  # noqa: PLC0415

    for obj in (getattr(exc, "response", None), exc):
        code = getattr(obj, "status_code", None)
        if isinstance(code, int):
            return code
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return None


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
        """Return True only for transient network/timeout errors.

        Check order matters:
        1. HTTP status code — wins over type (a 404 HTTPError is permanent).
        2. Permanent OS error subclasses — excluded before the broad type check.
        3. urllib.error.URLError — unwrap .reason and recurse.
        4. Known transient type families.
        5. OSError with a transient errno (e.g. ENETUNREACH).
        """
        import errno  # noqa: PLC0415
        import http.client  # noqa: PLC0415
        import socket  # noqa: PLC0415
        import urllib.error  # noqa: PLC0415

        _PERMANENT_OS_ERRORS = (  # noqa: N806
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
            NotADirectoryError,
            FileExistsError,
        )
        _TRANSIENT_TYPES = (  # noqa: N806
            TimeoutError,
            ConnectionError,
            socket.timeout,
            socket.gaierror,
            http.client.RemoteDisconnected,
        )
        _TRANSIENT_ERRNOS = {  # noqa: N806
            errno.ENETUNREACH,
            errno.EHOSTUNREACH,
            errno.ENETDOWN,
            errno.ETIMEDOUT,
        }

        # ── 1. HTTP status code takes precedence ──
        status = _status_code(exc)
        if status is not None:
            return status in (408, 429) or 500 <= status <= 599

        # ── 2. Permanent OS error subclasses are never transient ──
        if isinstance(exc, _PERMANENT_OS_ERRORS):
            return False

        # ── 3. URLError: unwrap .reason and recurse ──
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, BaseException):
                return BaseExternalRepository._is_transient(reason)
            return False

        # ── 4. Known transient types ──
        if isinstance(exc, _TRANSIENT_TYPES):
            return True

        # ── 5. OSError with transient errno ──
        if isinstance(exc, OSError) and exc.errno in _TRANSIENT_ERRNOS:
            return True

        return False
