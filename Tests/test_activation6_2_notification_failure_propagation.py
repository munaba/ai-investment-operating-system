"""
Activation 6.2 proof suite -- notification failure propagation.

Target: if ``Services.notification_service.NotificationService.
execute(context)`` returns a ``ServiceResult`` with ``success ==
False``, every caller in the production notification chain
(``Business.telegram_notification_channel.TelegramNotificationChannel.
send()`` -> ``Business.notification_dispatcher.NotificationDispatcher.
dispatch()`` -> ``Business.notification_manager.NotificationManager.
notify()``) must treat that as a FAILED notification -- never a silent
success.

Explicitly out of scope / unchanged by this STEP:
  * ``Services/notification_service.py`` -- its contract (still
    returns a ``ServiceResult``, still never raises) is untouched.
  * Telegram message/caption format (``NotificationService._send_telegram``)
    -- untouched.
  * No new ``NotificationEventType`` / event added.
  * Discord/email/multi-channel -- untouched, not exercised here.
  * No scheduler/background worker/autonomous execution added.
  * Trading state (``Order``/``Trade``/``Position``/``Account``) --
    proven unaffected by a failed notification (Scenario 5).

Uses the REAL production path: a real, temporary SQLite database via
``Core.init_command.run_init`` + ``Core.composition_root.
build_application()``, so ``graph.notification_manager`` /
``graph.notification_dispatcher`` / ``graph.telegram_notification_channel``
are the exact same wired objects a real deployment would use. The only
thing substituted is the outbound HTTP transport
(``NotificationService``'s injected ``http_client``, its own
documented dependency-injection seam -- see that module's docstring)
so this suite never makes a real network call; Telegram credentials
themselves come from the real ``Core.config`` env-var path established
in Activation 6.1, never hard-coded here as literal test-only values
with production significance.

Scenario coverage:
    1. Notification success -> caller (notify()) treats it as
       succeeded: returns normally, no exception.
    2. Notification failure -> caller (notify()) treats it as failed:
       raises, does not return normally.
    3. Failure reason/message is still knowable from the raised
       exception (not swallowed into an opaque generic error).
    4. No silent success: a failing NotificationService.execute()
       never results in notify()/dispatch()/send() returning
       normally.
    5. A failed notification never mutates Order/Trade/Position/
       Account state (real repositories, real DB, before/after
       snapshot).
    6. Regression: notification test suites + Activation 5/6.1 proof
       suites still pass (invoked as subprocesses).

Run directly:
``python Tests/test_activation6_2_notification_failure_propagation.py``
-- no external test framework required.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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


class FakeHttpClient:
    """requests-compatible double. ``mode`` controls the outcome:
    'success' -> Telegram-shaped ok response; 'http_failure' -> a
    Telegram-shaped error response (used to prove a *business*
    failure -- not a raised exception -- still propagates)."""

    class _Response:
        def __init__(self, status_code: int, body: Dict[str, Any]) -> None:
            self.status_code = status_code
            self._body = body

        def json(self) -> Dict[str, Any]:
            return self._body

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.calls: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> "FakeHttpClient._Response":
        self.calls.append({"url": url, **kwargs})
        if self.mode == "success":
            return self._Response(200, {"ok": True, "result": {"message_id": 1}})
        return self._Response(400, {"ok": False, "description": "chat not found"})


class _EnvSandbox:
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


def _build_graph(tmp_dir: str):
    """Build a real ApplicationGraph over a fresh, temporary SQLite DB."""
    db_path = Path(tmp_dir) / "activation6_2.db"
    os.environ["DB_PATH"] = str(db_path)

    from Core.composition_root import build_application
    from Core.init_command import run_init

    rc = run_init()
    check(rc == 0, "run_init() exited 0 on a brand-new database (setup)")
    graph = build_application(
        provider_name="gemini-activation6-2-test",
        agent_name="activation6-2-test-agent",
    )
    return graph


def _make_event(message: str = "Activation 6.2 test message"):
    from Business.notification_event import NotificationEvent, NotificationEventType

    return NotificationEvent(
        event_type=NotificationEventType.NEW_SIGNAL,
        timestamp="2026-08-13T00:00:00Z",
        title="Test",
        message=message,
        metadata={},
    )


def _snapshot_trading_state(graph) -> Dict[str, Any]:
    account = graph.account_repository.get_by_id("paper")
    return {
        "cash": account.cash if account else None,
        "equity": account.equity if account else None,
        "buying_power": account.buying_power if account else None,
        "orders": [o.order_id for o in graph.order_repository.list_by_account("paper")],
        "trades": [t.trade_id for t in graph.trade_repository.list_by_account("paper")],
        "positions": [
            (p.position_id, p.status) for p in graph.position_repository.list_by_account("paper")
        ],
    }


# ---------------------------------------------------------------------------
# Scenario 1 -- success is treated as success (no exception, normal return)
# ---------------------------------------------------------------------------
def scenario_success_is_treated_as_success() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        env.set(bot_token="tok-ok", chat_id="chat-ok")
        graph = _build_graph(tmp_dir)
        graph.telegram_notification_channel._notification_service._http_client = FakeHttpClient(
            mode="success"
        )

        raised: Optional[Exception] = None
        returned = "not-called"
        try:
            returned = graph.notification_manager.notify(_make_event())
        except Exception as exc:  # noqa: BLE001
            raised = exc

        check(
            raised is None,
            "S1: notify() does not raise when NotificationService.execute() "
            "succeeds",
        )
        check(
            returned is None,
            "S1: notify() returns None (its LOCKED contract) on success -- "
            "caller observes normal completion",
        )


# ---------------------------------------------------------------------------
# Scenario 2 -- failure is treated as failure (raises, does not return)
# ---------------------------------------------------------------------------
def scenario_failure_is_treated_as_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        # Missing bot token -> NotificationService._require_credential
        # raises internally -> execute() returns a failed ServiceResult.
        env.set(bot_token=None, chat_id="chat-ok")
        graph = _build_graph(tmp_dir)
        graph.telegram_notification_channel._notification_service._http_client = FakeHttpClient(
            mode="success"
        )

        raised: Optional[Exception] = None
        try:
            graph.notification_manager.notify(_make_event())
        except Exception as exc:  # noqa: BLE001
            raised = exc

        check(
            raised is not None,
            "S2: notify() raises when NotificationService.execute() "
            "returns a failed ServiceResult -- caller treats it as failed",
        )


def scenario_business_level_failure_also_propagates() -> None:
    """Not just missing-credential failures -- a business-level Telegram
    API failure (e.g. 'chat not found') must propagate identically,
    proving this isn't special-cased to the credential-missing path."""
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        env.set(bot_token="tok-ok", chat_id="chat-ok")
        graph = _build_graph(tmp_dir)
        graph.telegram_notification_channel._notification_service._http_client = FakeHttpClient(
            mode="http_failure"
        )

        raised: Optional[Exception] = None
        try:
            graph.notification_dispatcher.dispatch(_make_event())
        except Exception as exc:  # noqa: BLE001
            raised = exc

        check(
            raised is not None,
            "S2b: a Telegram API-level failure (ok=False) also raises "
            "through dispatch(), not just a missing-credential failure",
        )
        check(
            "chat not found" in str(raised).lower(),
            "S2b: the API-level failure reason is preserved in the "
            "raised exception",
        )


