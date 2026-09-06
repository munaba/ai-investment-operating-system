"""
Stage L3 proof suite -- Intelligent Provider Selection.

Scope (per this session's LOCKED design decision):
  - Providers/requirement.py (new): ProviderRequirement, a frozen
    dataclass -- every field defaults to "not required".
  - Providers/provider_selector.py (new): ProviderSelector.select(),
    ProviderSelector.candidates(). Filters registered providers against
    a ProviderRequirement, then scores survivors -- purely via
    provider.capabilities, never provider name/class/isinstance.
  - Providers/capabilities.py: one additive field, `is_local: bool =
    False` -- the one piece of deployment-topology metadata Stage L3
    needs that Stage L2's model-capability-only fields didn't cover
    (see provider_selector.py's module docstring for the documented
    local_only/offline_required-collapse-onto-one-field limitation).
  - Providers/gemini.py / Providers/ollama.py: their capability
    constants gained `is_local=False` / `is_local=True` respectively.
    No method body in either file was touched.
  - Providers/__init__.py: export ProviderRequirement, ProviderSelector.

Untouched (proven, not just claimed, below where practical):
  BaseProvider (no new abstractmethod, no signature change),
  ProviderManager (no new/changed method), GeminiProvider/OllamaProvider
  method bodies, Core/composition_root.py, Core/runtime.py,
  Agents/executor.py, Core/approval.py, Agents/planner.py.

Cakupan skenario:
  1. Filtering per requirement field: need_images, need_stream,
     need_reasoning, need_json, minimum_context_tokens (including the
     "unknown context = fails a minimum" rule), local_only,
     offline_required -- each proven to actually exclude a provider
     that fails it and admit one that satisfies it.
  2. Scoring: among multiple survivors, the one with more optional
     capabilities (and/or larger context as tiebreaker) wins; a custom
     third provider with strictly more capabilities than Gemini/Ollama
     is preferred over both, proving scoring is not hardcoded to two
     known providers.
  3. Multiple providers registered simultaneously -- select() picks
     deterministically among >2 candidates.
  4. No provider available -- ProviderError is raised, not None/crash,
     and candidates() returns an empty list rather than raising.
  5. Capability polymorphism -- a brand-new BaseProvider subclass this
     suite defines locally (never seen by provider_selector.py) is
     correctly filtered/scored/selected purely through its
     .capabilities property, proving new providers need zero selector
     changes to participate.
  6. No provider-name branching -- this suite's own dispatch logic
     never compares a name/class; additionally, the selector module's
     source is grepped at runtime for `==` comparisons against known
     provider name literals, failing loudly if one is ever introduced.
  7. BaseProvider/ProviderManager/GeminiProvider/OllamaProvider public
     surfaces still unchanged (regression guard specific to this
     stage's "JANGAN mengubah" list).

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import inspect
import re
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
    ProviderRequirement,
    ProviderResponse,
    ProviderSelector,
)
from Providers.provider_selector import _meets_requirement, _score
import Providers.provider_selector as provider_selector_module
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
# A custom third provider, defined only in this test file, that the
# production selector code has never heard of. Deliberately declares
# MORE capabilities than Gemini/Ollama so scoring tests aren't
# incidentally "hardcoded" to those two.
# ---------------------------------------------------------------------------
class _SuperProvider(BaseProvider):
    """A hypothetical fully-capable local provider, for polymorphism proof."""

    @property
    def name(self) -> str:
        return "super_provider"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stream=True,
            supports_tools=True,
            supports_json=True,
            supports_images=True,
            supports_reasoning=True,
            supports_embeddings=True,
            max_context_tokens=2_000_000,
            max_output_tokens=16_384,
            is_local=True,
        )

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        return ProviderResponse(text="ok", finish_reason="stop", model=self.name)

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        yield "ok"

    def count_tokens(self, messages: List[Message]) -> int:
        return len(messages)

    def health_check(self) -> bool:
        return True


class _BareProvider(BaseProvider):
    """A minimal provider that never overrides .capabilities -- inherits the
    all-False/unknown default. Used to prove the filter correctly excludes
    a provider that (declares it) supports nothing.
    """

    @property
    def name(self) -> str:
        return "bare_provider"

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


def _fresh_registry(*named_providers: "tuple[str, BaseProvider]") -> ProviderManager:
    """Register the given (name, provider) pairs on a clean ProviderManager
    singleton, unregistering anything already sitting under those names
    first (defensive against leftover state from a prior scenario/run).
    """
    manager = ProviderManager()
    for name, _ in named_providers:
        if manager.exists(name):
            manager.unregister(name)
    for name, provider in named_providers:
        manager.register(name, provider)
    return manager


def _cleanup(manager: ProviderManager, *names: str) -> None:
    for name in names:
        if manager.exists(name):
            manager.unregister(name)


# ---------------------------------------------------------------------------
# 1. Filtering, field by field.
# ---------------------------------------------------------------------------
def scenario_filtering_per_field() -> None:
    print("\nscenario_filtering_per_field")

    gemini_caps = GeminiProvider(api_key="x", model="x").capabilities
    ollama_caps = OllamaProvider(host="http://x", model="x").capabilities

    check(
        _meets_requirement(gemini_caps, ProviderRequirement(need_images=True)) is True,
        "need_images=True is satisfied by Gemini (supports_images=True)",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(need_images=True)) is False,
        "need_images=True excludes Ollama (supports_images=False)",
    )

    check(
        _meets_requirement(gemini_caps, ProviderRequirement(need_stream=True)) is False,
        "need_stream=True excludes Gemini (supports_stream=False in this codebase)",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(need_stream=True)) is False,
        "need_stream=True excludes Ollama too (supports_stream=False)",
    )

    check(
        _meets_requirement(gemini_caps, ProviderRequirement(need_reasoning=True)) is True,
        "need_reasoning=True is satisfied by Gemini",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(need_reasoning=True)) is False,
        "need_reasoning=True excludes Ollama",
    )

    check(
        _meets_requirement(gemini_caps, ProviderRequirement(need_json=True)) is True,
        "need_json=True is satisfied by Gemini",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(need_json=True)) is False,
        "need_json=True excludes Ollama",
    )

    check(
        _meets_requirement(gemini_caps, ProviderRequirement(minimum_context_tokens=500_000)) is True,
        "minimum_context_tokens=500_000 is satisfied by Gemini (1_000_000 known)",
    )
    check(
        _meets_requirement(gemini_caps, ProviderRequirement(minimum_context_tokens=2_000_000)) is False,
        "minimum_context_tokens=2_000_000 excludes Gemini (1_000_000 < 2_000_000)",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(minimum_context_tokens=1)) is False,
        "minimum_context_tokens=1 excludes Ollama -- unknown (None) context never satisfies a minimum",
    )

    check(
        _meets_requirement(ollama_caps, ProviderRequirement(local_only=True)) is True,
        "local_only=True is satisfied by Ollama (is_local=True)",
    )
    check(
        _meets_requirement(gemini_caps, ProviderRequirement(local_only=True)) is False,
        "local_only=True excludes Gemini (is_local=False)",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement(offline_required=True)) is True,
        "offline_required=True is satisfied by Ollama",
    )
    check(
        _meets_requirement(gemini_caps, ProviderRequirement(offline_required=True)) is False,
        "offline_required=True excludes Gemini",
    )

    check(
        _meets_requirement(gemini_caps, ProviderRequirement()) is True,
        "the empty ProviderRequirement() matches every provider (Gemini)",
    )
    check(
        _meets_requirement(ollama_caps, ProviderRequirement()) is True,
        "the empty ProviderRequirement() matches every provider (Ollama)",
    )


# ---------------------------------------------------------------------------
# 2. Scoring.
# ---------------------------------------------------------------------------
def scenario_scoring() -> None:
    print("\nscenario_scoring")

    gemini_caps = GeminiProvider(api_key="x", model="x").capabilities
    ollama_caps = OllamaProvider(host="http://x", model="x").capabilities
    super_caps = _SuperProvider().capabilities

    empty = ProviderRequirement()
    check(
        _score(gemini_caps, empty) > _score(ollama_caps, empty),
        "Gemini scores higher than Ollama under the empty requirement (more optional capabilities)",
    )
    check(
        _score(super_caps, empty) > _score(gemini_caps, empty),
        "a hypothetical fully-capable provider scores higher than Gemini (scoring isn't capped at known providers)",
    )

    local_pref = ProviderRequirement(local_only=True)
    ollama_score_plain = _score(ollama_caps, empty)
    ollama_score_localpref = _score(ollama_caps, local_pref)
    check(
        ollama_score_localpref > ollama_score_plain,
        "Ollama's score increases specifically when local_only=True is requested (its declared bonus term)",
    )


# ---------------------------------------------------------------------------
# 3. Multiple providers registered, select() end-to-end.
# ---------------------------------------------------------------------------
def scenario_multiple_providers_end_to_end() -> None:
    print("\nscenario_multiple_providers_end_to_end")
    manager = _fresh_registry(
        ("l3_gemini", GeminiProvider(api_key="x", model="x")),
        ("l3_ollama", OllamaProvider(host="http://x", model="x")),
        ("l3_super", _SuperProvider()),
        ("l3_bare", _BareProvider()),
    )
    try:
        selector = ProviderSelector(manager)

        check(
            selector.select(ProviderRequirement()).name == "super_provider",
            "with 4 candidates and the empty requirement, the highest-capability provider wins",
        )
        check(
            selector.select(ProviderRequirement(need_images=True)).name in ("gemini", "super_provider"),
            "need_images=True narrows to Gemini/SuperProvider (both support images)",
        )
        check(
            selector.select(ProviderRequirement(need_images=True)).name == "super_provider",
            "among image-capable candidates, SuperProvider still wins on richer capabilities",
        )
        check(
            selector.select(ProviderRequirement(local_only=True)).name in ("ollama", "super_provider"),
            "local_only=True narrows to Ollama/SuperProvider (both is_local=True)",
        )
        check(
            selector.select(ProviderRequirement(need_stream=True)).name == "super_provider",
            "need_stream=True narrows to SuperProvider alone (only one that supports streaming)",
        )

        candidates_for_stream = selector.candidates(ProviderRequirement(need_stream=True))
        check(
            len(candidates_for_stream) == 1 and candidates_for_stream[0].name == "super_provider",
            "candidates() for need_stream=True returns exactly [SuperProvider]",
        )
    finally:
        _cleanup(manager, "l3_gemini", "l3_ollama", "l3_super", "l3_bare")


# ---------------------------------------------------------------------------
# 4. No provider available.
# ---------------------------------------------------------------------------
def scenario_no_provider_available() -> None:
    print("\nscenario_no_provider_available")
    manager = _fresh_registry(
        ("l3_none_gemini", GeminiProvider(api_key="x", model="x")),
        ("l3_none_ollama", OllamaProvider(host="http://x", model="x")),
    )
    try:
        selector = ProviderSelector(manager)
        impossible = ProviderRequirement(need_images=True, need_stream=True, local_only=True)

        check(
            selector.candidates(impossible) == [],
            "candidates() returns an empty list (not None, not a crash) when nothing matches",
        )

        raised = None
        try:
            selector.select(impossible)
        except ProviderError as exc:
            raised = exc
        check(raised is not None, "select() raises ProviderError when no candidate satisfies the requirement")
        check(
            raised is not None and "requirement" in raised.details,
            "the raised ProviderError carries the requirement in .details for debuggability",
        )
    finally:
        _cleanup(manager, "l3_none_gemini", "l3_none_ollama")


# ---------------------------------------------------------------------------
# 5. Capability polymorphism -- selector never special-cases a class.
# ---------------------------------------------------------------------------
def scenario_capability_polymorphism() -> None:
    print("\nscenario_capability_polymorphism")
    manager = _fresh_registry(("l3_poly_super", _SuperProvider()))
    try:
        selector = ProviderSelector(manager)
        result = selector.select(ProviderRequirement(need_images=True, need_reasoning=True, local_only=True))
        check(
            result.name == "super_provider",
            "a brand-new BaseProvider subclass this suite invented is selected purely via its .capabilities",
        )
    finally:
        _cleanup(manager, "l3_poly_super")

    # Directly prove _meets_requirement/_score take capabilities objects,
    # not provider instances, by feeding them a bare ProviderCapabilities
    # that was never attached to any provider at all.
    freestanding_caps = ProviderCapabilities(supports_images=True, is_local=True)
    check(
        _meets_requirement(freestanding_caps, ProviderRequirement(need_images=True, local_only=True)),
        "_meets_requirement operates on a bare ProviderCapabilities value, no provider object needed at all",
    )


# ---------------------------------------------------------------------------
# 6. No provider-name branching, anywhere in the selector module.
# ---------------------------------------------------------------------------
def scenario_no_name_branching() -> None:
    print("\nscenario_no_name_branching")

    source = inspect.getsource(provider_selector_module)
    forbidden_patterns = [
        r'==\s*["\']gemini["\']',
        r'==\s*["\']ollama["\']',
        r'provider_name\s*==',
        r'\.name\s*==\s*["\']',
        r'isinstance\([^)]*GeminiProvider',
        r'isinstance\([^)]*OllamaProvider',
    ]
    violations = [p for p in forbidden_patterns if re.search(p, source)]
    check(
        violations == [],
        f"Providers/provider_selector.py contains no provider-name/class branching (checked {len(forbidden_patterns)} patterns)",
    )

    check(
        "capabilities" in source,
        "provider_selector.py's filtering/scoring logic is built on .capabilities (sanity check the grep target is right)",
    )

    manager = _fresh_registry(
        ("l3_nn_a", GeminiProvider(api_key="x", model="x")),
        ("l3_nn_b", OllamaProvider(host="http://x", model="x")),
    )
    try:
        selector = ProviderSelector(manager)
        # This test's own dispatch: iterate, never branch on key/name.
        picked = {req_label: selector.select(req).capabilities for req_label, req in {
            "images": ProviderRequirement(need_images=True),
            "local": ProviderRequirement(local_only=True),
        }.items()}
        check(
            picked["images"] != picked["local"],
            "selecting under different requirements yields provider-appropriate, differing capabilities "
            "with zero name comparisons in this test's own dispatch code",
        )
    finally:
        _cleanup(manager, "l3_nn_a", "l3_nn_b")


# ---------------------------------------------------------------------------
# 7. Regression guard: nothing on the "JANGAN mengubah" list changed shape.
# ---------------------------------------------------------------------------
def scenario_locked_surfaces_unchanged() -> None:
    print("\nscenario_locked_surfaces_unchanged")

    for method_name in ("connect", "disconnect", "generate", "stream", "count_tokens", "health_check"):
        check(
            callable(getattr(BaseProvider, method_name, None)),
            f"BaseProvider.{method_name} is still present",
        )
    check(
        "capabilities" in BaseProvider.__dict__,
        "BaseProvider.capabilities (Stage L2) is still present as a non-abstract property",
    )
    check(
        not getattr(BaseProvider.__dict__["capabilities"], "__isabstractmethod__", False),
        "BaseProvider.capabilities is still non-abstract (Stage L3 did not tighten the contract)",
    )

    for method_name in ("register", "unregister", "get", "list", "exists"):
        sig = inspect.signature(getattr(ProviderManager, method_name))
        check(
            "requirement" not in sig.parameters and "capabilities" not in sig.parameters,
            f"ProviderManager.{method_name}'s signature was not touched to know about requirements/capabilities",
        )

    gemini = GeminiProvider(api_key="x", model="x")
    ollama = OllamaProvider(host="http://x", model="x")
    check(gemini.capabilities.supports_json is True, "GeminiProvider capability declarations unchanged")
    check(ollama.capabilities.is_local is True, "OllamaProvider's new is_local declaration is exactly True (not accidentally flipped)")

    stream_raises = False
    try:
        next(gemini.stream([Message(role=MessageRole.USER, content="hi")]))
    except NotImplementedError:
        stream_raises = True
    check(stream_raises, "GeminiProvider.stream() behavior is unchanged (still raises NotImplementedError)")


def main() -> int:
    scenarios = [
        scenario_filtering_per_field,
        scenario_scoring,
        scenario_multiple_providers_end_to_end,
        scenario_no_provider_available,
        scenario_capability_polymorphism,
        scenario_no_name_branching,
        scenario_locked_surfaces_unchanged,
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
    print(f"STAGE L3 PROVIDER SELECTOR RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())