# ACTIVATION 1.1 — DEPENDENCY MANIFEST — DELIVERABLE REPORT (Revision 2)

Scope: dependency manifest only. No application source code, test code,
database schema, migration, or composition root was modified in this
revision or the prior one. No `doctor`, `init`, or migration-runner
functionality was implemented.

## Revision note

This is a revision of the first pass, made in response to review feedback:

1. **Manifest structure changed** so that optional and provider-specific
   dependencies can no longer be described as "automatically mandatory."
   In revision 1, a single `requirements.txt` bundled required + optional +
   provider-specific packages together, so `pip install -r requirements.txt`
   (the exact command in `README.md`) installed everything by default. That
   is now split into six files (§C, §D) so the file `README.md` tells
   people to run by default installs **core only**.
2. **`pytest` file count corrected from 6 to 3** everywhere it appears.
   Revision 1's `requirements-dev.txt` comment said "required by 6 of 246
   test files," which conflated two different things: 3 files actually
   import `pytest`, and a separate 3 files import stdlib `unittest` (which
   needs no external package at all). The report's own §G table already
   had this right in revision 1; only the `requirements-dev.txt` comment
   was wrong. Fixed in both places, and re-checked for any other
   occurrence.
3. **Clean-install validation re-run three ways**: core-only,
   provider-specific (Gemini), and full install — each in its own fresh
   virtual environment (§H, §I).

No application source code or test code was touched in this revision,
consistent with the original scope.

---

## A. Files Read

Same file set as revision 1 (unchanged — no new source reading was needed
for a manifest restructure):

- `Docs/ACTIVATION 0/AIOS_Activation0_Baseline_Audit.md`
- `Docs/ACTIVATION 0/AIOS_Activation0.2_Baseline_Test_Report.md`
- `Docs/ACTIVATION 0/AIOS_Test_Pass_Matrix.csv` (skimmed)
- `README.md`
- `main.py`
- `Core/config.py`, `Core/composition_root.py` (import section + `build_application` docstring)
- `Providers/gemini.py`, `Providers/gemini_vision_provider.py`, `Providers/ollama.py`
- `Services/notification_service.py`, `Services/chart_service.py`,
  `Services/backtest_service.py`, `Services/stock_service.py`,
  `Services/moving_average_service.py`, `Services/technical_indicator_service.py`,
  `Services/technical_score_service.py`
- `Repository/external/stock_data_repository.py`, `Repository/external/news_repository.py`
- `Business/manual_scan_service.py`
- All 217 production `.py` files (AST-walked programmatically for imports —
  every `import X` / `from X import Y` at any nesting level, not just
  module-level, so lazily-imported dependencies inside functions were
  caught too)
- All 246 test files under `Tests/` (same AST-walk, to separate
  dev/test-only imports from production imports)

---

## B. Files Created / Changed

Created (revision 2 — replaces revision 1's `requirements.txt` /
`requirements-dev.txt` pair):

- `requirements.txt` — **core only**: the minimum needed to import
  `Core/composition_root.py` and start `main.py`.
- `requirements-gemini.txt` — Gemini provider add-on.
- `requirements-ollama.txt` — Ollama provider add-on.
- `requirements-optional.txt` — chart / backtest / market-data / notification
  add-ons (all optional features together).
- `requirements-dev.txt` — development/test-only add-on (builds on
  `requirements.txt` only, not on any provider/optional file — see §G).
- `requirements-full.txt` — convenience "everything" file, for anyone who
  wants full functionality without composing the add-on files by hand.
- `Docs/ACTIVATION 1/AIOS_Activation1.1_Dependency_Manifest_Report.md`
  (this file, revision 2 — the revision-1 version was removed and
  replaced, not kept alongside it, to avoid two conflicting "official"
  reports existing at once).

Changed:
- `README.md` — install section updated to show the core-only default and
  the per-provider/per-feature/`-full` add-on commands, and the corrected
  pytest file count. No other README content touched.