# ---------------------------------------------------------------------------
# Scenario 3 -- failure reason is still knowable
# ---------------------------------------------------------------------------
def scenario_failure_reason_is_knowable() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        env.set(bot_token=None, chat_id=None)
        graph = _build_graph(tmp_dir)

        raised: Optional[Exception] = None
        try:
            graph.telegram_notification_channel.send(_make_event())
        except Exception as exc:  # noqa: BLE001
            raised = exc

        check(raised is not None, "S3: send() raised as expected")
        check(
            "telegram_bot_token" in str(raised).lower(),
            "S3: the raised exception's message identifies exactly which "
            "credential was missing -- the failure reason is knowable, "
            "not opaque",
        )
        from Services.notification_service import NotificationServiceError

        check(
            isinstance(raised, NotificationServiceError),
            "S3: the raised exception is the same NotificationServiceError "
            "type NotificationService itself uses -- not a re-wrapped, "
            "generic error that hides the original type",
        )


# ---------------------------------------------------------------------------
# Scenario 4 -- no silent success anywhere in the chain
# ---------------------------------------------------------------------------
def scenario_no_silent_success_at_any_layer() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        env.set(bot_token=None, chat_id="chat-ok")
        graph = _build_graph(tmp_dir)

        event = _make_event()

        send_raised = False
        try:
            graph.telegram_notification_channel.send(event)
        except Exception:  # noqa: BLE001
            send_raised = True
        check(send_raised, "S4: TelegramNotificationChannel.send() does not silently succeed")

        dispatch_raised = False
        try:
            graph.notification_dispatcher.dispatch(event)
        except Exception:  # noqa: BLE001
            dispatch_raised = True
        check(dispatch_raised, "S4: NotificationDispatcher.dispatch() does not silently succeed")

        notify_raised = False
        try:
            graph.notification_manager.notify(event)
        except Exception:  # noqa: BLE001
            notify_raised = True
        check(notify_raised, "S4: NotificationManager.notify() does not silently succeed")


