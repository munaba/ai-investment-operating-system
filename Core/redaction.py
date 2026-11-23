"""Strip credentials out of error text before it is stored, logged or exported.

Network errors from ``requests``/``urllib3`` quote the full request URL, and
Telegram's Bot API puts the bot token in the URL path
(``https://api.telegram.org/bot<TOKEN>/sendMessage``). Such text reaches
``scheduler_job_runs.detail``, audit payloads and the public dashboard
snapshot, so every error string from a credentialed call goes through
:func:`redact_secrets` first.
"""
from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Telegram bot token, with or without the "bot" URL prefix.
    (re.compile(r"(bot)?\d{6,12}:[A-Za-z0-9_-]{30,}"), r"\1<redacted-telegram-token>"),
    # Discord webhook id/token.
    (re.compile(r"(discord(?:app)?\.com/api/webhooks/)\d+/[A-Za-z0-9_-]+"), r"\1<redacted>"),
    # Google API keys (Gemini).
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<redacted-google-key>"),
    # key=/token= style query parameters.
    (re.compile(r"((?:api[_-]?key|token|access_token|key)=)[^&\s'\"]+", re.IGNORECASE), r"\1<redacted>"),
)


def redact_secrets(text: object) -> str:
    """Return ``str(text)`` with known credential formats replaced."""
    result = str(text)
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result
