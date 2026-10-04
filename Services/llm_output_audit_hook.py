"""LLM output audit hook -- wires every LLM narration into the
``llm_output_audit`` table (Database/migrations_llm_output_audit.py,
Repository/persistence/llm_output_audit_repository.py).

Used by ``Services.copilot_explanation_llm_narrator.narrate_explanation``
for the one production call site (``provider.generate``). Design rules:

- Additive: the hook is optional (``repo=None`` means "no audit sink
  wired"), so existing callers keep working unchanged.
- Fail visible: a repository failure never blocks narration (the
  deterministic summary must still reach the user), but it is printed
  to stderr so the gap shows up in logs instead of vanishing.
- No fabrication: fields that are unknown (tokens, latency) are passed
  through as ``None`` -- never guessed.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from Providers.message import Message
from Repository.persistence.llm_output_audit_repository import LlmOutputAuditRepository


def prompt_hash(messages: Sequence[Message]) -> str:
    """Stable sha256 over the serialized prompt messages."""
    blob = "\n".join(f"{m.role.value}: {m.content}" for m in messages)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record_llm_output(
    repo: Optional[LlmOutputAuditRepository],
    *,
    model: str,
    messages: Sequence[Message],
    response_text: str,
    source_data: str,
    tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Insert one audit row. Returns the row id, or ``None`` when no
    repo was wired or the insert failed (failure printed to stderr)."""
    if repo is None:
        return None
    try:
        return repo.create(
            timestamp=(now or datetime.now(timezone.utc)).isoformat(),
            model=model,
            prompt_hash=prompt_hash(messages),
            source_data=source_data,
            response=response_text,
            tokens=tokens,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # audit must never break narration
        print(f"[llm_audit] insert failed: {exc!r}", file=sys.stderr)
        return None
