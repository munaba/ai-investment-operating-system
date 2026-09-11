from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional
from Core.config import config
from Core.exceptions import ProviderError
from Core.logger import get_logger
from .base_provider import BaseProvider
from .capabilities import ProviderCapabilities
from .message import Message, MessageRole
from .response import ProviderResponse, Usage

logger = get_logger(__name__)

#: Stage L2 addition -- static capability metadata, declared once here
#: rather than checked via provider-name comparisons elsewhere. Mirrors
#: this implementation's actual Stage L1 scope: stream() and
#: count_tokens() both still raise NotImplementedError (see below), and
#: model-dependent limits (context/output window, tool support) vary
#: per locally-installed model, so they are left unknown (None/False)
#: rather than guessed.
#: Stage L3 addition: is_local=True -- OllamaProvider is designed to
#: talk to a self-hosted Ollama server (OLLAMA_HOST, typically
#: localhost), not a remote cloud API. Declared based on what this
#: provider connects to, not a live reachability check.
_OLLAMA_CAPABILITIES = ProviderCapabilities(
    supports_stream=False,
    supports_tools=False,
    supports_json=False,
    supports_images=False,
    supports_reasoning=False,
    supports_embeddings=False,
    max_context_tokens=None,
    max_output_tokens=None,
    is_local=True,
)

_ROLE_MAP: Dict[MessageRole, str] = {
    MessageRole.SYSTEM: "system",
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
    MessageRole.TOOL: "user",
}

_DEFAULT_TIMEOUT_SECONDS: float = 300.0


