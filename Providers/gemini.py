"""Google Gemini implementation of :class:`Providers.base_provider.BaseProvider`.

Uses the official ``google-genai`` SDK (``from google import genai``). The
SDK itself is imported lazily inside :meth:`GeminiProvider.connect` so that
importing this module — or the ``Providers`` package as a whole — never
requires ``google-genai`` to be installed unless a caller actually connects
a :class:`GeminiProvider`.

The API key is read from ``Core.config`` (``GEMINI_API_KEY``) and the model
name is read from ``Core.config`` (``GEMINI_MODEL``) — neither is ever
hardcoded.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from Core.config import config
from Core.exceptions import ProviderError
from Core.logger import get_logger
from .base_provider import BaseProvider
from .message import Message, MessageRole
from .response import ProviderResponse, Usage

logger = get_logger(__name__)

# TODO:
_ROLE_MAP: Dict[MessageRole, str] = {
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "model",
    MessageRole.TOOL: "user",  # TODO: 
}


class GeminiProvider(BaseProvider):
    """Gemini provider backed by the Google GenAI SDK.

    Attributes:
        model: The Gemini model name used for requests (read from
            ``GEMINI_MODEL`` in configuration unless overridden).
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        """Initialize the provider without connecting yet.

        Args:
            api_key: Gemini API key. Defaults to ``config.get("GEMINI_API_KEY")``.
            model: Gemini model name. Defaults to ``config.get("GEMINI_MODEL")``.
        """
        super().__init__()
        self._api_key: Optional[str] = api_key or config.get("GEMINI_API_KEY")
        self.model: Optional[str] = model or config.get("GEMINI_MODEL")
        self._client: Any = None
        self._connected: bool = False

    @property
    def name(self) -> str:
        """Return this provider's identifier.

        Returns:
            The string ``"gemini"``.
        """
        return "gemini"

    def connect(self) -> None:
        """Create the underlying Gemini SDK client.

        Idempotent: does nothing if already connected.

        Raises:
            ProviderError: If ``GEMINI_API_KEY``/``GEMINI_MODEL`` are not
                configured, the SDK is not installed, or client creation fails.
        """
        if self._connected:
            return

        if not self._api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not configured. Set it in your .env file."
            )
        if not self.model:
            raise ProviderError(
                "GEMINI_MODEL is not configured. Set it in your .env file."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError(
                "google-genai SDK is not installed. Install it with 'pip install google-genai'."
            ) from exc

        try:
            self._client = genai.Client(api_key=self._api_key)
            self._connected = True
            logger.debug(f"GeminiProvider connected using model '{self.model}'")
        except Exception as exc:  
            raise ProviderError("Failed to initialize Gemini client", details={"error": str(exc)}) from exc

    def disconnect(self) -> None:
        """Release the Gemini SDK client, if any."""
        if self._client is not None and hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Error while closing Gemini client: {exc}")
        self._client = None
        self._connected = False
        logger.debug("GeminiProvider disconnected")

    def _ensure_connected(self) -> None:
        """Connect lazily if this provider has not been connected yet.

        Raises:
            ProviderError: If connecting fails (see :meth:`connect`).
        """
        if not self._connected:
            self.connect()

    def _to_gemini_contents(self, messages: List[Message]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Convert provider-agnostic messages into Gemini SDK ``contents``.

        Args:
            messages: The conversation history to convert.

        Returns:
            A tuple of ``(contents, system_instruction)`` where ``contents``
            is a list of Gemini content dicts and ``system_instruction`` is
            the concatenated text of any ``SYSTEM`` messages (or ``None``).
        """
        contents: List[Dict[str, Any]] = []
        system_parts: List[str] = []

        for message in messages:
            if message.role == MessageRole.SYSTEM:
                system_parts.append(message.content)
                continue
            gemini_role = _ROLE_MAP.get(message.role, "user")
            contents.append({"role": gemini_role, "parts": [{"text": message.content}]})

        system_instruction = "\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        """Generate a complete response using Gemini's ``generate_content``.

        Args:
            messages: The conversation history to generate a reply for.
            **kwargs: Optional generation options: ``temperature`` (float),
                ``max_output_tokens`` (int).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If ``messages`` is empty (after removing system
                messages) or the request to Gemini fails.
        """
        self._ensure_connected()
        contents, system_instruction = self._to_gemini_contents(messages)
        if not contents:
            raise ProviderError("Cannot generate a response from an empty message list")

        try:
            from google.genai import types

            config_kwargs: Dict[str, Any] = {}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction
            if "max_output_tokens" in kwargs:
                config_kwargs["max_output_tokens"] = kwargs["max_output_tokens"]
            if "temperature" in kwargs:
                config_kwargs["temperature"] = kwargs["temperature"]

            generation_config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=generation_config,
            )
        except ProviderError:
            raise
        except Exception as exc:  
            raise ProviderError("Gemini generate_content request failed", details={"error": str(exc)}) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Convert a raw Gemini SDK response into a normalized ``ProviderResponse``.

        Args:
            response: The raw response object returned by the Gemini SDK.

        Returns:
            A normalized :class:`ProviderResponse`.
        """
        text = getattr(response, "text", "") or ""

        usage_metadata = getattr(response, "usage_metadata", None)
        usage = (
            Usage(
                input_tokens=getattr(usage_metadata, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage_metadata, "candidates_token_count", 0) or 0,
                total_tokens=getattr(usage_metadata, "total_token_count", 0) or 0,
            )
            if usage_metadata is not None
            else Usage()
        )

        finish_reason: Optional[str] = None
        candidates = getattr(response, "candidates", None)
        if candidates:
            raw_finish_reason = getattr(candidates[0], "finish_reason", None)
            finish_reason = str(raw_finish_reason) if raw_finish_reason is not None else None

        return ProviderResponse(
            text=text,
            finish_reason=finish_reason,
            model=self.model or "",
            usage=usage,
            raw_response=response,
            metadata={},
        )

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        """Streaming is not yet implemented for this provider.

        The Google GenAI SDK exposes ``generate_content_stream()`` for this
        purpose; wiring it up is left for a future iteration, as permitted
        by the provider framework's requirements.

        Raises:
            NotImplementedError: Always, in this version.
        """
        raise NotImplementedError(
            "GeminiProvider.stream() is not implemented yet. "
            "The underlying SDK supports generate_content_stream(); "
            "this will be wired up in a future update."
        )

    def count_tokens(self, messages: List[Message]) -> int:
        """Count tokens for the given messages using Gemini's ``count_tokens``.

        Args:
            messages: The messages to count tokens for.

        Returns:
            The total token count reported by Gemini.

        Raises:
            ProviderError: If the request to Gemini fails.
        """
        self._ensure_connected()
        contents, _system_instruction = self._to_gemini_contents(messages)
        try:
            response = self._client.models.count_tokens(model=self.model, contents=contents)
            return int(getattr(response, "total_tokens", 0) or 0)
        except Exception as exc:  
            raise ProviderError("Gemini count_tokens request failed", details={"error": str(exc)}) from exc

    def health_check(self) -> bool:
        """Check whether Gemini is reachable using a minimal token-count request.

        Never raises: any failure is caught, logged, and reported as
        ``False``. Records latency and (on failure) the error message via
        :meth:`BaseProvider._record_health_check`, retrievable afterwards
        through :attr:`last_health_check` for richer diagnostics than the
        plain boolean return value (e.g. for dashboards or alerting).

        Returns:
            ``True`` if Gemini responded successfully, ``False`` otherwise.
        """
        started_at = time.monotonic()
        try:
            self._ensure_connected()
            self.count_tokens([Message(role=MessageRole.USER, content="ping")])
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=True, latency_ms=latency_ms)
            logger.debug(f"GeminiProvider health check OK ({latency_ms:.1f} ms)")
            return True
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_health_check(healthy=False, latency_ms=latency_ms, error=str(exc))
            logger.warning(f"GeminiProvider health check failed after {latency_ms:.1f} ms: {exc}")
            return False