from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderCapabilities:
    """Static, declarative description of what a provider implementation supports.

    This is pure metadata -- it does not enforce anything by itself and
    does not change how :class:`~Providers.base_provider.BaseProvider`
    methods behave. Callers use it to make decisions (e.g. "should I try
    ``stream()`` on this provider?") without needing to know the
    provider's concrete class or registry name.

    Stage L2 addition (additive only): exists alongside the existing
    ``BaseProvider`` interface. No abstract method changed signature,
    no existing method's behavior changed.

    Attributes:
        supports_stream: Whether ``stream()`` yields real incremental
            chunks rather than raising ``NotImplementedError``.
        supports_tools: Whether the provider's SDK/API accepts tool /
            function-calling definitions.
        supports_json: Whether the provider can be asked to constrain
            output to valid JSON (structured output mode).
        supports_images: Whether the provider accepts image input as
            part of a message.
        supports_reasoning: Whether the provider exposes a distinct
            extended-reasoning / thinking mode.
        supports_embeddings: Whether the provider can produce vector
            embeddings for text.
        max_context_tokens: Maximum combined input+history token budget
            the provider's configured model accepts, if known.
        max_output_tokens: Maximum tokens the provider's configured
            model can generate in a single response, if known.
        is_local: Whether this provider talks to a locally-hosted model
            (e.g. a self-hosted inference server) rather than a remote
            cloud API. Stage L3 addition: this is the one piece of
            *deployment topology* metadata alongside the otherwise
            *model capability* fields above -- it exists so
            ProviderSelector can honor ``local_only``/``offline_required``
            requirements without inspecting a provider's concrete class
            or name. Declared, not measured: a provider that talks to a
            local server is marked ``True`` based on what it is designed
            to connect to, not a live network check.
    """

    supports_stream: bool = False
    supports_tools: bool = False
    supports_json: bool = False
    supports_images: bool = False
    supports_reasoning: bool = False
    supports_embeddings: bool = False
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_local: bool = False