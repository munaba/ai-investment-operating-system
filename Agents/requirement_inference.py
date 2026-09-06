"""Stage L8 -- Automatic Requirement Inference.

``infer_requirement`` is a pure function that maps free-form user text to
an (optional) :class:`~Providers.requirement.ProviderRequirement` via a
simple, explicit keyword match. It has no knowledge of -- and must never
import -- ``Planner``, ``ProviderSelector``, or ``ProviderManager``: this
module only produces a *candidate* requirement. Whether that candidate is
actually usable (i.e. whether any registered provider satisfies it) is
decided elsewhere (see ``Agents.base_agent.BaseAgent.chat``'s Stage L8
probe), never here.

Scope (deliberately narrow, per this stage's approved plan): only three
``ProviderRequirement`` fields are inferred --
``need_images``, ``local_only``, ``need_reasoning``. Every other field
(``need_stream``, ``need_json``, ``offline_required``,
``minimum_context_tokens``) is left at its dataclass default and is never
touched by this module.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from Providers import ProviderRequirement

# Case-insensitive substring keyword lists. Order/content is the entire
# inference policy for this stage -- deliberately simple, not tunable
# scoring, matching the brief's approved keyword set exactly.
_IMAGE_KEYWORDS = ("chart", "png", "gambar", "grafik", "visualisasi", "image")
_LOCAL_KEYWORDS = ("lokal", "local", "offline")
_REASONING_KEYWORDS = ("analisa", "analisis", "reasoning", "saham", "prediksi")


@runtime_checkable
class RequirementInference(Protocol):
    """Abstraction ``BaseAgent`` depends on for requirement inference.

    Stage L9 (additive): decouples ``BaseAgent`` from any one concrete
    inference strategy. ``KeywordRequirementInference`` is the only
    implementation today; the Protocol exists so ``BaseAgent`` never
    imports (or type-checks against) that concrete class directly.
    """

    def infer(self, text: str) -> Optional[ProviderRequirement]:
        """Infer a :class:`ProviderRequirement` from ``text``, or ``None``."""
        ...


class KeywordRequirementInference:
    """Keyword-substring implementation of :class:`RequirementInference`.

    Stage L9 (additive): holds the exact keyword-matching policy that
    previously lived directly in the module-level ``infer_requirement``
    function. No behavior change from Stage L8 -- this is a move, not a
    rewrite. Still has no knowledge of, and must never import, ``Planner``,
    ``ProviderSelector``, or ``ProviderManager``.
    """

    def infer(self, text: str) -> Optional[ProviderRequirement]:
        """Infer a :class:`ProviderRequirement` from ``text`` via keyword matching.

        Pure method: no I/O, no side effects, no dependency on ``Planner``,
        ``ProviderSelector``, or ``ProviderManager``.

        Args:
            text: The raw user input to scan for keywords.

        Returns:
            A :class:`ProviderRequirement` with ``need_images``/``local_only``/
            ``need_reasoning`` set according to which keyword groups matched
            (case-insensitive substring match), or ``None`` if none of the
            three groups matched at all.

            ``None`` is a deliberate, distinct outcome from
            ``ProviderRequirement()`` (the all-``False`` empty requirement):
            callers must treat ``None`` as "inference has no opinion -- use
            the pre-existing name-based path," not as "an empty requirement
            that should still be routed through ``ProviderSelector``." This
            never returns the empty requirement.
        """
        lowered = text.lower()

        need_images = any(keyword in lowered for keyword in _IMAGE_KEYWORDS)
        local_only = any(keyword in lowered for keyword in _LOCAL_KEYWORDS)
        need_reasoning = any(keyword in lowered for keyword in _REASONING_KEYWORDS)

        if not (need_images or local_only or need_reasoning):
            return None

        return ProviderRequirement(
            need_images=need_images,
            local_only=local_only,
            need_reasoning=need_reasoning,
        )


def infer_requirement(text: str) -> Optional[ProviderRequirement]:
    """Compatibility shim retained for Stage L8 regression.

    New production code should depend on ``RequirementInference`` /
    ``KeywordRequirementInference`` instead -- this function is no longer
    the primary production entry point as of Stage L9. It exists solely
    because ``Tests/test_stage_l8_requirement_inference.py`` calls it
    directly and monkeypatches its name on ``Agents.base_agent``; it is
    not called by ``BaseAgent.chat()`` anymore.

    Args:
        text: The raw user input to scan for keywords.

    Returns:
        Identical output to ``KeywordRequirementInference().infer(text)``.
    """
    return KeywordRequirementInference().infer(text)