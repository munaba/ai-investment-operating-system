"""NotificationDedupPolicy -- Phase D (Proactive IDX Scheduler Routine).

Pure decision logic answering: given the last-known state of one named
alert channel (e.g. ``"session_scan_brief"``, ``"data_freshness"``) and
a freshly computed signature for "what the alert would say right now",
should the scheduler actually send a Telegram message this tick, or
suppress it?

Two independent reasons a candidate alert is suppressed (Phase D
brief: "material SUCCESS changes only" / "no spam"):

1. **No material change** -- the new signature is identical to the
   last one actually sent for this ``alert_type``. Re-sending the same
   conclusion every tick is exactly the spam the brief forbids.
2. **Rate limit** -- even when the signature *did* change, degradation
   / recovery style alerts are additionally rate-limited: this policy
   refuses to send the same ``alert_type`` again inside
   ``min_interval_seconds`` of its last send, regardless of signature,
   so a flapping data source cannot page the operator every tick.

This module never sends anything itself and never touches persistence
directly -- it is handed the *previous* dedup state (as loaded by the
caller from ``Repository.persistence.notification_dedup_repository.
NotificationDedupRepository``) and returns a decision; the caller is
responsible for persisting the new state after actually sending (or
not).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

SEND: str = "SEND"
SUPPRESS_NO_CHANGE: str = "SUPPRESS_NO_CHANGE"
SUPPRESS_RATE_LIMITED: str = "SUPPRESS_RATE_LIMITED"


@dataclass(frozen=True)
class DedupState:
    """Previously persisted state for one ``alert_type``.

    Attributes:
        alert_type: Stable identifier for this alert channel.
        last_signature: The signature of the last alert actually sent
            (``None`` if never sent).
        last_sent_at: ISO-8601 timestamp of the last actual send
            (``None`` if never sent).
    """

    alert_type: str
    last_signature: Optional[str]
    last_sent_at: Optional[str]


@dataclass(frozen=True)
class DedupDecision:
    """The outcome of evaluating one candidate alert.

    Attributes:
        action: One of ``SEND``/``SUPPRESS_NO_CHANGE``/
            ``SUPPRESS_RATE_LIMITED``.
        should_send: Convenience flag, ``True`` iff ``action == SEND``.
        reason: One-line human-readable explanation, for audit
            logging.
    """

    action: str
    should_send: bool
    reason: str


def _parse_iso8601(value: str) -> datetime:
    from datetime import timezone as _timezone

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone.utc)
    return parsed


@dataclass(frozen=True)
class NotificationDedupPolicy:
    """Decides SEND vs SUPPRESS for one candidate alert.

    Attributes:
        min_interval_seconds: Minimum time that must have elapsed
            since the last actual send of the *same* ``alert_type``
            before a same-type alert is allowed to send again, even if
            its signature changed. Rate limiting only ever makes a
            SEND decision stricter -- it can never turn a no-change
            case into a send.
    """

    min_interval_seconds: float

    def evaluate(
        self,
        *,
        state: Optional[DedupState],
        new_signature: str,
        now: datetime,
    ) -> DedupDecision:
        """Decide whether a candidate alert with ``new_signature``
        should be sent.

        Args:
            state: The previously persisted ``DedupState`` for this
                ``alert_type``, or ``None`` if this is the first time
                this alert type has ever been evaluated.
            new_signature: A caller-computed, deterministic string
                summarizing "what this alert would say right now" --
                e.g. a hash of the material fields of a scan brief, or
                a literal ``"DEGRADED"``/``"RECOVERED"`` for a
                freshness alert. Equal signatures across ticks mean
                "nothing material changed".
            now: The evaluation moment (timezone-aware).

        Returns:
            A ``DedupDecision``. ``SEND`` is returned only when there
            is either no prior state, or the signature genuinely
            changed AND the rate-limit window has elapsed.
        """
        if state is None or state.last_signature is None:
            return DedupDecision(
                action=SEND,
                should_send=True,
                reason="no prior alert of this type has ever been sent",
            )

        if new_signature == state.last_signature:
            return DedupDecision(
                action=SUPPRESS_NO_CHANGE,
                should_send=False,
                reason="signature unchanged since the last sent alert",
            )

        if state.last_sent_at is not None and self.min_interval_seconds > 0:
            elapsed = (now - _parse_iso8601(state.last_sent_at)).total_seconds()
            if elapsed < self.min_interval_seconds:
                return DedupDecision(
                    action=SUPPRESS_RATE_LIMITED,
                    should_send=False,
                    reason=(
                        f"signature changed but only {elapsed:.0f}s elapsed "
                        f"since the last send (< {self.min_interval_seconds:.0f}s "
                        f"rate limit)"
                    ),
                )

        return DedupDecision(
            action=SEND,
            should_send=True,
            reason="signature changed and rate-limit window has elapsed",
        )


#: Default minimum interval between two same-``alert_type`` sends.
#: 30 minutes -- long enough that a flapping provider cannot page more
#: than twice an hour, short enough that a genuine recovery is still
#: reported the same trading session.
DEFAULT_MIN_INTERVAL_SECONDS: float = 1800.0


def load_notification_dedup_policy(env_get=None) -> NotificationDedupPolicy:
    """Build a ``NotificationDedupPolicy`` from
    ``NOTIFICATION_MIN_INTERVAL_SECONDS`` (defaults to
    ``DEFAULT_MIN_INTERVAL_SECONDS`` when unset or non-positive).
    """
    if env_get is None:
        from Core.config import config as _config

        env_get = _config.get_float
    interval = env_get("NOTIFICATION_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)
    if interval is None or interval < 0:
        interval = DEFAULT_MIN_INTERVAL_SECONDS
    return NotificationDedupPolicy(min_interval_seconds=float(interval))