class OllamaProvider(BaseProvider):
    """Local AI provider backed by a running Ollama server's HTTP API.

    Stage L1 scope: ``generate()`` and ``health_check()`` only.
    ``stream()`` and ``count_tokens()`` intentionally raise
    ``NotImplementedError`` in this stage -- see their docstrings.

    Attributes:
        model: The Ollama model name used for requests (read from
            ``OLLAMA_MODEL`` in configuration unless overridden).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        """Initialize the provider without connecting yet.

        Args:
            host: Base URL of the Ollama server (e.g. ``http://localhost:11434``).
                Defaults to ``config.get("OLLAMA_HOST")``.
            model: Ollama model name. Defaults to ``config.get("OLLAMA_MODEL")``.
            timeout: Per-request timeout in seconds. Defaults to
                ``config.get_float("OLLAMA_TIMEOUT", 300.0)``.
            http_client: Optional pre-configured HTTP client (or a test
                double) exposing ``.post``/``.get``, same injection pattern
                as ``Services.notification_service.NotificationService``.
                When omitted, ``requests`` is lazily imported on
                :meth:`connect`.
        """
        super().__init__()
        self._host: Optional[str] = host or config.get("OLLAMA_HOST")
        self.model: Optional[str] = model or config.get("OLLAMA_MODEL")
        self._timeout: float = (
            timeout if timeout is not None else config.get_float("OLLAMA_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)
        )
        self._http_client: Optional[Any] = http_client
        self._client: Any = None
        self._connected: bool = False

    @property
    def name(self) -> str:
        """Return this provider's identifier.

        Returns:
            The string ``"ollama"``.
        """
        return "ollama"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return this provider's static capability metadata.

        See module-level ``_OLLAMA_CAPABILITIES`` for the declared
        values and the reasoning behind each one.

        Returns:
            This provider's :class:`ProviderCapabilities`.
        """
        return _OLLAMA_CAPABILITIES

    def _get_http_client(self) -> Any:
        """Resolve the HTTP client, injected or lazily imported.

        Returns:
            The injected client if one was provided at construction time,
            otherwise the freshly (lazily) imported ``requests`` module.

        Raises:
            ProviderError: If no client was injected and ``requests`` is
                not installed.
        """
        if self._http_client is not None:
            return self._http_client
        try:
            import requests
        except ImportError as exc:
            raise ProviderError(
                "requests is not installed. Install it with 'pip install requests'."
            ) from exc
        return requests

    def connect(self) -> None:
        """Resolve the HTTP client and validate configuration.

        Idempotent: does nothing if already connected. Performs no
        network I/O -- only resolves the client and checks that
        ``OLLAMA_HOST``/``OLLAMA_MODEL`` are configured, mirroring
        ``GeminiProvider.connect()``'s construct-only contract.

        Raises:
            ProviderError: If ``OLLAMA_HOST``/``OLLAMA_MODEL`` are not
                configured, or ``requests`` is not installed and no
                ``http_client`` was injected.
        """
        if self._connected:
            return

        if not self._host:
            raise ProviderError(
                "OLLAMA_HOST is not configured. Set it in your .env file."
            )
        if not self.model:
            raise ProviderError(
                "OLLAMA_MODEL is not configured. Set it in your .env file."
            )

        self._client = self._get_http_client()
        self._connected = True
        logger.debug(f"OllamaProvider connected using model '{self.model}' at '{self._host}'")

    def disconnect(self) -> None:
        """Release the resolved HTTP client, if any."""
        self._client = None
        self._connected = False
        logger.debug("OllamaProvider disconnected")

    def _ensure_connected(self) -> None:
        """Connect lazily if this provider has not been connected yet.

        Raises:
            ProviderError: If connecting fails (see :meth:`connect`).
        """
        if not self._connected:
            self.connect()

    def _to_ollama_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert provider-agnostic messages into Ollama chat messages.

        Args:
            messages: The conversation history to convert.

        Returns:
            A list of ``{"role": ..., "content": ...}`` dicts for the
            Ollama ``/api/chat`` endpoint.
        """
        return [
            {"role": _ROLE_MAP.get(message.role, "user"), "content": message.content}
            for message in messages
        ]

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        """Generate a complete response using Ollama's ``/api/chat`` endpoint.

        Args:
            messages: The conversation history to generate a reply for.
            **kwargs: Optional generation options: ``temperature`` (float),
                ``max_output_tokens`` (int, mapped to Ollama's
                ``num_predict`` option).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If ``messages`` is empty, or the request to
                Ollama fails.
        """
        self._ensure_connected()
        if not messages:
            raise ProviderError("Cannot generate a response from an empty message list")

        ollama_messages = self._to_ollama_messages(messages)

        options: Dict[str, Any] = {}
        if "temperature" in kwargs:
            options["temperature"] = kwargs["temperature"]
        if "max_output_tokens" in kwargs:
            options["num_predict"] = kwargs["max_output_tokens"]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        try:
            response = self._client.post(
                f"{self._host}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:  
            raise ProviderError("Ollama /api/chat request failed", details={"error": str(exc)}) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Convert a raw ``/api/chat`` HTTP response into a normalized
        ``ProviderResponse``.

        Args:
            response: The raw HTTP response object (``requests``-compatible:
                exposes ``.status_code``/``.json()``/``.text``).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If the HTTP status indicates failure, or the
                response body cannot be parsed as JSON.
        """
        status_code = getattr(response, "status_code", None)
        if status_code is not None and status_code != 200:
            raise ProviderError(
                "Ollama /api/chat returned a non-200 status",
                details={"status_code": status_code, "body": getattr(response, "text", "")},
            )

        try:
            body = response.json()
        except Exception as exc:  
            raise ProviderError("Ollama /api/chat returned a non-JSON response", details={"error": str(exc)}) from exc

        message = body.get("message", {}) or {}
        text = message.get("content", "") or ""

        usage = Usage(
            input_tokens=int(body.get("prompt_eval_count", 0) or 0),
            output_tokens=int(body.get("eval_count", 0) or 0),
            total_tokens=int(body.get("prompt_eval_count", 0) or 0) + int(body.get("eval_count", 0) or 0),
        )

        finish_reason = body.get("done_reason")

        return ProviderResponse(
            text=text,
            finish_reason=finish_reason,
            model=body.get("model") or self.model or "",
            usage=usage,
            raw_response=body,
            metadata={},
        )

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        """Streaming is not implemented in Stage L1.

        Ollama's ``/api/chat`` supports ``"stream": true`` with
        newline-delimited JSON chunks; wiring that up is deferred to a
        future stage, as permitted by the provider framework's
        requirements (same deferral ``GeminiProvider.stream()`` makes).

        Raises:
            NotImplementedError: Always, in this version.
        """
        raise NotImplementedError(
            "OllamaProvider.stream() is not implemented in Stage L1. "
            "The Ollama /api/chat endpoint supports stream=true; "
            "this will be wired up in a future update."
        )

    def count_tokens(self, messages: List[Message]) -> int:
        """Token counting is not implemented in Stage L1.

        Ollama does not expose a dedicated token-counting endpoint;
        ``prompt_eval_count``/``eval_count`` are only available after a
        real ``/api/chat`` call (see :meth:`generate`). Deferred to a
        future stage rather than approximated here.

        Raises:
            NotImplementedError: Always, in this version.
        """
        raise NotImplementedError(
            "OllamaProvider.count_tokens() is not implemented in Stage L1."
        )

    def health_check(self) -> bool:
        """Check whether the Ollama server is reachable via ``/api/tags``.

        Never raises: any failure is caught, logged, and reported as
        ``False``. Records latency and (on failure) the error message via
        :meth:`BaseProvider._record_health_check`, retrievable afterwards
        through :attr:`last_health_check`.

        Returns:
            ``True`` if Ollama responded successfully to ``/api/tags``,
            ``False`` otherwise.
        """
        started_at = time.monotonic()
        try:
            self._ensure_connected()
            response = self._client.get(f"{self._host}/api/tags", timeout=self._timeout)
            status_code = getattr(response, "status_code", None)
            if status_code != 200:
                raise ProviderError(
                    "Ollama /api/tags returned a non-200 status",
                    details={"status_code": status_code},
                )
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=True, latency_ms=latency_ms)
            logger.debug(f"OllamaProvider health check OK ({latency_ms:.1f} ms)")
            return True
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=False, latency_ms=latency_ms, error=str(exc))
            logger.warning(f"OllamaProvider health check failed after {latency_ms:.1f} ms: {exc}")
            return False