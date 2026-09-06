"""Stage L3 -- Intelligent Provider Selection.

``ProviderSelector`` resolves a :class:`ProviderRequirement` to a
concrete :class:`~Providers.base_provider.BaseProvider` by reading each
registered provider's :attr:`~Providers.base_provider.BaseProvider.capabilities`
-- never its name or class. Adding a third/fourth provider (OpenAI,
Anthropic, LM Studio, ...) requires *zero* changes here: as long as it
registers with ``ProviderManager`` and declares a ``capabilities``
property, it is automatically eligible.

Documented modeling limitation (see also ``requirement.py``):
``ProviderRequirement.offline_required`` and ``.local_only`` are both
currently checked against the single ``capabilities.is_local`` flag.
Stage L2's capability model has no field that distinguishes "runs
without any external process" from "runs without internet access" --
those are two different real-world properties that happen to collapse
onto the same provider in this codebase today (Ollama is both local and
offline-capable). If a future provider is local but still requires
network access (e.g. a LAN-hosted service with a separate license
server), this collapsing would need to be revisited by giving
``ProviderCapabilities`` two separate fields instead of one -- not done
here, to keep this stage's change surface minimal.
"""

from __future__ import annotations

from typing import List, Tuple

from Core.exceptions import ProviderError
from Core.logger import get_logger

from .base_provider import BaseProvider
from .capabilities import ProviderCapabilities
from .provider_manager import ProviderManager
from .requirement import ProviderRequirement

logger = get_logger(__name__)


def _meets_requirement(capabilities: ProviderCapabilities, requirement: ProviderRequirement) -> bool:
    """Return whether ``capabilities`` satisfies every field ``requirement`` sets.

    Pure function over two dataclasses -- no provider name or class is
    ever inspected.

    Args:
        capabilities: The candidate provider's declared capabilities.
        requirement: The caller's stated requirement.

    Returns:
        ``True`` if every requirement field the caller turned on is
        satisfied by ``capabilities``, else ``False``.
    """
    if requirement.need_images and not capabilities.supports_images:
        return False
    if requirement.need_stream and not capabilities.supports_stream:
        return False
    if requirement.need_reasoning and not capabilities.supports_reasoning:
        return False
    if requirement.need_json and not capabilities.supports_json:
        return False
    if requirement.offline_required and not capabilities.is_local:
        return False
    if requirement.local_only and not capabilities.is_local:
        return False
    if requirement.minimum_context_tokens is not None:
        if capabilities.max_context_tokens is None:
            return False
        if capabilities.max_context_tokens < requirement.minimum_context_tokens:
            return False
    return True


def _score(capabilities: ProviderCapabilities, requirement: ProviderRequirement) -> Tuple[int, int]:
    """Score a candidate that already passed :func:`_meets_requirement`.

    A simple, explicit, two-tier score (documented, not hidden):

    1. **Primary**: a point for each optional capability the provider
       happens to support (images, reasoning, json, stream, embeddings),
       plus one more point if ``requirement.local_only`` was asked for
       and the provider is local -- rewarding the trait the caller
       explicitly cared about, on top of the hard filter already
       applied in :func:`_meets_requirement`.
    2. **Secondary (tiebreaker)**: larger ``max_context_tokens`` wins;
       unknown (``None``) is treated as ``0``.

    Args:
        capabilities: The candidate provider's declared capabilities.
        requirement: The caller's stated requirement (used only for the
            ``local_only`` bonus above; every other field was already
            enforced as a hard filter before scoring runs).

    Returns:
        A ``(primary, secondary)`` tuple; higher sorts better under
        normal tuple comparison.
    """
    primary = 0
    if capabilities.supports_images:
        primary += 1
    if capabilities.supports_reasoning:
        primary += 1
    if capabilities.supports_json:
        primary += 1
    if capabilities.supports_stream:
        primary += 1
    if capabilities.supports_embeddings:
        primary += 1
    if requirement.local_only and capabilities.is_local:
        primary += 1

    secondary = capabilities.max_context_tokens or 0
    return (primary, secondary)


class ProviderSelector:
    """Chooses the best-fit registered provider for a stated requirement.

    Example:
        >>> selector = ProviderSelector(provider_manager)
        >>> requirement = ProviderRequirement(need_images=True, need_reasoning=True)
        >>> provider = selector.select(requirement)
    """

    def __init__(self, provider_manager: ProviderManager) -> None:
        """Initialize the selector against an existing registry.

        Args:
            provider_manager: The :class:`~Providers.provider_manager.ProviderManager`
                to read registered providers from. Not defaulted to the
                module-level singleton, to keep this class trivially
                testable against an isolated registry.
        """
        self._provider_manager = provider_manager

    def candidates(self, requirement: ProviderRequirement) -> List[BaseProvider]:
        """Return every registered provider that satisfies ``requirement``.

        Args:
            requirement: The capability requirement to filter by.

        Returns:
            Providers satisfying every field ``requirement`` turned on,
            in ``ProviderManager.list()`` (registration) order. May be
            empty.
        """
        matches: List[BaseProvider] = []
        for name in self._provider_manager.list():
            provider = self._provider_manager.get(name)
            if _meets_requirement(provider.capabilities, requirement):
                matches.append(provider)
        return matches

    def select(self, requirement: ProviderRequirement) -> BaseProvider:
        """Select the best-fit registered provider for ``requirement``.

        Args:
            requirement: The capability requirement to satisfy.

        Returns:
            The highest-scoring provider among those satisfying
            ``requirement`` (see :func:`_score` for the scoring rule).
            Ties keep the first-registered candidate, so selection is
            deterministic given a fixed registration order.

        Raises:
            ProviderError: If no registered provider satisfies
                ``requirement``.
        """
        matches = self.candidates(requirement)
        if not matches:
            raise ProviderError(
                "No registered provider satisfies the given ProviderRequirement.",
                details={"requirement": requirement},
            )

        best = matches[0]
        best_score = _score(best.capabilities, requirement)
        for provider in matches[1:]:
            score = _score(provider.capabilities, requirement)
            if score > best_score:
                best = provider
                best_score = score

        logger.debug(
            f"ProviderSelector: selected '{best.name}' "
            f"(score={best_score}, candidates={[p.name for p in matches]})"
        )
        return best