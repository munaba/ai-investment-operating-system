from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderRequirement:
    """A capability requirement a caller wants satisfied by *some* provider.

    Stage L3 addition. Callers (a ``Planner``, an ``Agent``, or any other
    future caller) state *what they need*, never *which provider they
    want* -- :class:`~Providers.provider_selector.ProviderSelector`
    resolves the requirement to a concrete provider by reading
    :attr:`~Providers.base_provider.BaseProvider.capabilities`, never by
    name.

    Every field defaults to "not required", so
    ``ProviderRequirement()`` (no arguments) matches every provider --
    the empty requirement.

    Attributes:
        need_images: Require ``capabilities.supports_images``.
        need_stream: Require ``capabilities.supports_stream``.
        need_reasoning: Require ``capabilities.supports_reasoning``.
        need_json: Require ``capabilities.supports_json``.
        offline_required: Require a provider that can function without
            an internet connection. Currently checked via
            ``capabilities.is_local`` (see
            :mod:`Providers.provider_selector` module docstring for the
            documented limitation this implies).
        local_only: Require a provider that talks to a locally-hosted
            model (``capabilities.is_local``), e.g. for data-locality
            or privacy reasons.
        minimum_context_tokens: Require
            ``capabilities.max_context_tokens`` to be known and at
            least this large. A provider whose context window is
            unknown (``None``) is treated as *not* satisfying this --
            an unverified context window cannot be guaranteed
            sufficient.
    """

    need_images: bool = False
    need_stream: bool = False
    need_reasoning: bool = False
    need_json: bool = False
    offline_required: bool = False
    local_only: bool = False
    minimum_context_tokens: Optional[int] = None