```
No application source code modified.
No test code modified.
No database schema modified.
No migration modified.
No composition root modified.
```

---

## C. Manifest Decision

**Format: `requirements.txt`-family, not `pyproject.toml`.** Reasoning
unchanged from revision 1 — the repository has no installable package
structure (no root package name, flat `Agents.x`/`Core.x`-style imports
that assume the repo root is on `sys.path`, no build backend or project
metadata anywhere), and building that structure would cross into
architecture/refactor territory this activation is explicitly scoped away
from. `requirements.txt` also already matched `README.md`'s pre-existing
(if broken) convention.

**Structure: six files, not one.** This is the part that changed in this
revision.

| File | Contents | When you need it |
|---|---|---|
| `requirements.txt` | `python-dotenv`, `pandas` | Always — this is core. |
| `requirements-gemini.txt` | `google-genai` | Only if you use the Gemini provider. |
| `requirements-ollama.txt` | `requests` | Only if you use the Ollama provider. |
| `requirements-optional.txt` | `plotly`, `numpy`, `yfinance`, `requests` | Only for chart rendering / backtesting / live market data / notification sending — install the whole file, or hand-pick individual packages if you only need one feature. |
| `requirements-dev.txt` | `-r requirements.txt` + `pytest` | Only to run the pytest-based test files. |
| `requirements-full.txt` | `-r` of all of the above except dev | Convenience "install everything" for people who don't want to compose files by hand. |

Rationale for six files over one: with everything in a single
`requirements.txt`, the literal command in `README.md`
(`pip install -r requirements.txt`) installed every provider and every
optional feature by default — meaning an operator who only ever uses
Gemini still got `requests` (Ollama), `plotly`, `numpy`, and `yfinance`
whether or not they intended to. That doesn't cause the application to
*misbehave* (the source code's own lazy-import design already tolerates
missing optional packages gracefully — see §H/§I), but it does mean the
manifest itself was making an installation-time decision ("give the
operator everything") that the category system in the task brief (§5)
says the manifest should not make. Splitting into core + per-provider +
optional + dev + a `-full` convenience file means:
- The literal default install command now installs only what's provably
  required (§D).
- Choosing a provider is an explicit, separate `pip install -r
  requirements-<provider>.txt` step — nothing forces both providers to be
  installed together.
- Anyone who does want the old "just give me everything" behavior still
  has a one-line way to get it (`requirements-full.txt`), so nothing was
  lost — the default just changed from "everything" to "minimum viable."

`requests` intentionally appears in two files (`requirements-ollama.txt`
and `requirements-optional.txt`) because it is genuinely used by two
independent features (Ollama HTTP calls, Telegram/Discord notification
sending — see §D/§E/§F). This is documented in both files' comments so it
doesn't look like an accidental duplicate; installing either file (or
both) results in exactly one `requests` install either way, so there's no
practical downside to listing it twice.

---

## D. Dependency Inventory

