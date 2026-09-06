"""CopilotExplanationLlmNarrator -- Phase F, Task 6: optionally rephrase
an already-computed ``CopilotExplanationResult`` (Task 4) in natural
language via an injected ``BaseProvider``.

Scope note (LOCKED for this task): this module introduces exactly one
thing -- ``narrate_explanation``, a small function that turns an
existing ``CopilotExplanationResult`` plus an injected
``Providers.base_provider.BaseProvider`` into a single ``str``. Nothing
else.

This is purely a rewording layer over state Task 4 already computed.
It never makes a new decision, never suggests a different action, and
never invents a number, price, timestamp, or piece of evidence beyond
what ``CopilotExplanationResult`` already carries -- the system prompt
built here explicitly instructs the model not to. If the provider is
unavailable, fails, or returns nothing useful, this function returns
``result.summary`` (Task 4's own deterministic, template-built text)
unchanged -- the LLM path is optional narration on top of an answer
that already exists, never a replacement for it.

Explicitly NOT part of this task: intent classification (Task 3 already
covers that, deterministically, with no provider call), a database
read/write, a Telegram side effect, a tool invocation, a memory
read/write, Composition Root wiring, or provider-manager lookup --
the caller is responsible for resolving a ``BaseProvider`` (e.g. via
``Providers.provider_manager.provider_manager.get("ollama")``) and
injecting it; this module never imports ``provider_manager`` or
``Core.composition_root`` itself.

Dependency direction: this module imports only the stdlib
``typing`` module, ``Core.exceptions.ProviderError``,
``Providers.base_provider.BaseProvider``,
``Providers.message.Message``/``MessageRole``, and
``Services.copilot_explanation_service.CopilotExplanationResult``. It
does not import from, and is not imported by,
``Providers.provider_manager``, ``Core.composition_root``, any
Telegram module, ``Orchestration.memory``, or any tool/skill module.
It is additive-only, standing on its own until a future task wires it
behind a copilot-facing entry point.
"""

from __future__ import annotations

from typing import Optional

from Core.exceptions import ProviderError
from Providers.base_provider import BaseProvider
from Providers.message import Message, MessageRole
from Services.copilot_explanation_service import CopilotExplanationResult

#: Fixed system instruction. Deliberately explicit about all four
#: constraints this task requires -- rephrase only, no new decision,
#: no alternative action, no fabricated numbers/evidence -- so the
#: model is told the boundary directly rather than it being implied.
_SYSTEM_INSTRUCTION = (
    "You are a copilot that rephrases an already-decided, deterministic "
    "trading-system explanation into clear, natural language for a "
    "human reader.\n\n"
    "Rules you must follow exactly:\n"
    "1. Rephrase the explanation given below. Do not change its meaning.\n"
    "2. Do not make a new decision. The decision below is already final.\n"
    "3. Do not suggest a different action, trade, or next step.\n"
    "4. Do not invent any number, price, timestamp, or piece of evidence "
    "that is not explicitly given below. If a field below is empty or "
    "missing, do not guess a value for it or imply one exists.\n"
    "5. Respond with plain natural-language text only -- no new headings, "
    "no code, no lists of instructions."
)

#: Default generation options. Kept low-temperature and short, since
#: this is rewording of already-fixed content, not creative generation.
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_MAX_OUTPUT_TOKENS = 300


def _build_user_message(result: CopilotExplanationResult) -> str:
    """Serialize only the existing explanation fields into plain text.

    Includes exactly the five fields this task specifies -- ``title``,
    ``summary``, ``reason``, ``blocked_by``, ``status`` -- and nothing
    else (no ``brief_id``/``symbol``/``source_snapshot_id``/
    ``generated_at``, which Task 4 also carries but which this task
    does not ask to be narrated). A field that is ``None`` on
    ``result`` is rendered as an explicit ``"(none)"`` rather than
    omitted or guessed, so the model is never left to infer a missing
    value.

    Args:
        result: The already-computed ``CopilotExplanationResult`` to
            serialize.

    Returns:
        A fixed-format, multi-line plain-text block containing only
        ``result``'s own field values.
    """

    def _field(value: Optional[str]) -> str:
        return value if value else "(none)"

    return (
        "Explanation to rephrase (do not add anything beyond this):\n"
        f"Title: {_field(result.title)}\n"
        f"Summary: {_field(result.summary)}\n"
        f"Reason: {_field(result.reason)}\n"
        f"Blocked by: {_field(result.blocked_by)}\n"
        f"Status: {_field(result.status)}"
    )


def narrate_explanation(
    result: CopilotExplanationResult,
    provider: BaseProvider,
    *,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    """Rephrase ``result`` via ``provider``, falling back to
    ``result.summary`` on any failure or empty output.

    Builds exactly two messages (a fixed ``SYSTEM`` instruction, then a
    ``USER`` message serializing only ``result``'s own
    title/summary/reason/blocked_by/status fields), calls
    ``provider.generate(messages, temperature=..., max_output_tokens=...)``,
    and returns the generated text on success. Never raises a provider
    failure to the caller: any ``ProviderError``, any other exception
    raised by ``provider.generate``, or a response whose text is empty
    (after stripping whitespace) all fall back to ``result.summary``,
    unchanged, instead.

    Args:
        result: The already-computed ``CopilotExplanationResult``
            (Task 4) to narrate. Never mutated, never used to compute
            a new decision.
        provider: An already-constructed, injected ``BaseProvider``
            (e.g. an ``OllamaProvider`` resolved by the caller). This
            function never constructs or looks up a provider itself.
        temperature: Optional generation temperature forwarded to
            ``provider.generate``. Defaults to a low, non-creative
            value since this is rewording, not free generation.
        max_output_tokens: Optional output length cap forwarded to
            ``provider.generate``.

    Returns:
        The provider's generated text on a successful, non-empty
        response; otherwise ``result.summary`` (Task 4's own
        deterministic text), unchanged.
    """
    messages = [
        Message(role=MessageRole.SYSTEM, content=_SYSTEM_INSTRUCTION),
        Message(role=MessageRole.USER, content=_build_user_message(result)),
    ]

    try:
        response = provider.generate(
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
    except ProviderError:
        return result.summary
    except Exception:
        # Any other failure from an injected provider (e.g. a test
        # double raising a non-ProviderError exception) is treated the
        # same way: the deterministic explanation must never be
        # blocked by an LLM-layer failure of any kind.
        return result.summary

    text = getattr(response, "text", None)
    if not isinstance(text, str) or text.strip() == "":
        return result.summary

    return text