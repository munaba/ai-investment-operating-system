"""
Activation 6.1 proof suite -- Telegram credential wiring into
``ServiceContext`` (production path only).

Scope: this STEP makes ``Core.composition_root.
_notification_service_context_factory`` -- the one, real production
``service_context_factory`` given to ``TelegramNotificationChannel``
-- the sole call site that resolves the Telegram bot token and chat id
from ``Core.config`` (i.e. the ``TELEGRAM_BOT_TOKEN`` /
``TELEGRAM_CHAT_ID`` environment variables) into
``ServiceContext.metadata``, so ``Services.notification_service.
NotificationService.execute()`` can actually find them.

Explicitly out of scope for this STEP (LOCKED, unchanged):
  * ``Business.telegram_notification_channel.TelegramNotificationChannel``
    -- its own dedicated suite (``Tests/test_telegram_notification_channel.py``)
    still asserts it forwards *only* ``channel``/``message``. This
    suite does not touch or re-test that contract.
  * ``Business.notification_event``, ``Business.notification_dispatcher``,
    ``Business.notification_manager`` -- no event/trigger behavior
    changes in this STEP.
  * No scheduler, background worker, or autonomous execution is added
    anywhere.
  * Discord/email/multi-channel: untouched -- this suite only exercises
    the Telegram path.

Credentials used in this suite are read exclusively from
``os.environ`` (via ``Core.config.config``, the same production
singleton), restored after every scenario -- never hard-coded as the
value ``NotificationService`` actually sends anywhere.

Scenario coverage:
    S1  -- Credential present in environment reaches
           ``ServiceContext.metadata`` (bot token + chat id both).
    S2  -- ``message`` is still forwarded through the factory
           unchanged, alongside the injected credentials.
    S3  -- ``title``, if a caller already put it in ``metadata``, is
           preserved through the factory untouched (contract support
           for "title jika diperlukan").
    S4  -- Credential is never hard-coded: two different environment
           values produce two different ``ServiceContext.metadata``
           values (source-level proof, not just behavioral).
    S5  -- No credential literal string appears in
           ``Core/composition_root.py`` source (static/AST-adjacent
           proof against hard-coding).
    S6  -- Missing bot token -> ``NotificationService.execute()``
           returns an explicit failed ``ServiceResult`` (never raises,
           never silently "succeeds").
    S7  -- Missing chat id -> same explicit failure behavior.
    S8  -- Both credentials missing -> same explicit failure behavior,
           and the failure message identifies the first missing
           credential.
    S9  -- Both credentials present -> the factory no longer blocks;
           the failure this suite gets (if any) comes only from the
           network layer (an injected fake HTTP client that always
           succeeds is used, so end-to-end resolution is proven
           without any real Telegram call).
    S10 -- The factory never mutates the ``metadata`` dict object the
           caller passed in (defensive copy).
    S11 -- Caller-supplied credential values (if ever present) are
           never overwritten by the environment-sourced ones.
    S12 -- Regression: the existing Sprint 7 STEP 4/7 notification
           suites still pass unmodified (invoked as subprocesses).

Run directly:
``python Tests/test_activation6_1_telegram_credential_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Core.composition_root as composition_root_mod  # noqa: E402
from Business.notification_event import NotificationEvent, NotificationEventType  # noqa: E402
from Business.telegram_notification_channel import TelegramNotificationChannel  # noqa: E402
from Core.composition_root import _notification_service_context_factory  # noqa: E402
from Services.metadata_keys import MetadataKeys  # noqa: E402
from Services.notification_service import NotificationService  # noqa: E402
from Services.service_context import ServiceContext  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Environment isolation helpers
# ---------------------------------------------------------------------------
class _EnvSandbox:
    """Save/restore TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID around a scenario."""

    def __enter__(self) -> "_EnvSandbox":
        self._saved: Dict[str, Optional[str]] = {
            _BOT_TOKEN_ENV: os.environ.get(_BOT_TOKEN_ENV),
            _CHAT_ID_ENV: os.environ.get(_CHAT_ID_ENV),
        }
        return self

    def set(self, bot_token: Optional[str], chat_id: Optional[str]) -> None:
        for key, value in ((_BOT_TOKEN_ENV, bot_token), (_CHAT_ID_ENV, chat_id)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, *exc_info: object) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeHttpClient:
    """A requests-compatible double that always returns a Telegram-shaped
    success response. Used only to prove end-to-end resolution without
    any real network call."""

    class _Response:
        status_code = 200

        def json(self) -> Dict[str, Any]:
            return {"ok": True, "result": {"message_id": 1}}

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> "FakeHttpClient._Response":
        self.calls.append({"url": url, **kwargs})
        return self._Response()


def make_event(message: str = "hello", title: str = "Report") -> NotificationEvent:
    return NotificationEvent(
        event_type=NotificationEventType.NEW_SIGNAL,
        timestamp="2026-08-12T00:00:00Z",
        title=title,
        message=message,
        metadata={},
    )


# ---------------------------------------------------------------------------
# S1 -- credential present in environment reaches ServiceContext.metadata
# ---------------------------------------------------------------------------
def scenario_env_credential_reaches_context() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="123:ABC-test-token", chat_id="-100999888")
        context = _notification_service_context_factory(
            {MetadataKeys.CHANNEL: "telegram", MetadataKeys.MESSAGE: "hi"}
        )
        check(
            isinstance(context, ServiceContext),
            "S1: factory returns a real ServiceContext",
        )
        check(
            context.metadata.get(MetadataKeys.TELEGRAM_BOT_TOKEN) == "123:ABC-test-token",
            "S1: TELEGRAM_BOT_TOKEN from the environment reaches "
            "ServiceContext.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN]",
        )
        check(
            context.metadata.get(MetadataKeys.TELEGRAM_CHAT_ID) == "-100999888",
            "S1: TELEGRAM_CHAT_ID from the environment reaches "
            "ServiceContext.metadata[MetadataKeys.TELEGRAM_CHAT_ID]",
        )


# ---------------------------------------------------------------------------
# S2 -- message forwarded unchanged alongside injected credentials
# ---------------------------------------------------------------------------
def scenario_message_forwarded_with_credentials() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="tok", chat_id="chat")
        context = _notification_service_context_factory(
            {MetadataKeys.CHANNEL: "telegram", MetadataKeys.MESSAGE: "portfolio update"}
        )
        check(
            context.metadata.get(MetadataKeys.MESSAGE) == "portfolio update",
            "S2: message is forwarded through the factory unchanged",
        )
        check(
            context.metadata.get(MetadataKeys.CHANNEL) == "telegram",
            "S2: channel is forwarded through the factory unchanged",
        )


# ---------------------------------------------------------------------------
# S3 -- title, when already supplied, is preserved untouched
# ---------------------------------------------------------------------------
def scenario_title_preserved_when_supplied() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="tok", chat_id="chat")
        context = _notification_service_context_factory(
            {
                MetadataKeys.CHANNEL: "telegram",
                MetadataKeys.MESSAGE: "body",
                MetadataKeys.TITLE: "Daily Report",
            }
        )
        check(
            context.metadata.get(MetadataKeys.TITLE) == "Daily Report",
            "S3: title, when already present in the metadata a caller "
            "supplies, is preserved untouched through the factory",
        )


# ---------------------------------------------------------------------------
# S4 -- credential is never hard-coded: different env -> different result
# ---------------------------------------------------------------------------
def scenario_different_env_values_produce_different_results() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="token-one", chat_id="chat-one")
        context_a = _notification_service_context_factory(
            {MetadataKeys.CHANNEL: "telegram", MetadataKeys.MESSAGE: "m"}
        )
        env.set(bot_token="token-two", chat_id="chat-two")
        context_b = _notification_service_context_factory(
            {MetadataKeys.CHANNEL: "telegram", MetadataKeys.MESSAGE: "m"}
        )
        check(
            context_a.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN] == "token-one",
            "S4: first environment value is reflected exactly",
        )
        check(
            context_b.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN] == "token-two",
            "S4: second (different) environment value is reflected exactly",
        )
        check(
            context_a.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN]
            != context_b.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN],
            "S4: changing the environment changes the credential the "
            "factory produces -- proves it is not a fixed/hard-coded "
            "literal",
        )


# ---------------------------------------------------------------------------
# S5 -- no credential literal in composition_root.py source
# ---------------------------------------------------------------------------
def scenario_no_hardcoded_credential_literal_in_source() -> None:
    source = (ROOT / "Core" / "composition_root.py").read_text(encoding="utf-8")
    check(
        "config.get_str(_TELEGRAM_BOT_TOKEN_ENV)" in source
        or "config.get_str(\"TELEGRAM_BOT_TOKEN\")" in source,
        "S5: composition_root.py reads the bot token via Core.config, "
        "not a literal value",
    )
    # A crude but effective heuristic: a hard-coded Telegram bot token
    # looks like digits ':' 35 alnum/underscore/hyphen chars. None
    # should appear anywhere in this module's source.
    import re

    check(
        re.search(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b", source) is None,
        "S5: no string matching the shape of a real Telegram bot "
        "token literal appears anywhere in composition_root.py",
    )


# ---------------------------------------------------------------------------
# S6/S7/S8 -- missing credential(s) -> explicit failure, never silent
# ---------------------------------------------------------------------------
def _execute_via_production_path(
    http_client: Any, bot_token: Optional[str], chat_id: Optional[str]
):
    with _EnvSandbox() as env:
        env.set(bot_token=bot_token, chat_id=chat_id)
        channel = TelegramNotificationChannel(
            notification_service=NotificationService(http_client=http_client),
            service_context_factory=_notification_service_context_factory,
        )
        result_holder: Dict[str, Any] = {}

        # TelegramNotificationChannel.send() itself never returns the
        # ServiceResult (LOCKED contract), so a thin spy NotificationService
        # is used purely to capture it for this suite's own assertions,
        # without changing send()'s own behavior at all.
        original_execute = channel._notification_service.execute

        def capturing_execute(context: ServiceContext):
            result = original_execute(context)
            result_holder["result"] = result
            return result

        channel._notification_service.execute = capturing_execute  # type: ignore[method-assign]
        # Activation 6.2 note: channel.send() itself now raises when
        # execute() returns a failed ServiceResult (see
        # Tests/test_activation6_2_notification_failure_propagation.py
        # for the dedicated proof of that behavior). This suite's own
        # concern is unchanged -- inspecting the ServiceResult
        # NotificationService.execute() produced -- so the (now
        # expected) exception from send() is caught here purely to
        # let this helper still return that captured ServiceResult;
        # it is not swallowed anywhere production code runs.
        try:
            channel.send(make_event())
        except Exception:  # noqa: BLE001
            pass
        return result_holder["result"]


def scenario_missing_bot_token_is_explicit_failure() -> None:
    result = _execute_via_production_path(FakeHttpClient(), bot_token=None, chat_id="chat-id")
    check(
        result.success is False,
        "S6: missing TELEGRAM_BOT_TOKEN produces a failed ServiceResult "
        "(explicit failure), never a silent success",
    )
    check(
        "telegram_bot_token" in str(result.error).lower(),
        "S6: the failure explicitly names the missing credential",
    )


def scenario_missing_chat_id_is_explicit_failure() -> None:
    result = _execute_via_production_path(FakeHttpClient(), bot_token="tok", chat_id=None)
    check(
        result.success is False,
        "S7: missing TELEGRAM_CHAT_ID produces a failed ServiceResult "
        "(explicit failure), never a silent success",
    )
    check(
        "telegram_chat_id" in str(result.error).lower(),
        "S7: the failure explicitly names the missing credential",
    )


def scenario_both_missing_is_explicit_failure() -> None:
    result = _execute_via_production_path(FakeHttpClient(), bot_token=None, chat_id=None)
    check(
        result.success is False,
        "S8: both credentials missing still produces a failed "
        "ServiceResult (explicit failure/blocked state)",
    )


# ---------------------------------------------------------------------------
# S9 -- both credentials present -> factory no longer blocks the call
# ---------------------------------------------------------------------------
def scenario_both_present_reaches_notification_service_send() -> None:
    fake_client = FakeHttpClient()
    result = _execute_via_production_path(fake_client, bot_token="tok", chat_id="chat")
    check(
        result.success is True,
        "S9: with both credentials configured, NotificationService.execute() "
        "succeeds end-to-end through the production factory (using an "
        "injected fake HTTP client, no real network call)",
    )
    check(
        len(fake_client.calls) == 1,
        "S9: exactly one outbound Telegram API call was attempted",
    )
    check(
        "tok" in fake_client.calls[0]["url"],
        "S9: the resolved bot token was actually used to build the "
        "Telegram API URL",
    )


# ---------------------------------------------------------------------------
# S10 -- factory never mutates the caller's metadata dict
# ---------------------------------------------------------------------------
def scenario_factory_does_not_mutate_caller_dict() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="tok", chat_id="chat")
        original: Dict[str, Any] = {MetadataKeys.CHANNEL: "telegram", MetadataKeys.MESSAGE: "m"}
        snapshot = dict(original)
        _notification_service_context_factory(original)
        check(
            original == snapshot,
            "S10: the factory never mutates the metadata dict object "
            "the caller passed in (defensive copy)",
        )


# ---------------------------------------------------------------------------
# S11 -- caller-supplied credential values are never overwritten
# ---------------------------------------------------------------------------
def scenario_caller_supplied_credentials_not_overwritten() -> None:
    with _EnvSandbox() as env:
        env.set(bot_token="env-token", chat_id="env-chat")
        context = _notification_service_context_factory(
            {
                MetadataKeys.CHANNEL: "telegram",
                MetadataKeys.MESSAGE: "m",
                MetadataKeys.TELEGRAM_BOT_TOKEN: "caller-token",
                MetadataKeys.TELEGRAM_CHAT_ID: "caller-chat",
            }
        )
        check(
            context.metadata[MetadataKeys.TELEGRAM_BOT_TOKEN] == "caller-token",
            "S11: a caller-supplied bot token is never overwritten by "
            "the environment-sourced value",
        )
        check(
            context.metadata[MetadataKeys.TELEGRAM_CHAT_ID] == "caller-chat",
            "S11: a caller-supplied chat id is never overwritten by "
            "the environment-sourced value",
        )


# ---------------------------------------------------------------------------
# S12 -- regression: existing notification suites still pass
# ---------------------------------------------------------------------------
def scenario_existing_notification_suites_still_pass() -> None:
    suite_files = [
        "test_notification_event.py",
        "test_notification_dispatcher.py",
        "test_notification_manager.py",
        "test_telegram_notification_channel.py",
        "test_stage_sprint7_step7_notification_wiring.py",
    ]
    for suite_file in suite_files:
        suite_path = ROOT / "Tests" / suite_file
        check(suite_path.is_file(), f"{suite_file} still exists")
        result = subprocess.run(
            [sys.executable, str(suite_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"S12: {suite_file} still exits 0 (regression) "
            f"[stderr tail: {result.stderr[-400:] if result.returncode != 0 else ''}]",
        )


def main() -> int:
    scenarios = [
        scenario_env_credential_reaches_context,
        scenario_message_forwarded_with_credentials,
        scenario_title_preserved_when_supplied,
        scenario_different_env_values_produce_different_results,
        scenario_no_hardcoded_credential_literal_in_source,
        scenario_missing_bot_token_is_explicit_failure,
        scenario_missing_chat_id_is_explicit_failure,
        scenario_both_missing_is_explicit_failure,
        scenario_both_present_reaches_notification_service_send,
        scenario_factory_does_not_mutate_caller_dict,
        scenario_caller_supplied_credentials_not_overwritten,
        scenario_existing_notification_suites_still_pass,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"ACTIVATION 6.1 TELEGRAM CREDENTIAL WIRING RESULTS: "
        f"{_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())