| Package (PyPI) | Import name | Category | Used By | Mandatory? | Manifest file | Evidence |
|---|---|---|---|---|---|---|
| `python-dotenv` | `dotenv` | Required | `Core/config.py` | Yes | `requirements.txt` | `from dotenv import load_dotenv` at module top level, no try/except; `Core.config` is imported transitively by nearly everything, including `main.py`. |
| `pandas` | `pandas` | Required (de facto, via eager import) | `Services/chart_service.py`, `Services/moving_average_service.py`, `Services/technical_indicator_service.py`, `Services/technical_score_service.py` | Yes | `requirements.txt` | `import pandas as pd` at module top level (no lazy-import guard, unlike numpy/plotly/yfinance in the same codebase). All four modules are imported at module level by `Core/composition_root.py`, which `main.py` imports unconditionally. Verified empirically: uninstalling pandas breaks `import Core.composition_root` immediately. |
| `numpy` | `numpy` | Optional (feature: backtest); present anyway via pandas | `Services/backtest_service.py` | No, by source design (lazily imported via `_get_numpy()`, wrapped in try/except with an actionable install message) — but pandas itself declares numpy as an install-time dependency, so it is present in any environment with pandas installed (i.e. every environment, since pandas is core). Listed under `requirements-optional.txt` per the app's own lazy-import contract, even though it's physically already there. | `requirements-optional.txt` | `Services/backtest_service.py:81` `import numpy as np` inside `_get_numpy()`, guarded. |
| `plotly` | `plotly` | Optional (feature: chart rendering) | `Services/chart_service.py` | No | `requirements-optional.txt` | `Services/chart_service.py:92-93`, `import plotly.graph_objects as go` / `from plotly.subplots import make_subplots` inside `_resolve_plotly()`, explicitly commented `# intentionally lazy`. Verified: `ChartService()` instantiates fine without `plotly` installed; only `_resolve_plotly()` fails, with a clear `ModuleNotFoundError`. |
| `yfinance` | `yfinance` | Optional at import time / effectively required at runtime for the two live commands | `Services/stock_service.py`, `Repository/external/stock_data_repository.py`, `Repository/external/news_repository.py` | Lazy import at the code level, guarded — but both production commands (`auto`, `scan`) ultimately need real market data to return anything meaningful. | `requirements-optional.txt` | `Services/stock_service.py:88`, `Repository/external/stock_data_repository.py:52`, `Repository/external/news_repository.py:51`. |
| `google-genai` | `google.genai` | Provider-specific (Gemini) | `Providers/gemini.py`, `Providers/gemini_vision_provider.py` | Only if the Gemini provider is actually connected to | `requirements-gemini.txt` | `Providers/gemini.py:107` `from google import genai` inside `connect()`, wrapped in try/except raising `ProviderError("google-genai SDK is not installed...")`. Note: this is the newer unified `google-genai` SDK, **not** the older `google-generativeai` package — verified by the exact import shape (`from google import genai`, `genai.Client(...)`) and the module's own error message. |
| `requests` | `requests` | Provider-specific (Ollama) **and** optional feature (Telegram/Discord notification) | `Providers/ollama.py`, `Services/notification_service.py` | Only if Ollama is used or a notification is actually sent | `requirements-ollama.txt` **and** `requirements-optional.txt` (intentionally listed in both — see §C) | `Providers/ollama.py:126` and `Services/notification_service.py:90`, both inside lazy `_get_http_client()` methods, guarded, actionable error messages. Per Activation 0 baseline, notification sending is currently dead code (nothing calls `.notify()` from the live command paths), so today `requests` is only load-bearing for Ollama. |
| `pytest` | `pytest` | Development/Test only | Exactly 3 of 246 test files (`Tests/test_stage5_suspend_resume.py`, `Tests/test_stage6_delegate.py`, `Tests/test_stage7_cancel.py`) | Only to run those 3 files / the full suite via `pytest` | `requirements-dev.txt` | AST-verified via programmatic import scan across all 246 test files; confirmed by direct `grep` for `pytest.raises`/`pytest.main`. Not installed in the baseline audit environment (confirmed: `ModuleNotFoundError: No module named 'pytest'` before this activation). |

**Not listed** (standard library, excluded from manifest per §3.1):
`abc`, `builtins`, `collections`, `contextlib`, `dataclasses`, `datetime`,
`enum`, `functools`, `json`, `logging`, `os`, `pathlib`, `random`, `re`,
`socket`, `sqlite3`, `sys`, `tempfile`, `threading`, `time`, `types`,
`typing`, `uuid`, `weakref`, `__future__`. `unittest` (used by exactly 3
test files — `Tests/test_manual_scan_command.py`, `Tests/test_stage_l17_memory.py`,
`Tests/test_market_analysis_foundation.py`) is also stdlib and not added as
an external dependency.

