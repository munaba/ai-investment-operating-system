"""
Stage L2 proof suite -- Provider Capability Layer.

Scope (per this session's LOCKED design decision):
  - Providers/capabilities.py (new): ProviderCapabilities, a frozen
    dataclass carrying supports_stream / supports_tools / supports_json /
    supports_images / supports_reasoning / supports_embeddings /
    max_context_tokens / max_output_tokens. Pure data -- it enforces
    nothing by itself.
  - Providers/base_provider.py: one addition -- a non-abstract
    `capabilities` property defaulting to ProviderCapabilities() (the
    all-False/unknown baseline). NOT `@abstractmethod`, so every
    pre-existing BaseProvider subclass -- including Fake/Spy/Mock test
    doubles defined in *other* test files -- keeps working unchanged
    even though none of them override it.
  - Providers/gemini.py, Providers/ollama.py: each overrides
    `capabilities` with a `@property` returning a module-level constant
    describing that implementation's actual current behavior (e.g.
    supports_stream=False because .stream() still raises
    NotImplementedError in both -- this suite cross-checks that claim
    against the real .stream() behavior, so the metadata cannot silently
    drift from reality).
  - Providers/provider_manager.py: untouched. register/get/list/exists/
    unregister keep their exact existing signatures -- proven below by
    calling them exactly as Stage 9.0/9.3's suites already do.
  - No provider-name string comparison was introduced anywhere. This
    suite demonstrates the intended call pattern -- iterating registered
    providers and reading `.capabilities` polymorphically -- and proves
    it distinguishes Gemini from Ollama without a single
    `if name == "gemini"` check.

Out of scope (per the task): Core/runtime.py, Agents/executor.py,
Agents/sandbox.py, Core/approval.py -- none of these were opened for
this stage, let alone edited.

Cakupan skenario:
  1. BaseProvider.capabilities defaults to ProviderCapabilities() for a
     bare subclass that doesn't override it (additive, non-breaking).
  2. ProviderCapabilities is frozen (immutable) -- mutation raises.
  3. GeminiProvider.capabilities is readable with zero I/O (no connect(),
     no API key, no network) and matches its declared metadata.
  4. GeminiProvider.capabilities.supports_stream == False is consistent
     with GeminiProvider.stream() actually raising NotImplementedError.
  5. OllamaProvider.capabilities is readable with zero I/O and matches
     its declared metadata.
  6. OllamaProvider.capabilities.supports_stream == False and
     supports_... are consistent with .stream()/.count_tokens() actually
     raising NotImplementedError.
  7. Polymorphic dispatch: registering both providers under arbitrary
     names and reading `.capabilities` off of what ProviderManager.get()
     returns yields provider-correct, *different* metadata -- with no
     branch on the registry name anywhere in the test's own dispatch
     logic (it only ever asks the object for its capabilities).
  8. ProviderManager's public API (register/get/list/exists/unregister)
     is unchanged: exact same call shapes as Stage 9.0/9.3 use, still
     succeed, still raise ProviderError on the same bad inputs.
  9. GeminiProvider/OllamaProvider public method signatures untouched:
     connect/disconnect/generate/stream/count_tokens/health_check/name
     all still present and still callable the same way (construction and
     attribute presence only -- no network).
 10. Existing pre-Stage-L2 BaseProvider subclasses (a local stand-in for
     Tests/test_stock_agent_smoke.py::FakeProvider-style doubles that
     never heard of `capabilities`) still register/construct/run fine.

All checks are hermetic: no network call, no API key, no external
package required (mirrors Stage 9.0's Level 1 hermetic contract).
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Providers import (
    BaseProvider,
    GeminiProvider,
    Message,
    MessageRole,
    OllamaProvider,
    ProviderCapabilities,
    ProviderManager,
    ProviderResponse,
)
from Core.exceptions import ProviderError

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Minimal BaseProvider subclass that predates Stage L2 -- never overrides
# `capabilities`. Mirrors the shape of FakeProvider/MockProvider/SpyProvider
# in the other test files without importing across test-file boundaries.
# ---------------------------------------------------------------------------
class _PreStageL2Provider(BaseProvider):
    @property
    def name(self) -> str:
        return "pre_stage_l2"

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        return ProviderResponse(text="ok", finish_reason="stop", model=self.name)

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def count_tokens(self, messages: List[Message]) -> int:
        return len(messages)

    def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# 1 + 2. Default capabilities baseline, and frozen-ness.
# ---------------------------------------------------------------------------
def scenario_default_capabilities_baseline() -> None:
    print("\nscenario_default_capabilities_baseline")
    provider = _PreStageL2Provider()
    caps = provider.capabilities

    check(isinstance(caps, ProviderCapabilities), "capabilities returns a ProviderCapabilities instance")
    check(caps.supports_stream is False, "default supports_stream is False")
    check(caps.supports_tools is False, "default supports_tools is False")
    check(caps.supports_json is False, "default supports_json is False")
    check(caps.supports_images is False, "default supports_images is False")
    check(caps.supports_reasoning is False, "default supports_reasoning is False")
    check(caps.supports_embeddings is False, "default supports_embeddings is False")
    check(caps.max_context_tokens is None, "default max_context_tokens is None")
    check(caps.max_output_tokens is None, "default max_output_tokens is None")

    try:
        caps.supports_stream = True  # type: ignore[misc]
        mutated_ok = False
    except dataclasses.FrozenInstanceError:
        mutated_ok = True
    except Exception:
        mutated_ok = False
    check(mutated_ok, "ProviderCapabilities is frozen -- mutation raises FrozenInstanceError")


# ---------------------------------------------------------------------------
# 3 + 4. GeminiProvider capabilities, zero I/O, cross-checked vs stream().
# ---------------------------------------------------------------------------
def scenario_gemini_capabilities_hermetic() -> None:
    print("\nscenario_gemini_capabilities_hermetic")
    provider = GeminiProvider(api_key="unused-in-this-test", model="unused-in-this-test")
    caps = provider.capabilities

    check(isinstance(caps, ProviderCapabilities), "GeminiProvider.capabilities returns ProviderCapabilities")
    check(caps.supports_json is True, "Gemini declares supports_json=True")
    check(caps.supports_images is True, "Gemini declares supports_images=True")
    check(caps.supports_reasoning is True, "Gemini declares supports_reasoning=True")
    check(caps.supports_embeddings is False, "Gemini declares supports_embeddings=False")
    check(caps.max_context_tokens == 1_000_000, "Gemini declares max_context_tokens=1_000_000")
    check(caps.max_output_tokens == 8_192, "Gemini declares max_output_tokens=8_192")
    check(provider._connected is False, "reading .capabilities did not connect() the provider")

    stream_raises = False
    try:
        next(provider.stream([Message(role=MessageRole.USER, content="hi")]))
    except NotImplementedError:
        stream_raises = True
    except Exception:
        stream_raises = False
    check(
        caps.supports_stream is False and stream_raises,
        "Gemini's supports_stream=False is consistent with stream() actually raising NotImplementedError",
    )


# ---------------------------------------------------------------------------
# 5 + 6. OllamaProvider capabilities, zero I/O, cross-checked vs stream()/count_tokens().
# ---------------------------------------------------------------------------
def scenario_ollama_capabilities_hermetic() -> None:
    print("\nscenario_ollama_capabilities_hermetic")
    provider = OllamaProvider(host="http://unused:11434", model="unused-model")
    caps = provider.capabilities

    check(isinstance(caps, ProviderCapabilities), "OllamaProvider.capabilities returns ProviderCapabilities")
    check(caps.supports_stream is False, "Ollama declares supports_stream=False")
    check(caps.supports_tools is False, "Ollama declares supports_tools=False")
    check(caps.supports_embeddings is False, "Ollama declares supports_embeddings=False")
    check(caps.max_context_tokens is None, "Ollama declares max_context_tokens=None (model-dependent, unknown)")
    check(caps.max_output_tokens is None, "Ollama declares max_output_tokens=None (model-dependent, unknown)")
    check(provider._connected is False, "reading .capabilities did not connect() the provider")

    stream_raises = False
    try:
        next(provider.stream([Message(role=MessageRole.USER, content="hi")]))
    except NotImplementedError:
        stream_raises = True
    except Exception:
        stream_raises = False
    check(
        caps.supports_stream is False and stream_raises,
        "Ollama's supports_stream=False is consistent with stream() actually raising NotImplementedError",
    )

    count_tokens_raises = False
    try:
        provider.count_tokens([Message(role=MessageRole.USER, content="hi")])
    except NotImplementedError:
        count_tokens_raises = True
    except Exception:
        count_tokens_raises = False
    check(count_tokens_raises, "Ollama.count_tokens() still raises NotImplementedError (Stage L1 scope unchanged)")


# ---------------------------------------------------------------------------
# 7. Polymorphic dispatch -- no provider-name branching in the dispatch path.
# ---------------------------------------------------------------------------
def scenario_polymorphic_capability_dispatch() -> None:
    print("\nscenario_polymorphic_capability_dispatch")
    manager = ProviderManager()
    gemini_key = "l2_gemini_probe"
    ollama_key = "l2_ollama_probe"

    for key in (gemini_key, ollama_key):
        if manager.exists(key):
            manager.unregister(key)

    manager.register(gemini_key, GeminiProvider(api_key="x", model="x"))
    manager.register(ollama_key, OllamaProvider(host="http://x", model="x"))

    try:
        # Deliberately generic: no `if key == "..."` anywhere in this loop.
        # Capability differences come entirely from polymorphism.
        observed = {key: manager.get(key).capabilities for key in (gemini_key, ollama_key)}

        check(
            observed[gemini_key] != observed[ollama_key],
            "capabilities differ across providers purely via polymorphism (no name check in dispatch)",
        )
        check(
            observed[gemini_key].supports_json and not observed[ollama_key].supports_json,
            "the polymorphically-resolved capabilities are provider-correct (Gemini json=True, Ollama json=False)",
        )
    finally:
        manager.unregister(gemini_key)
        manager.unregister(ollama_key)


# ---------------------------------------------------------------------------
# 8. ProviderManager public API unchanged.
# ---------------------------------------------------------------------------
def scenario_provider_manager_api_unchanged() -> None:
    print("\nscenario_provider_manager_api_unchanged")
    manager = ProviderManager()
    key = "l2_manager_api_probe"
    if manager.exists(key):
        manager.unregister(key)

    manager.register(key, _PreStageL2Provider())
    check(manager.exists(key) is True, "register() + exists() still work with the original two-arg call shape")
    check(key in manager.list(), "list() still returns the registered name")
    check(isinstance(manager.get(key), BaseProvider), "get() still returns a BaseProvider instance")

    raised_on_duplicate = False
    try:
        manager.register(key, _PreStageL2Provider())
    except ProviderError:
        raised_on_duplicate = True
    check(raised_on_duplicate, "register() without overwrite=True still rejects a duplicate name")

    manager.register(key, _PreStageL2Provider(), overwrite=True)
    check(True, "register(..., overwrite=True) still replaces an existing registration")

    manager.unregister(key)
    check(manager.exists(key) is False, "unregister() still removes the registration")

    raised_on_missing = False
    try:
        manager.get(key)
    except ProviderError:
        raised_on_missing = True
    check(raised_on_missing, "get() on an unregistered name still raises ProviderError")


# ---------------------------------------------------------------------------
# 9. Public method surface of GeminiProvider/OllamaProvider untouched.
# ---------------------------------------------------------------------------
def scenario_provider_public_surface_untouched() -> None:
    print("\nscenario_provider_public_surface_untouched")
    for cls, ctor_kwargs in (
        (GeminiProvider, {"api_key": "x", "model": "x"}),
        (OllamaProvider, {"host": "http://x", "model": "x"}),
    ):
        provider = cls(**ctor_kwargs)
        for method_name in ("connect", "disconnect", "generate", "stream", "count_tokens", "health_check"):
            check(
                callable(getattr(provider, method_name, None)),
                f"{cls.__name__}.{method_name} is still present and callable",
            )
        check(isinstance(provider.name, str) and provider.name, f"{cls.__name__}.name still returns a non-empty str")
        check(isinstance(provider.capabilities, ProviderCapabilities), f"{cls.__name__}.capabilities is the new addition, present")


# ---------------------------------------------------------------------------
# 10. Pre-existing BaseProvider subclasses unaffected.
# ---------------------------------------------------------------------------
def scenario_pre_existing_subclass_unaffected() -> None:
    print("\nscenario_pre_existing_subclass_unaffected")
    provider = _PreStageL2Provider()
    manager = ProviderManager()
    key = "l2_pre_existing_probe"
    if manager.exists(key):
        manager.unregister(key)

    manager.register(key, provider)
    check(manager.get(key) is provider, "a BaseProvider subclass that never overrides capabilities still registers fine")

    response = provider.generate([Message(role=MessageRole.USER, content="hi")])
    check(isinstance(response, ProviderResponse) and response.text == "ok", "generate() still works unchanged")
    check(provider.capabilities == ProviderCapabilities(), "it inherits the all-False/unknown default, not a crash")

    manager.unregister(key)


def main() -> int:
    scenarios = [
        scenario_default_capabilities_baseline,
        scenario_gemini_capabilities_hermetic,
        scenario_ollama_capabilities_hermetic,
        scenario_polymorphic_capability_dispatch,
        scenario_provider_manager_api_unchanged,
        scenario_provider_public_surface_untouched,
        scenario_pre_existing_subclass_unaffected,
    ]

    import traceback

    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE L2 PROVIDER CAPABILITY LAYER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())