# ---------------------------------------------------------------------------
# Scenario 5 -- failed notification never mutates trading state
# ---------------------------------------------------------------------------
def scenario_failure_does_not_mutate_trading_state() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir, _EnvSandbox() as env:
        env.set(bot_token=None, chat_id=None)
        graph = _build_graph(tmp_dir)

        before = _snapshot_trading_state(graph)

        try:
            graph.notification_manager.notify(_make_event())
        except Exception:  # noqa: BLE001
            pass  # expected -- Scenario 2 already proves this raises

        after = _snapshot_trading_state(graph)

        check(
            before == after,
            "S5: Account cash/equity/buying_power and the set of "
            "Order/Trade/open-Position ids are byte-for-byte identical "
            "before and after a failed notification -- no trading state "
            f"mutation (before={before}, after={after})",
        )


def scenario_no_trading_imports_in_notification_layer() -> None:
    """Static/AST-adjacent belt-and-suspenders check: none of the three
    notification-layer modules import Repository/Database at all, so
    they have no way to touch trading state even indirectly."""
    import ast

    for rel_path in (
        "Business/telegram_notification_channel.py",
        "Business/notification_dispatcher.py",
        "Business/notification_manager.py",
    ):
        source = (_PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        violations = [
            m for m in imported if "repository" in m.lower() or "database" in m.lower()
        ]
        check(
            len(violations) == 0,
            f"S5b: {rel_path} imports no Repository/Database module "
            f"(found: {violations})",
        )


# ---------------------------------------------------------------------------
# Scenario 6 -- regression
# ---------------------------------------------------------------------------
def scenario_regression_suites_still_pass() -> None:
    suite_files = [
        "test_notification_event.py",
        "test_notification_dispatcher.py",
        "test_notification_manager.py",
        "test_telegram_notification_channel.py",
        "test_stage_sprint7_step7_notification_wiring.py",
        "test_activation6_1_telegram_credential_wiring.py",
        "test_activation5_6_wiring.py",
        "activation5_6_acceptance_proof.py",
    ]
    for suite_file in suite_files:
        suite_path = _PROJECT_ROOT / "Tests" / suite_file
        check(suite_path.is_file(), f"{suite_file} still exists")
        result = subprocess.run(
            [sys.executable, str(suite_path)],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"S6: {suite_file} still exits 0 (regression) "
            f"[stderr tail: {result.stderr[-400:] if result.returncode != 0 else ''}]",
        )


def main() -> int:
    scenarios = [
        scenario_success_is_treated_as_success,
        scenario_failure_is_treated_as_failure,
        scenario_business_level_failure_also_propagates,
        scenario_failure_reason_is_knowable,
        scenario_no_silent_success_at_any_layer,
        scenario_failure_does_not_mutate_trading_state,
        scenario_no_trading_imports_in_notification_layer,
        scenario_regression_suites_still_pass,
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
        f"ACTIVATION 6.2 NOTIFICATION FAILURE PROPAGATION RESULTS: "
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