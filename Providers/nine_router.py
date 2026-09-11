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

#: Static capability metadata -- mirrors OllamaProvider's own
#: declaration style. 9router is a locally-run proxy server
#: (``9router`` CLI, default dashboard/API at
#: ``http://localhost:20128``) that fronts many remote AI providers
#: behind a single OpenAI-compatible endpoint, so ``is_local=True``
#: reflects what THIS provider connects to (a local process), not the
#: (possibly remote) model it ultimately routes to. stream() and
#: count_tokens() are not implemented yet -- same deferral OllamaProvider
#: makes for its own Stage L1 scope.
_NINE_ROUTER_CAPABILITIES = ProviderCapabilities(
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
_DEFAULT_HOST: str = "http://localhost:20128"


class NineRouterProvider(BaseProvider):
    """AI provider backed by a locally-running ``9router`` server's
    OpenAI-compatible HTTP API (``/v1/chat/completions``).

    ``9router`` (see https://www.npmjs.com/package/9router) is a
    third-party, locally-hosted proxy that exposes many upstream AI
    providers (Claude, OpenAI, Gemini, and others) behind one unified
    OpenAI-compatible endpoint. This class only talks to that local
    endpoint -- it has no knowledge of, and does not need to know,
    which upstream model 9router itself routes a given request to.

    Mirrors ``Providers.ollama.OllamaProvider``'s structure and scope
    exactly (construct-only ``connect()``, ``generate()``/
    ``health_check()`` implemented, ``stream()``/``count_tokens()``
    deferred), swapping only the wire format (OpenAI ``/v1/chat/
    completions`` request/response shape and an ``Authorization:
    Bearer <api_key>`` header when an API key is configured, instead
    of Ollama's own ``/api/chat`` shape).

    Attributes:
        model: The model identifier sent to 9router (e.g. a value
            from 9router's own dashboard, such as
            ``"kr/claude-sonnet-4.5"``), read from ``NINE_ROUTER_MODEL``
            unless overridden.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        """Initialize the provider without connecting yet.

        Args:
            host: Base URL of the running 9router server (e.g.
                ``http://localhost:20128``). Defaults to
                ``config.get("NINE_ROUTER_HOST", _DEFAULT_HOST)`` --
                unlike Ollama, a sensible default is used since
                9router's default port is fixed and well-known.
            model: Model identifier to request from 9router. Defaults
                to ``config.get("NINE_ROUTER_MODEL")``.
            api_key: Optional API key copied from the 9router
                dashboard, sent as ``Authorization: Bearer <api_key>``.
                Defaults to ``config.get("NINE_ROUTER_API_KEY")``.
                May be omitted entirely if the local 9router instance
                is configured without auth.
            timeout: Per-request timeout in seconds. Defaults to
                ``config.get_float("NINE_ROUTER_TIMEOUT", 300.0)``.
            http_client: Optional pre-configured HTTP client (or a
                test double) exposing ``.post``/``.get``, same
                injection pattern as ``OllamaProvider``. When omitted,
                ``requests`` is lazily imported on :meth:`connect`.
        """
        super().__init__()
        self._host: str = (host or config.get("NINE_ROUTER_HOST", _DEFAULT_HOST) or _DEFAULT_HOST).rstrip("/")
        self.model: Optional[str] = model or config.get("NINE_ROUTER_MODEL")
        self._api_key: Optional[str] = api_key or config.get("NINE_ROUTER_API_KEY")
        self._timeout: float = (
            timeout if timeout is not None else config.get_float("NINE_ROUTER_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)
        )
        self._http_client: Optional[Any] = http_client
        self._client: Any = None
        self._connected: bool = False

    @property
    def name(self) -> str:
        """Return this provider's identifier.

        Returns:
            The string ``"nine_router"``.
        """
        return "nine_router"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return this provider's static capability metadata.

        See module-level ``_NINE_ROUTER_CAPABILITIES`` for the
        declared values and the reasoning behind each one.

        Returns:
            This provider's :class:`ProviderCapabilities`.
        """
        return _NINE_ROUTER_CAPABILITIES

    def _get_http_client(self) -> Any:
        """Resolve the HTTP client, injected or lazily imported.

        Returns:
            The injected client if one was provided at construction
            time, otherwise the freshly (lazily) imported ``requests``
            module.

        Raises:
            ProviderError: If no client was injected and ``requests``
                is not installed.
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
        ``NINE_ROUTER_MODEL`` is configured, mirroring
        ``OllamaProvider.connect()``'s construct-only contract.
        ``NINE_ROUTER_HOST`` is never required to be explicitly set
        (it defaults to ``http://localhost:20128``), matching
        9router's own documented default port.

        Raises:
            ProviderError: If ``NINE_ROUTER_MODEL`` is not configured,
                or ``requests`` is not installed and no ``http_client``
                was injected.
        """
        if self._connected:
            return

        if not self.model:
            raise ProviderError(
                "NINE_ROUTER_MODEL is not configured. Set it in your .env file "
                "(pick a model id from the 9router dashboard, e.g. "
                "'kr/claude-sonnet-4.5')."
            )

        self._client = self._get_http_client()
        self._connected = True
        logger.debug(f"NineRouterProvider connected using model '{self.model}' at '{self._host}'")

    def disconnect(self) -> None:
        """Release the resolved HTTP client, if any."""
        self._client = None
        self._connected = False
        logger.debug("NineRouterProvider disconnected")

    def _ensure_connected(self) -> None:
        """Connect lazily if this provider has not been connected yet.

        Raises:
            ProviderError: If connecting fails (see :meth:`connect`).
        """
        if not self._connected:
            self.connect()

    def _headers(self) -> Dict[str, str]:
        """Build request headers, including ``Authorization`` only
        when an API key is configured -- 9router instances run
        without auth are never sent an empty/placeholder header."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _to_openai_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert provider-agnostic messages into OpenAI-style chat
        messages.

        Args:
            messages: The conversation history to convert.

        Returns:
            A list of ``{"role": ..., "content": ...}`` dicts for the
            9router ``/v1/chat/completions`` endpoint.
        """
        return [
            {"role": _ROLE_MAP.get(message.role, "user"), "content": message.content}
            for message in messages
        ]

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        """Generate a complete response using 9router's
        ``/v1/chat/completions`` endpoint.

        Args:
            messages: The conversation history to generate a reply
                for.
            **kwargs: Optional generation options: ``temperature``
                (float), ``max_output_tokens`` (int, mapped to the
                OpenAI-style ``max_tokens`` field).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If ``messages`` is empty, or the request to
                9router fails.
        """
        self._ensure_connected()
        if not messages:
            raise ProviderError("Cannot generate a response from an empty message list")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
            "stream": False,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "max_output_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_output_tokens"]

        try:
            response = self._client.post(
                f"{self._host}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
        except Exception as exc:
            raise ProviderError(
                "9router /v1/chat/completions request failed", details={"error": str(exc)}
            ) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Convert a raw ``/v1/chat/completions`` HTTP response into a
        normalized ``ProviderResponse``.

        Args:
            response: The raw HTTP response object (``requests``-
                compatible: exposes ``.status_code``/``.json()``/
                ``.text``).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If the HTTP status indicates failure, or
                the response body cannot be parsed as JSON.
        """
        status_code = getattr(response, "status_code", None)
        if status_code is not None and status_code != 200:
            raise ProviderError(
                "9router /v1/chat/completions returned a non-200 status",
                details={"status_code": status_code, "body": getattr(response, "text", "")},
            )

        try:
            body = response.json()
        except Exception as exc:
            raise ProviderError(
                "9router /v1/chat/completions returned a non-JSON response",
                details={"error": str(exc)},
            ) from exc

        choices = body.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message", {}) or {}
        text = message.get("content", "") or ""
        finish_reason = first_choice.get("finish_reason")

        raw_usage = body.get("usage", {}) or {}
        usage = Usage(
            input_tokens=int(raw_usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(raw_usage.get("completion_tokens", 0) or 0),
            total_tokens=int(raw_usage.get("total_tokens", 0) or 0),
        )

        return ProviderResponse(
            text=text,
            finish_reason=finish_reason,
            model=body.get("model") or self.model or "",
            usage=usage,
            raw_response=body,
            metadata={},
        )

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        """Streaming is not implemented yet.

        9router's ``/v1/chat/completions`` supports ``"stream": true``
        with server-sent-event chunks (standard OpenAI streaming
        format); wiring that up is deferred to a future update, same
        deferral ``OllamaProvider.stream()`` makes.

        Raises:
            NotImplementedError: Always, in this version.
        """
        raise NotImplementedError(
            "NineRouterProvider.stream() is not implemented yet. "
            "The 9router /v1/chat/completions endpoint supports stream=true; "
            "this will be wired up in a future update."
        )

    def count_tokens(self, messages: List[Message]) -> int:
        """Token counting is not implemented yet.

        9router does not expose a dedicated token-counting endpoint;
        ``prompt_tokens``/``completion_tokens`` are only available
        after a real ``/v1/chat/completions`` call (see
        :meth:`generate`). Deferred rather than approximated here.

        Raises:
            NotImplementedError: Always, in this version.
        """
        raise NotImplementedError("NineRouterProvider.count_tokens() is not implemented yet.")

    def health_check(self) -> bool:
        """Check whether the 9router server is reachable via
        ``/v1/models``.

        Never raises: any failure is caught, logged, and reported as
        ``False``. Records latency and (on failure) the error message
        via :meth:`BaseProvider._record_health_check`, retrievable
        afterwards through :attr:`last_health_check`.

        Returns:
            ``True`` if 9router responded successfully to
            ``/v1/models``, ``False`` otherwise.
        """
        started_at = time.monotonic()
        try:
            self._ensure_connected()
            response = self._client.get(
                f"{self._host}/v1/models", headers=self._headers(), timeout=self._timeout
            )
            status_code = getattr(response, "status_code", None)
            if status_code != 200:
                raise ProviderError(
                    "9router /v1/models returned a non-200 status",
                    details={"status_code": status_code},
                )
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=True, latency_ms=latency_ms)
            return True
        except Exception as exc:
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=False, latency_ms=latency_ms, error=str(exc))
            logger.warning(f"NineRouterProvider health_check failed: {exc}")
            return False