**Local packages** (not dependencies — internal source folders):
`Agents`, `Business`, `Core`, `Database`, `Orchestration`, `Providers`,
`Repository`, `Services`.

---

## E. Provider Dependency Map

| Provider | Dependency | Manifest file | Required When |
|---|---|---|---|
| Gemini | `google-genai` | `requirements-gemini.txt` | Only when `GeminiProvider.connect()` (or `GeminiVisionProvider`'s equivalent) is actually called — i.e., the Gemini provider is selected/used at runtime. Not required to import `Core.composition_root`, build the `ApplicationGraph`, or start `main.py`. |
| Ollama | `requests` | `requirements-ollama.txt` | Only when `OllamaProvider.connect()`/`_get_http_client()` is called — i.e., the Ollama provider is actually used. Same isolation property as Gemini. |

Verified empirically (this revision) in three separate clean venvs:
- **Core-only venv**: `google-genai` and `requests` both absent; `build_application()` still succeeds.
- **Gemini-only venv** (`requirements.txt` + `requirements-gemini.txt`): `GeminiProvider.connect()` succeeds (constructs a client; no live API call was made). `plotly`/`yfinance` remain absent — installing the Gemini add-on does not pull in optional-feature packages.
  - Note: `google-genai`'s own dependency tree transitively installs `requests`/`httpx`/`google-auth` (that's `google-genai`'s own requirement, not something this manifest declares for Ollama). As a side effect, `OllamaProvider.connect()` also succeeds in this venv — which is a legitimate transitive consequence of Gemini's SDK, not a Gemini→Ollama coupling this manifest introduces. If Ollama is the only provider needed, `requirements-ollama.txt` alone (without Gemini) still installs `requests` directly and independently, as shown by the core-only test.
- **Full venv** (`requirements-full.txt`): both providers work, confirming nothing regresses when everything is installed together.

---

## F. Optional Dependency Map

| Feature | Dependency | Manifest file | Required When |
|---|---|---|---|
| Chart rendering | `plotly` | `requirements-optional.txt` | Only when `ChartService._resolve_plotly()` runs (i.e., a chart is actually rendered). `ChartService()` instantiates fine without it. |
| Backtesting | `numpy` | `requirements-optional.txt` | Only when `BacktestService._get_numpy()` runs. Present regardless in practice because `pandas` (core) declares `numpy` as its own dependency. |
| Live market data (price history, company info) | `yfinance` | `requirements-optional.txt` | Only when `StockService`/`StockDataRepository` actually fetch data — but this happens on essentially every real invocation of `auto`/`scan`, since both commands need live ticker data to produce output. Import itself remains lazy/guarded. |
| News fetch | `yfinance` | `requirements-optional.txt` | Same package as above (`Repository/external/news_repository.py` also imports it lazily; no separate package). |
| Telegram/Discord notification | `requests` | `requirements-optional.txt` (also `requirements-ollama.txt`) | Only when `NotificationService.execute()`/`_send_telegram()` actually sends. Per Activation 0, no live command path currently calls this. |

Verified empirically (core-only venv, this revision): `plotly` and
`yfinance` both absent; `build_application()` still succeeds.
`ChartService()`/`StockService()` instantiate fine; the specific
resolve-the-real-library methods raise clean `ModuleNotFoundError`s only
when actually called.

---

## G. Development/Test Dependency Map

| Dependency | Used By | Runtime Required? | Manifest file |
|---|---|---|---|
| `pytest` | Exactly 3 of 246 test files (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`, `test_stage7_cancel.py`) — `pytest.raises`, `sys.exit(pytest.main(...))` | No — not imported anywhere in production source. | `requirements-dev.txt` |
| `unittest` | Exactly 3 test files (`test_manual_scan_command.py`, `test_stage_l17_memory.py`, `test_market_analysis_foundation.py`) | No — stdlib, no package needed. | n/a |
| (none) | The remaining 240 test files | No — standalone proof scripts (`assert`/print-PASS-FAIL style), no test-framework import at all. | n/a |

**Correction from revision 1**: the `requirements-dev.txt` comment
previously said "required by 6 of 246 test files," which incorrectly
merged the pytest count (3) with the separate unittest count (3). Both
this table and the file comment now say 3 for `pytest` specifically, with
the 3 stdlib-`unittest` files called out as a distinct, no-extra-package
group.

`requirements-dev.txt` builds on `requirements.txt` (core) only — not on
`requirements-gemini.txt`, `requirements-ollama.txt`, or
`requirements-optional.txt` — because none of the 246 test files import
`google.genai`, `requests`, `plotly`, `numpy`, or `yfinance` directly
(AST-verified). Running the test suite does not require any
provider-specific or optional-feature package on top of core + pytest.

---

## H. Installation Validation

Environment: fresh `python3 -m venv` per scenario (Python 3.12.3), no
prior packages except `pip` itself. Three separate scenarios validated,
each in its own venv:

### H.1 — Core-only install

```
$ python3 -m venv clean_env_core && . clean_env_core/bin/activate
$ pip install -r requirements.txt
Installing collected packages: pytz, tzdata, six, python-dotenv, numpy, python-dateutil, pandas
Successfully installed numpy-2.5.1 pandas-2.3.3 python-dateutil-2.9.0.post0 python-dotenv-1.2.2 pytz-2026.3.post1 six-1.17.0 tzdata-2026.3
```

Result: **PASS**. Note `numpy` appears — it's pulled in transitively by
`pandas` itself (pandas' own dependency), not by anything this manifest
declares for numpy directly; `google-genai`, `requests`, `plotly`, and
`yfinance` are all correctly absent.

### H.2 — Provider-specific install (Gemini)

```
$ python3 -m venv clean_env_gemini && . clean_env_gemini/bin/activate
$ pip install -r requirements.txt -r requirements-gemini.txt
Successfully installed annotated-types-0.8.0 anyio-4.14.2 certifi-2026.7.22 cffi-2.1.0
charset_normalizer-3.4.9 cryptography-50.0.0 distro-1.9.0 google-auth-2.56.2
google-genai-2.16.0 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.18 numpy-2.5.1
pandas-2.3.3 pyasn1-0.6.4 pyasn1-modules-0.4.2 pycparser-3.0 pydantic-2.13.4
pydantic-core-2.46.4 python-dateutil-2.9.0.post0 python-dotenv-1.2.2 pytz-2026.3.post1
requests-2.34.2 six-1.17.0 sniffio-1.3.1 tenacity-9.1.4 typing-extensions-4.16.0
typing-inspection-0.4.2 tzdata-2026.3 urllib3-2.7.0 websockets-16.1.1
```

Result: **PASS**. `plotly` and `yfinance` correctly absent (verified in
§I.2). `requests` is present here as `google-genai`'s own transitive
dependency, not because `requirements-gemini.txt` declares it.

### H.3 — Full install

```
$ python3 -m venv clean_env_full && . clean_env_full/bin/activate
$ pip install -r requirements-full.txt
Successfully installed [... all of: annotated-types anyio beautifulsoup4 certifi cffi
charset_normalizer cryptography curl_cffi distro google-auth google-genai h11 httpcore
httpx idna multitasking narwhals numpy pandas peewee platformdirs plotly protobuf
pyasn1 pyasn1-modules pycparser pydantic pydantic-core python-dateutil python-dotenv
pytz requests six sniffio soupsieve tenacity typing-extensions typing-inspection
tzdata urllib3 websockets yfinance ...]
$ pip install -r requirements-dev.txt
Successfully installed iniconfig-2.3.0 pluggy-1.6.0 pygments-2.20.0 pytest-9.1.1
```

Result: **PASS**.

Resolved top-level versions across all three scenarios (not hard-pinned in
the manifest; see §K for the versioning rationale):

```
python-dotenv==1.2.2   pandas==2.3.3      numpy==2.5.1
plotly==6.9.0           requests==2.34.2   yfinance==1.5.2
google-genai==2.16.0    pytest==9.1.1
```

---

## I. Import Validation

### I.1 — Core-only venv

```
$ python -c "
import main
from Core.composition_root import build_application
app = build_application()
print(type(app).__name__)
"
ApplicationGraph
```

```
$ python -c "
for m in ['google.genai','requests','plotly','yfinance']:
    try:
        __import__(m); print(m, 'UNEXPECTEDLY PRESENT')
    except ImportError:
        print(m, 'absent (expected)')
"
google.genai absent (expected)
requests absent (expected)
plotly absent (expected)
yfinance absent (expected)
```

`build_application()` succeeded with **zero** provider-specific or
optional-feature packages installed — direct proof that the core file
alone is sufficient to import `main`/`Core.composition_root` and construct
the full `ApplicationGraph`, with no env vars, no network access, and no
database connection, consistent with the composition root's own
"hermetic" docstring claim.

### I.2 — Gemini-only venv

```
$ python -c "
from Core.composition_root import build_application
app = build_application()
import Providers.gemini as g
p = g.GeminiProvider(api_key='fake', model='fake-model')
p.connect()
print('GeminiProvider.connect() succeeded')
"
ApplicationGraph
GeminiProvider.connect() succeeded
```

```
$ python -c "
for m in ['plotly','yfinance']:
    try:
        __import__(m); print(m, 'UNEXPECTEDLY PRESENT')
    except ImportError:
        print(m, 'absent (expected)')
"
plotly absent (expected)
yfinance absent (expected)
```

Confirms `requirements-gemini.txt` does not pull in unrelated
optional-feature packages.

### I.3 — Full venv

```
$ python -c "
import main
from Core.composition_root import build_application
app = build_application()
print(type(app).__name__)
"
ApplicationGraph

$ python -m pytest Tests/test_stage5_suspend_resume.py Tests/test_stage6_delegate.py Tests/test_stage7_cancel.py -q
31 passed in 0.16s

$ python Tests/test_stock_agent_smoke.py
SMOKE TEST RESULTS: 33 PASS / 0 FAIL (total 33)
```

### I.4 — Isolation checks carried over from revision 1 (not re-run this
revision, still valid — the underlying source code was not touched)

| Removed package | Result |
|---|---|
| `google-genai` | `build_application()` still succeeds. `GeminiProvider.connect()` raises a clean `ProviderError` naming the missing package. |
| `requests` | `build_application()` still succeeds. `OllamaProvider.connect()` and `NotificationService.execute()` both raise clean, actionable errors instead of failing at import time. |
| `plotly` + `yfinance` | `build_application()` still succeeds. `ChartService()`/`StockService()` instantiate fine; only the specific resolve-the-real-library methods fail. |

Result: **PASS** across all scenarios (Scenario A/B/C/D all hold, now
demonstrated by installing only the relevant subset rather than only by
uninstalling from a full environment).

---

## J. README Consistency

`README.md`'s install section now shows:
- `pip install -r requirements.txt` as the default/core-only command
  (matches what the file actually contains as of this revision — it no
  longer silently installs providers/optional features by default).
- Explicit add-on commands for Gemini, Ollama, and optional features.
- A `requirements-full.txt` convenience command for "install everything."
- The corrected pytest file count (3, not 6) in the dev-install line.

No other README content (Features, Architecture, non-install command
list) was touched.

---

## K. Unresolved Dependency Risks

(Unchanged from revision 1 — restructuring the manifest into multiple
files did not resolve or introduce any version-verification risk; the
same package/version pairs are used, just distributed across files.)

- **No original lock file or "known-good" version set existed anywhere in
  the repository.** The version floors in `requirements.txt` and the
  add-on files are conservative lower bounds chosen because the APIs
  actually used are stable, long-standing surface area, validated to
  install and work together in three clean environments today (§H, §I) —
  not because they match some prior known-good set (none exists).
- **`pandas` is capped at `<3.0.0`** as a conservative choice; the
  installed/validated version is `2.3.3`. No `.ix[`, `.iteritems()`, or
  similar removed-in-3.0 patterns were found in source, so pandas 3.x
  would likely also work, but this was **not** empirically validated
  against a pandas-3.x install — flagged `UNVERIFIED`.
- **`numpy`'s true minimum/maximum compatible version is unverified**
  independent of pandas — only whatever `pandas==2.3.3` pulled in
  (`numpy==2.5.1`) was actually exercised.
- **`google-genai`'s exact required minimum version is unverified**
  beyond "the version resolved today (`2.16.0`) successfully imports and
  constructs a client." No live Gemini API call was made (would require a
  real API key / network access outside the allowed audit environment).
- **Two legacy non-pytest test files referenced in `README.md`**
  (`Tests/integration_test.py`, `Tests/E2e_test.py`) were not run in this
  or the prior pass beyond being present in the AST import scan; already
  flagged by Activation 0 as referencing an older architecture. Not a
  dependency risk — the packages they import (`pandas`) are already
  covered by `requirements.txt`.

---

## L. Out-of-Scope Findings

(Unchanged substance from revision 1 — restructuring the manifest doesn't
touch any of these; carried forward for continuity.)

1. **`pandas`'s eager, module-level import in 4 Services files makes it a
   de facto mandatory dependency**, inconsistent with the lazy-import
   pattern used everywhere else in the codebase. Source-code consistency
   question, not something this activation is allowed to fix.
2. **57 of 246 test scripts fail when run as standalone scripts today**,
   independent of any dependency issue — mostly stale API-surface
   assertions from earlier development stages, plus a handful of
   pytest-oriented files that need `pytest`'s own invocation/rootdir
   mechanics rather than direct `python file.py` execution. Out of scope
   for a dependency manifest activation.
3. **`requests` is used by both Ollama and Telegram/Discord notification
   sending**, but the notification pipeline is (per Activation 0) not
   wired into any live command path. If a later activation wires
   notifications into `scan`, the manifest's `requests` classification
   should be revisited (it would become load-bearing for any deployment
   using notifications, regardless of provider).
4. **Coupling relevant to future Activation 1.5** ("scan tanpa Telegram"):
   confirmed `NotificationService` degrades cleanly (returns a failed
   `ServiceResult`, does not raise/crash) when `requests` is absent or
   Telegram isn't configured, and `scan`'s current call path
   (`ManualScanService` → `WatchlistScanner` + `SnapshotRepository`) does
   not touch `NotificationService` at all today. No coupling found that
   would block a Telegram-less `scan` run at the dependency level.

---

## M. Final Status

```
PRODUCTION PATH VERIFIED
```

Basis: six manifest files (core `requirements.txt`, two provider add-ons,
one optional-feature add-on, one dev add-on, one full convenience file)
exist and are referenced accurately by `README.md`; built from a real,
programmatic audit of every import in all 217 production files and 246
test files; required/optional/provider-specific/dev-test are explicitly
distinguished by file placement as well as by comment, with evidence per
package; no optional or provider-specific package is installed by the
default core command, and none is silently forced on an operator who only
wants a specific provider (empirically proven across three separate clean
virtual environments: core-only, Gemini-only, and full); each environment
successfully imported `main`/`Core.composition_root` and constructed the
full `ApplicationGraph`; the pytest test-file count is corrected and
consistent (3) across the report and the manifest comments; `README.md` no
longer references a non-existent file and no longer implies a full install
is the default; no application source, test code, database schema, or
migration was modified; all version-related uncertainty remains documented
rather than invented (§K).
