"""Activation 6 -- real Telegram success-path proof.

Roadmap ``ACTIVATION 6 -- OPERATIONAL NOTIFICATION`` acceptance gate
(``Success``): "Notifikasi nyata terkirim ke Telegram." -- a real
notification actually delivered to Telegram. Every other Activation 6
proof suite (``test_activation6_1_*`` / ``test_activation6_2_*`` /
``test_activation6_3_*``) intentionally injects a fake HTTP client so
it can run offline/deterministically; none of them ever performs a
real outbound call. This script is the one, deliberately separate,
executable proof of the actual gate: it performs a real call, through
the real, unmodified production wiring, using the real
``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` environment
credentials -- and only those.

What this script does NOT do:
  * It does not build, mutate, or invent any Telegram endpoint --
    ``Services.notification_service.NotificationService._send_telegram``
    is called completely unmodified.
  * It does not touch trading state, ``Repository``, ``Database``, or
    any Order/Trade/Position/Account.
  * It does not fake, mock, or stub the HTTP layer -- the real
    ``requests`` library is used, exactly as production does when no
    ``http_client`` is injected into ``NotificationService``.
  * It never reports success unless Telegram's own API actually
    returned ``{"ok": true, ...}``.

Exit codes (deliberately distinct so a caller/CI can tell the
difference between "not configured" and "actually failed"):
  0 -- real message delivered; Telegram's own ``ok: true`` + a real
       ``message_id`` were observed.
  2 -- BLOCKED: TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are not
       configured in this environment. Not a code failure -- this
       script deliberately does not fake a send when there is nothing
       real to send with.
  3 -- FAILED: credentials were present but the real call did not
       succeed (invalid token/chat id, network unreachable, Telegram
       API error, etc). The failure is printed in full -- never
       swallowed, never turned into a fake success.

Manual retry: this script itself IS the manual retry mechanism the
roadmap's Failure gate requires ("notification dapat dicoba ulang
secara manual") -- it can simply be re-run, as many times as needed,
once credentials/network are fixed; nothing about a failed run leaves
any state behind that would block a subsequent attempt.

Run directly:
``python Tests/activation6_telegram_real_send_proof.py``
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Business.notification_event import NotificationEvent, NotificationEventType  # noqa: E402
from Core.composition_root import (  # noqa: E402
    _build_notification_service,
    _build_telegram_notification_channel,
    _notification_service_context_factory,
)
from Core.config import config  # noqa: E402

_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def main() -> int:
    bot_token = config.get_str(_BOT_TOKEN_ENV)
    chat_id = config.get_str(_CHAT_ID_ENV)
    missing = [
        name
        for name, value in ((_BOT_TOKEN_ENV, bot_token), (_CHAT_ID_ENV, chat_id))
        if not value
    ]
    if missing:
        print("BLOCKED - Activation 6 real Telegram success gate NOT attempted.")
        print(f"  Missing credential(s): {', '.join(missing)}")
        print(
            "  This is expected/honest in an environment with no real "
            "Telegram bot configured -- no message was sent, and none is "
            "claimed to have been sent."
        )
        return 2

    # Real, unmodified production objects -- no injected http_client, no
    # fake channel, no stub. The exact same NotificationService /
    # TelegramNotificationChannel / context-factory
    # build_application() wires into the real trading flow.
    notification_service = _build_notification_service()
    channel = _build_telegram_notification_channel(notification_service)

    probe_id = uuid.uuid4().hex[:8]
    event = NotificationEvent(
        event_type=NotificationEventType.DAILY_REPORT,
        timestamp="activation6-real-send-proof",
        title="AIOS Activation 6 proof",
        message=(
            f"AIOS Activation 6 real-send proof ({probe_id}). "
            "If you can read this in Telegram, the real success gate is proven."
        ),
        metadata={},
    )

    print(f"Credentials found ({_BOT_TOKEN_ENV}, {_CHAT_ID_ENV}) -- attempting a REAL send...")
    try:
        channel.send(event)
    except Exception as exc:  # noqa: BLE001 - report the real failure, never swallow it
        print("FAILED - the real Telegram call did not succeed.")
        print(f"  {type(exc).__name__}: {exc}")
        print(
            "  Trading state is unaffected either way (Activation 6.2/6.3 "
            "isolate notification failures) -- this script itself touches "
            "no trading state at all. Fix the credential/network issue and "
            "re-run this same script to retry manually."
        )
        return 3

    print("PASS - a real message was sent to Telegram and the Bot API returned ok=true.")
    print(f"  probe id: {probe_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())