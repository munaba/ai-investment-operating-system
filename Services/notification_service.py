from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from Core.exceptions import AgentError
from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)

#: Supported values for the ``channel`` metadata parameter.
DISCORD_CHANNEL: str = "discord"
TELEGRAM_CHANNEL: str = "telegram"
SUPPORTED_CHANNELS: frozenset = frozenset({DISCORD_CHANNEL, TELEGRAM_CHANNEL})

#: HTTP request timeout, in seconds, used for every outbound call.
_REQUEST_TIMEOUT_SECONDS: int = 10

#: Discord webhook status codes considered successful.
_DISCORD_SUCCESS_STATUS_CODES: frozenset = frozenset({200, 204})


class NotificationServiceError(AgentError):
    """Raised for any business-level failure while sending a notification.

    Additive subclass of ``Core.exceptions.AgentError``, following the
    same pattern used elsewhere in the framework (e.g. ``PlannerError``,
    ``NewsServiceError``). Never escapes :meth:`NotificationService.execute`
    -- it is always caught and converted into a failed
    :class:`Services.service_result.ServiceResult`.
    """


class NotificationService(BaseService):
    """Sends a notification through Discord or Telegram.

    The service is stateless aside from its injected HTTP client
    reference, which is never mutated after construction -- a single
    instance can therefore be shared safely across threads without extra
    locking.

    Args:
        http_client: Optional pre-configured HTTP client (or a test
            double exposing a ``requests``-compatible ``.post(url, ...)``
            method) to use instead of importing ``requests`` lazily. This
            is the same dependency-injection seam used by
            ``NewsService``'s ``yfinance_module``, and exists so this
            service can be smoke-tested without network access or without
            ``requests`` installed at all.
    """

    def __init__(self, http_client: Optional[Any] = None) -> None:
        self._http_client: Optional[Any] = http_client

    @property
    def name(self) -> str:
        """Unique, human-readable identifier for this service."""
        return "notification_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Sends notifications via Discord webhook or Telegram Bot API."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "notification"

    def _get_http_client(self) -> Any:
        """Resolve the HTTP client, injected or lazily imported.

        Returns:
            The injected client if one was provided at construction time,
            otherwise the freshly (lazily) imported ``requests`` module.

        Raises:
            NotificationServiceError: If no client was injected and
                ``requests`` is not installed.
        """
        if self._http_client is not None:
            return self._http_client
        try:
            import requests
        except ImportError as exc:
            raise NotificationServiceError(
                "requests is not installed. Install it with 'pip install requests'.",
                details={"error": str(exc)},
            ) from exc
        return requests

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Send a notification as described by ``context.metadata``.

        Args:
            context: Request context. Reads the following metadata keys:
                ``channel`` (str, required -- ``"discord"`` or
                ``"telegram"``), ``message`` (str, required),
                ``title`` (str, optional), ``image_path`` (str, optional
                path to a local image/file to attach),
                ``webhook_url`` (str, required for ``discord``),
                ``telegram_bot_token`` (str, required for ``telegram``),
                ``telegram_chat_id`` (str, required for ``telegram``).

        Returns:
            On success, a :class:`ServiceResult` whose ``data`` is
            ``{"channel": ..., "status": ..., "response": ...}``.
            On any business or unexpected error, a failed
            :class:`ServiceResult` built via :meth:`ServiceResult.fail`.
            This method never raises.
        """
        started_at = time.monotonic()
        try:
            channel = self._resolve_channel(context)
            message = self._resolve_message(context)
            title = self._resolve_optional_str(context, MetadataKeys.TITLE)
            image_path = self._resolve_optional_str(context, MetadataKeys.IMAGE_PATH)

            http_client = self._get_http_client()

            if channel == DISCORD_CHANNEL:
                webhook_url = self._require_credential(context, MetadataKeys.WEBHOOK_URL, channel)
                status, response = self._send_discord(
                    http_client, webhook_url, message, title, image_path
                )
            else:  # channel == TELEGRAM_CHANNEL (validated by _resolve_channel)
                bot_token = self._require_credential(context, MetadataKeys.TELEGRAM_BOT_TOKEN, channel)
                chat_id = self._require_credential(context, MetadataKeys.TELEGRAM_CHAT_ID, channel)
                status, response = self._send_telegram(
                    http_client, bot_token, chat_id, message, title, image_path
                )

            elapsed_ms = (time.monotonic() - started_at) * 1000
            return ServiceResult.ok(
                data={MetadataKeys.CHANNEL: channel, "status": status, "response": response},
                message=f"Notification sent via {channel}.",
                execution_time_ms=elapsed_ms,
            )
        except NotificationServiceError as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.warning(f"NotificationService.execute failed: {exc}")
            return ServiceResult.fail(exc, execution_time_ms=elapsed_ms)
        except Exception as exc:  # noqa: BLE001 - normalize any unexpected failure
            elapsed_ms = (time.monotonic() - started_at) * 1000
            wrapped = NotificationServiceError(
                "Unexpected error while sending notification", details={"error": str(exc)}
            )
            logger.error(f"NotificationService.execute unexpected error: {exc}")
            return ServiceResult.fail(wrapped, execution_time_ms=elapsed_ms)

    @staticmethod
    def _resolve_channel(context: ServiceContext) -> str:
        """Read and validate the ``channel`` metadata value.

        Raises:
            NotificationServiceError: If ``channel`` is missing, not a
                string, or not one of :data:`SUPPORTED_CHANNELS`.
        """
        channel = context.get_metadata(MetadataKeys.CHANNEL)
        if not isinstance(channel, str) or not channel.strip():
            raise NotificationServiceError(
                "channel must be a non-empty string", details={"channel": channel}
            )
        normalized = channel.strip().lower()
        if normalized not in SUPPORTED_CHANNELS:
            raise NotificationServiceError(
                f"Invalid channel: '{channel}'. Supported channels: "
                f"{sorted(SUPPORTED_CHANNELS)}",
                details={"channel": channel},
            )
        return normalized

    @staticmethod
    def _resolve_message(context: ServiceContext) -> str:
        """Read and validate the ``message`` metadata value.

        Raises:
            NotificationServiceError: If ``message`` is missing, not a
                string, or empty.
        """
        message = context.get_metadata(MetadataKeys.MESSAGE)
        if not isinstance(message, str) or not message.strip():
            raise NotificationServiceError(
                "message must be a non-empty string", details={"message": message}
            )
        return message

    @staticmethod
    def _resolve_optional_str(context: ServiceContext, key: str) -> Optional[str]:
        """Read an optional string metadata value, treating blanks as absent."""
        value = context.get_metadata(key)
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    @staticmethod
    def _require_credential(context: ServiceContext, key: str, channel: str) -> str:
        """Read a required credential metadata value for ``channel``.

        Raises:
            NotificationServiceError: If ``key`` is missing, not a
                string, or empty.
        """
        value = context.get_metadata(key)
        if not isinstance(value, str) or not value.strip():
            raise NotificationServiceError(
                f"Missing credential '{key}' for channel '{channel}'",
                details={"channel": channel, "credential": key},
            )
        return value.strip()

    @staticmethod
    def _send_discord(
        http_client: Any,
        webhook_url: str,
        message: str,
        title: Optional[str],
        image_path: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        """Send a message to a Discord webhook.

        Sends a rich embed (``title`` + ``message`` as description) when
        ``title`` is provided, otherwise sends ``message`` as plain
        webhook content. When ``image_path`` is provided, the file is
        attached via multipart upload alongside the payload.

        Args:
            http_client: A ``requests``-compatible client exposing ``.post``.
            webhook_url: Discord webhook URL to POST to.
            message: The notification text.
            title: Optional embed title.
            image_path: Optional path to a local file to attach.

        Returns:
            A ``(status, response)`` tuple where ``status`` is a short
            human-readable outcome string and ``response`` contains
            normalized response details.

        Raises:
            NotificationServiceError: If the attachment file cannot be
                read, the request fails, or Discord returns an
                unexpected status code.
        """
        payload: Dict[str, Any] = (
            {"embeds": [{"title": title, "description": message}]}
            if title
            else {"content": message}
        )

        try:
            if image_path:
                with open(image_path, "rb") as file_obj:
                    files = {"file": (os.path.basename(image_path), file_obj)}
                    data = {"payload_json": json.dumps(payload)}
                    response = http_client.post(
                        webhook_url, data=data, files=files, timeout=_REQUEST_TIMEOUT_SECONDS
                    )
            else:
                response = http_client.post(
                    webhook_url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS
                )
        except FileNotFoundError as exc:
            raise NotificationServiceError(
                f"Image file not found: '{image_path}'", details={"image_path": image_path}
            ) from exc
        except NotificationServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize any transport-level error
            raise NotificationServiceError(
                "Discord webhook request failed", details={"error": str(exc)}
            ) from exc

        status_code = getattr(response, "status_code", None)
        if status_code not in _DISCORD_SUCCESS_STATUS_CODES:
            raise NotificationServiceError(
                f"Discord webhook returned unexpected status code: {status_code}",
                details={"status_code": status_code, "body": getattr(response, "text", "")},
            )
        return "sent", {"status_code": status_code}

    @staticmethod
    def _send_telegram(
        http_client: Any,
        bot_token: str,
        chat_id: str,
        message: str,
        title: Optional[str],
        image_path: Optional[str],
    ) -> Tuple[str, Dict[str, Any]]:
        """Send a message to a Telegram chat via the Bot API.

        Uses ``sendPhoto`` (with ``message``/``title`` as the caption)
        when ``image_path`` is provided, otherwise uses ``sendMessage``.
        Telegram has no native "title" concept, so when provided it is
        folded into the leading line of the text/caption (see module
        Architecture Notes).

        Args:
            http_client: A ``requests``-compatible client exposing ``.post``.
            bot_token: Telegram bot token.
            chat_id: Target chat id.
            message: The notification text.
            title: Optional leading title line.
            image_path: Optional path to a local image to attach.

        Returns:
            A ``(status, response)`` tuple where ``status`` is a short
            human-readable outcome string and ``response`` is the parsed
            JSON body returned by Telegram.

        Raises:
            NotificationServiceError: If the attachment file cannot be
                read, the request fails, or Telegram reports a
                non-``ok`` result.
        """
        text = f"{title}\n\n{message}" if title else message
        base_url = f"https://api.telegram.org/bot{bot_token}"

        try:
            if image_path:
                with open(image_path, "rb") as file_obj:
                    files = {"photo": (os.path.basename(image_path), file_obj)}
                    data = {"chat_id": chat_id, "caption": text}
                    response = http_client.post(
                        f"{base_url}/sendPhoto",
                        data=data,
                        files=files,
                        timeout=_REQUEST_TIMEOUT_SECONDS,
                    )
            else:
                data = {"chat_id": chat_id, "text": text}
                response = http_client.post(
                    f"{base_url}/sendMessage", data=data, timeout=_REQUEST_TIMEOUT_SECONDS
                )
        except FileNotFoundError as exc:
            raise NotificationServiceError(
                f"Image file not found: '{image_path}'", details={"image_path": image_path}
            ) from exc
        except NotificationServiceError:
            raise
        except Exception as exc:  
            raise NotificationServiceError(
                "Telegram API request failed", details={"error": str(exc)}
            ) from exc

        body: Optional[Dict[str, Any]]
        try:
            body = response.json()
        except Exception:  
            body = None

        status_code = getattr(response, "status_code", None)
        is_ok = bool(body.get("ok")) if isinstance(body, dict) else False
        if status_code != 200 or not is_ok:
            description = body.get("description") if isinstance(body, dict) else None
            raise NotificationServiceError(
                f"Telegram API call failed: {description or status_code}",
                details={"status_code": status_code, "body": body},
            )
        return "sent", body or {}

    def health_check(self) -> bool:
        """Report whether this service can currently resolve its dependency.

        Mirrors the ``bool``-returning contract shared by every
        ``health_check()`` in the framework (``BaseProvider``,
        ``BaseAgent``, ``BaseService``). Deliberately does not perform a
        live network call: it only verifies that an HTTP client
        (injected or importable ``requests``) is available, so health
        checks remain fast and safe to call frequently. Never raises.

        Returns:
            ``True`` if an HTTP client can be resolved, ``False``
            otherwise.
        """
        try:
            self._get_http_client()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"NotificationService.health_check failed: {exc}")
            return False