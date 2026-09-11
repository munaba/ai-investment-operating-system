from __future__ import annotations

from Core.config import config

#: Environment variables required for the application to run in
#: production with Gemini active, checked for presence only (never for
#: validity/connectivity).
#:
#: Stage 9.4 scope (unchanged, kept for backward compatibility): this
#: name and its Gemini-only contents are exactly what they were before
#: Stage L1 -- existing callers that import this constant directly still
#: see the same list. Stage L1 does not repurpose it; it adds a second,
#: per-provider-kind list below and a lookup that selects between them.
REQUIRED_RUNTIME_ENV_VARS: list[str] = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
]

#: Ollama's required env vars. Stage L1 addition -- mirrors
#: REQUIRED_RUNTIME_ENV_VARS's Gemini list, just for the other provider
#: kind. OLLAMA_TIMEOUT is intentionally not required here: it has a
#: documented default (300s) in ``Providers.ollama.OllamaProvider``, so
#: its absence is not a configuration error.
OLLAMA_REQUIRED_RUNTIME_ENV_VARS: list[str] = [
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
]

#: 9router's required env vars. Mirrors OLLAMA_REQUIRED_RUNTIME_ENV_VARS's
#: shape. NINE_ROUTER_HOST is intentionally not required here: it has a
#: documented default (``http://localhost:20128``, 9router's own
#: documented default port) in
#: ``Providers.nine_router.NineRouterProvider``, so its absence is not
#: a configuration error. NINE_ROUTER_API_KEY is also not required --
#: a locally-run 9router instance may be configured without auth.
NINE_ROUTER_REQUIRED_RUNTIME_ENV_VARS: list[str] = [
    "NINE_ROUTER_MODEL",
]

#: provider_kind -> required env vars for that kind. Stage L1 addition.
#: Extending this for a future provider (OpenAI, Anthropic, ...) is a
#: one-line addition here -- no change to ``validate_runtime_environment``
#: itself.
_REQUIRED_ENV_VARS_BY_PROVIDER_KIND: dict[str, list[str]] = {
    "gemini": REQUIRED_RUNTIME_ENV_VARS,
    "ollama": OLLAMA_REQUIRED_RUNTIME_ENV_VARS,
    "nine_router": NINE_ROUTER_REQUIRED_RUNTIME_ENV_VARS,
}

#: Default provider kind when ACTIVE_PROVIDER is unset -- matches
#: Core.composition_root.DEFAULT_PROVIDER_NAME so behavior stays
#: identical to pre-Stage-L1 when no one has opted into Ollama yet.
_DEFAULT_PROVIDER_KIND: str = "gemini"


def validate_runtime_environment() -> None:
    """Fail fast if required production environment variables are absent
    for whichever provider is currently active.

    Stage L1: which env vars are required is now conditional on
    ``ACTIVE_PROVIDER`` (``"gemini"`` or ``"ollama"``, defaulting to
    ``"gemini"`` when unset -- the same default
    ``Core.composition_root.build_application`` uses). Gemini variables
    are never required when Ollama is active, and vice versa -- exactly
    one provider's variables are checked per call.

    Presence-only check via ``Core.config.config.validate()`` (existing,
    previously-unused method -- this is its first caller in the
    codebase). Does not read/parse the values, does not import or
    connect to any provider SDK, and performs no network I/O -- entirely
    distinct from and unrelated to ``Providers.gemini.GeminiProvider.connect()``/
    ``Providers.ollama.OllamaProvider.connect()``, which still perform
    their own lazy validation at first real use.

    Intended to be called once, explicitly, from the application
    entrypoint (``main.py``) -- deliberately *not* from
    ``Core.composition_root.build_application()``, which Stage 9.0 locks
    as hermetic (must succeed with no secrets, no network, and no
    external package present). Calling this function is what makes a
    real run of the application fail fast on missing configuration;
    calling ``build_application()`` directly (e.g. in tests/CI) remains
    unaffected.

    Raises:
        ConfigurationError: If any variable required for the active
            provider kind is unset. The exception's
            ``details["missing_keys"]`` lists exactly which ones.
    """
    active_provider_kind = config.get("ACTIVE_PROVIDER", _DEFAULT_PROVIDER_KIND)
    required_vars = _REQUIRED_ENV_VARS_BY_PROVIDER_KIND.get(active_provider_kind, REQUIRED_RUNTIME_ENV_VARS)
    config.validate(required_vars)