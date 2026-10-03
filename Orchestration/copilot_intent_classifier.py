"""CopilotIntentClassifier -- Phase F, Task 3: deterministic
classification of a user utterance into the existing closed
``CopilotIntent`` enum (Task 2).

Scope note (LOCKED for this task): this module introduces exactly one
thing -- ``CopilotIntentClassifier``, a pure, stateless, keyword-based
classifier that maps free-form text to a single ``CopilotIntent``
member. Nothing else.

Explicitly NOT part of this task: an LLM/provider call, a database
lookup, a tool/skill invocation, memory reads or writes, execution of
the classified intent, or any side effect of any kind. This mirrors
``Orchestration.instrument_extractor.BaseInstrumentExtractor`` /
``IDXTickerExtractor`` (a pure ``strategy``-style extractor operating
only on its ``text`` argument, raising rather than guessing on
ambiguity) and the deterministic, template/keyword-only construction
style already used in ``Orchestration.text_analysis_skill.
TextAnalysisSkill`` -- no AI, no natural-language generation, no
external call of any kind.

Classification never raises on ambiguous/unknown input (unlike
``IDXTickerExtractor.extract``, which raises ``ValueError``): the
copilot contract (Phase F, Task 1) requires that unsupported or
ambiguous input resolve to ``CopilotIntent.UNSUPPORTED`` rather than
propagate an exception or silently default to a financial action.
``classify()`` therefore has exactly one return type
(``CopilotIntent``) and never throws for any ``str`` input, including
``""``.

Dependency direction: this module imports only the stdlib ``re``
module plus ``Orchestration.copilot_intent.CopilotIntent`` (Task 2).
It does not import from, and is not imported by, any ``Providers``,
``Orchestration.base_tool``, ``Orchestration.base_skill``,
``Orchestration.memory``, ``Orchestration.tool_permission``,
``Orchestration.permission_context``, ``Core.composition_root``, or
Telegram module. It is additive-only, standing on its own until a
future task wires it into a copilot-facing skill.
"""

from __future__ import annotations

import re
from typing import Sequence, Tuple

from Orchestration.copilot_intent import CopilotIntent


class CopilotIntentClassifier:
    """Pure, stateless, deterministic classifier from free-form text to
    ``CopilotIntent``.

    Holds no mutable state and no collaborators -- construction takes
    no arguments and every call to :meth:`classify` depends only on
    its ``utterance`` argument. This is a keyword/pattern match over
    normalized text, not a model: given the same input it always
    returns the same ``CopilotIntent`` member, and it never calls a
    provider, a tool, a database, or any other component. It only
    classifies -- it never executes the intent it returns.

    Matching is deliberately conservative: an utterance must contain
    at least one keyword/phrase associated with exactly one intent
    category to be classified as that intent. An utterance matching
    keywords from more than one category, or matching none, is
    classified as ``CopilotIntent.UNSUPPORTED`` -- ambiguity is never
    resolved by guessing, and there is no fallback to any financial
    action.
    """

    # Each pattern is matched against the normalized (lower-cased,
    # whitespace-collapsed) utterance with a word-boundary-aware
    # substring search. Patterns are plain literals, not full regex
    # DSL, kept deliberately simple and auditable -- no external
    # keyword list, no configuration file, no learned weights.
    _EXPLAIN_DECISION_PATTERNS: Tuple[str, ...] = (
        "why did",
        "why was",
        "why is",
        "explain the decision",
        "explain that decision",
        "explain this decision",
        "explain why",
        "reason for the trade",
        "reason behind",
        "kenapa",
        "mengapa",
        "jelaskan keputusan",
        "alasan keputusan",
    )

    _SUMMARIZE_PORTFOLIO_PATTERNS: Tuple[str, ...] = (
        "summarize my portfolio",
        "summarize portfolio",
        "portfolio summary",
        "portfolio performance",
        "how is my portfolio",
        "how's my portfolio",
        "ringkasan portofolio",
        "performa portofolio",
    )

    _RECALL_PREFERENCE_PATTERNS: Tuple[str, ...] = (
        "what did i say",
        "what did i tell you",
        "what do i prefer",
        "what is my preference",
        "what are my preferences",
        "recall my preference",
        "remember my preference",
        "what did we decide",
        "preferensi saya",
        "apa yang saya bilang",
    )

    _ASK_STATUS_PATTERNS: Tuple[str, ...] = (
        "what is the status",
        "what's the status",
        "current status",
        "system status",
        "is the scheduler running",
        "is it running",
        "status hari ini",
        "status sistem",
    )

    def classify(self, utterance: str) -> CopilotIntent:
        """Deterministically classify ``utterance`` into a single
        ``CopilotIntent`` member.

        This method only classifies -- it never executes a tool,
        reads or writes memory, calls a provider, or performs any
        other side effect. It always returns a ``CopilotIntent`` and
        never raises for any ``str`` (or ``None``-like falsy) input.

        Args:
            utterance: Free-form user text. May be empty, ``None``,
                mixed-case, or contain irregular whitespace -- all
                are normalized before matching.

        Returns:
            The single matching ``CopilotIntent`` member, or
            ``CopilotIntent.UNSUPPORTED`` if zero or more than one
            intent category's keywords are found.
        """
        normalized = self._normalize(utterance)
        if not normalized:
            return CopilotIntent.UNSUPPORTED

        matched_intents = set()

        if self._matches_any(normalized, self._EXPLAIN_DECISION_PATTERNS):
            matched_intents.add(CopilotIntent.EXPLAIN_DECISION)
        if self._matches_any(normalized, self._SUMMARIZE_PORTFOLIO_PATTERNS):
            matched_intents.add(CopilotIntent.SUMMARIZE_PORTFOLIO)
        if self._matches_any(normalized, self._RECALL_PREFERENCE_PATTERNS):
            matched_intents.add(CopilotIntent.RECALL_PREFERENCE)
        if self._matches_any(normalized, self._ASK_STATUS_PATTERNS):
            matched_intents.add(CopilotIntent.ASK_STATUS)

        if len(matched_intents) == 1:
            return next(iter(matched_intents))

        # Zero matches (unrecognized input) or more than one matched
        # category (genuinely ambiguous input) both resolve the same
        # way: UNSUPPORTED. There is no partial credit, no priority
        # ordering between categories, and no default to a financial
        # action.
        return CopilotIntent.UNSUPPORTED

    @staticmethod
    def _normalize(utterance: str) -> str:
        """Lower-case and collapse whitespace in ``utterance``.

        Treats ``None`` and non-``str`` input the same as an empty
        string rather than raising -- ``classify()`` must never throw
        on malformed input, only ever return ``UNSUPPORTED``.

        Args:
            utterance: Raw input text, possibly ``None`` or malformed.

        Returns:
            A lower-cased string with all runs of whitespace collapsed
            to a single space and leading/trailing whitespace
            stripped. Empty if ``utterance`` was falsy or not a
            ``str``.
        """
        if not isinstance(utterance, str) or not utterance.strip():
            return ""
        return re.sub(r"\s+", " ", utterance.strip().lower())

    @staticmethod
    def _matches_any(normalized_utterance: str, patterns: Sequence[str]) -> bool:
        """Return ``True`` if any literal in ``patterns`` is a substring
        of ``normalized_utterance``.

        Args:
            normalized_utterance: Already-normalized (lower-cased,
                whitespace-collapsed) text.
            patterns: Literal substrings to search for, already
                lower-cased at declaration time.

        Returns:
            ``True`` if at least one pattern is found, else ``False``.
        """
        return any(pattern in normalized_utterance for pattern in patterns)