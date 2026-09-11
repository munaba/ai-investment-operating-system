from __future__ import annotations

"""Activation 1.2 -- ``python main.py doctor``.

A read-only diagnostic command. It answers "is AIOS ready to run?" by
inspecting the *actual* environment (Python runtime, installed
packages, database file/migration state, the active provider's
configuration, Telegram configuration, and the market-data provider)
and classifying every check into exactly one of three buckets:

    READY             -- available / usable for what is being checked.
    OPTIONAL MISSING   -- unavailable, but does not block core usage.
    BLOCKED            -- unavailable/misconfigured in a way that
                          prevents the relevant command from working.

Hard boundaries (Activation 1.2 scope, see
``Docs/ACTIVATION 1/...`` prompt, sections 10-11):

  * Never creates the database file.
  * Never runs, repairs, or reverses a migration.
  * Never sends a Telegram message.
  * Never performs a paid/model-generation provider call (e.g. Gemini's
    ``count_tokens``/``generate_content``) -- only local, free checks
    (package import, credential presence, client construction with no
    network I/O, or a short-timeout local network probe such as
    Ollama's ``/api/tags``).
  * Never mutates ``Core.config.config`` / process env / any registry.

Reuse, not reinvention: which env vars are required for which active
provider comes straight from
``Core.startup_validation._REQUIRED_ENV_VARS_BY_PROVIDER_KIND`` (the
existing, previously-single-purpose lookup) -- this module does not
redeclare that list. The database path/pragma contract comes from
``Database.database_config.DatabaseConfig.from_env()``. The migration
ledger contract (``schema_migrations`` table + version numbers) comes
from ``Database.schema``/``Database.migrations_*``, unchanged.
"""

import importlib.util
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from Core.config import config
from Core.product_mode import resolve_product_mode
from Core.startup_validation import _REQUIRED_ENV_VARS_BY_PROVIDER_KIND, _DEFAULT_PROVIDER_KIND
from Database.database_config import DatabaseConfig
from Database.migration_registry import MIGRATION_MODULES as _MIGRATION_MODULES
from Database.migration_registry import expected_migrations as _expected_migrations

READY = "READY"
OPTIONAL_MISSING = "OPTIONAL MISSING"
BLOCKED = "BLOCKED"

#: Ordering used to compute a section's/overall's worst status -- higher
#: index wins. READY < OPTIONAL MISSING < BLOCKED.
_SEVERITY = {READY: 0, OPTIONAL_MISSING: 1, BLOCKED: 2}


def _worst(statuses: Sequence[str]) -> str:
    """Return the most severe status among ``statuses`` (``READY`` if empty)."""
    if not statuses:
        return READY
    return max(statuses, key=lambda status: _SEVERITY[status])


@dataclass
class CheckResult:
    """One diagnostic line item.

    Attributes:
        label: Short human-readable name (e.g. ``"pandas"``).
        status: One of ``READY``/``OPTIONAL_MISSING``/``BLOCKED``.
        detail: One-line explanation of *why* this status was chosen.
    """

    label: str
    status: str
    detail: str = ""


@dataclass
class Section:
    """A named group of :class:`CheckResult` (e.g. ``"Database"``).

    ``status`` is always the worst status among ``checks`` -- it is
    computed, never set independently, so a section can never silently
    disagree with its own line items.
    """

    name: str
    checks: List[CheckResult] = field(default_factory=list)
    note: str = ""

    @property
    def status(self) -> str:
        return _worst([c.status for c in self.checks])


@dataclass
class DoctorReport:
    """The full result of one ``doctor`` run."""

    sections: List[Section] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        return _worst([s.status for s in self.sections])

    @property
    def exit_code(self) -> int:
        """0 for READY/OPTIONAL MISSING only, non-zero if any BLOCKED.

        Section 7 of the Activation 1.2 spec: no convention existed in
        the repository prior to this command, so this is the minimal
        one established here -- OPTIONAL MISSING is never a command
        failure.
        """
        return 1 if self.overall_status == BLOCKED else 0


# ---------------------------------------------------------------------------
# 4.1 Python version
# ---------------------------------------------------------------------------

def _check_python_version() -> Section:
    """Report the running interpreter's version.

    No minimum Python version is declared anywhere in this repository
    (no ``pyproject.toml``/``setup.py``/``setup.cfg``/``runtime.txt``/
    ``.python-version`` audited in Section 3 of the Activation 1.2
    prompt). Per that prompt's Section 4.1, doctor must not invent one:
    the interpreter that is running *this command right now* is, by
    definition, capable of running the source (imports below are the
    proof), so this is reported READY with an explicit note that a
    minimum has not been declared/verified anywhere else in source.
    """
    version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    check = CheckResult(
        label="Python version",
        status=READY,
        detail=(
            f"{version_str} -- running and able to import the application. "
            "No minimum Python version is declared in source "
            "(no pyproject.toml/setup.py/setup.cfg found); minimum-version "
            "conformance is therefore UNVERIFIED, not asserted."
        ),
    )
    return Section(name="Python", checks=[check])


# ---------------------------------------------------------------------------
# 4.2 Required dependency
# ---------------------------------------------------------------------------

#: (import name, display label) for packages required unconditionally
#: to import Core.composition_root / start main.py. Source: Docs
#: /ACTIVATION 1/requirements.txt (Activation 1.1's audited manifest) --
#: this is exactly that file's two entries, not a re-derived guess.
_CORE_REQUIRED_PACKAGES: Sequence[tuple[str, str]] = (
    ("dotenv", "python-dotenv"),
    ("pandas", "pandas"),
)

#: (import name, display label) per active-provider-kind -- only the
#: kind actually selected via ACTIVE_PROVIDER is treated as required;
#: the other is optional. Source: Docs/ACTIVATION 1/requirements-gemini.txt
#: and requirements-ollama.txt.
_PROVIDER_PACKAGES = {
    "gemini": ("google.genai", "google-genai"),
    "ollama": ("requests", "requests"),
}

#: (import name, display label) for feature-optional packages that are
#: never required to import/start the app. Source: Docs/ACTIVATION 1
#: /requirements-optional.txt.
_OPTIONAL_FEATURE_PACKAGES: Sequence[tuple[str, str]] = (
    ("plotly", "plotly"),
    ("numpy", "numpy"),
    ("yfinance", "yfinance"),
)


def _is_importable(module_name: str) -> bool:
    """True if ``module_name`` can be imported without actually importing it.

    Uses ``importlib.util.find_spec`` (not a live ``import``) so a
    present-but-broken package doesn't crash doctor -- consistent with
    every other check in this module never raising.
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _active_provider_kind() -> str:
    """Same resolution ``Core.startup_validation.validate_runtime_environment``
    and ``Core.composition_root.build_application`` already use:
    ``ACTIVE_PROVIDER``, defaulting to ``"gemini"``."""
    return config.get("ACTIVE_PROVIDER", _DEFAULT_PROVIDER_KIND)


def _check_dependencies() -> Section:
    checks: List[CheckResult] = []

    for import_name, label in _CORE_REQUIRED_PACKAGES:
        present = _is_importable(import_name)
        checks.append(
            CheckResult(
                label=label,
                status=READY if present else BLOCKED,
                detail="importable" if present else (
                    f"not installed -- required by core startup "
                    f"(Docs/ACTIVATION 1/requirements.txt)"
                ),
            )
        )

    active_kind = _active_provider_kind()
    for kind, (import_name, label) in _PROVIDER_PACKAGES.items():
        present = _is_importable(import_name)
        is_active = kind == active_kind
        if present:
            status, detail = READY, "importable"
        elif is_active:
            status, detail = BLOCKED, (
                f"not installed -- required because ACTIVE_PROVIDER='{active_kind}'"
            )
        else:
            status, detail = OPTIONAL_MISSING, (
                f"not installed -- only needed if ACTIVE_PROVIDER='{kind}'"
            )
        checks.append(CheckResult(label=f"{label} ({kind} provider)", status=status, detail=detail))

    for import_name, label in _OPTIONAL_FEATURE_PACKAGES:
        present = _is_importable(import_name)
        checks.append(
            CheckResult(
                label=label,
                status=READY if present else OPTIONAL_MISSING,
                detail="importable" if present else "not installed -- optional feature only",
            )
        )

    return Section(name="Required Dependencies", checks=checks)


# ---------------------------------------------------------------------------
# 4.3 / 4.4 Database path + migration status
#
# _MIGRATION_MODULES / _expected_migrations() moved to
# Database.migration_registry as part of Activation 1.3 (see that
# module's docstring) so `python main.py init` and `doctor` share
# exactly one canonical migration ordering, imported above rather than
# declared twice.
# ---------------------------------------------------------------------------


def _check_database_and_migrations(db_config: DatabaseConfig) -> tuple[Section, Section]:
    """Inspect (never create/modify) the database file and its migration
    ledger.

    Read-only by construction: the database file is only ever opened
    via a ``sqlite3`` URI connection in ``mode=ro`` (SQLite's own
    read-only open mode), and only *after* confirming the file already
    exists on disk -- so a missing database is reported as missing, not
    silently created (``Database.sqlite_database.SQLiteDatabase.connect()``
    -- the production connection path -- creates the file on first
    open, which is exactly the side effect doctor must never trigger).
    """
    db_path = Path(db_config.db_path)
    db_checks: List[CheckResult] = []

    db_checks.append(
        CheckResult(label="Path configured", status=READY, detail=f"DB_PATH -> {db_path}")
    )

    parent_dir = db_path.parent
    parent_exists = parent_dir.exists() or str(parent_dir) in ("", ".")
    db_checks.append(
        CheckResult(
            label="Directory",
            status=READY if parent_exists else OPTIONAL_MISSING,
            detail=(
                f"{parent_dir} exists" if parent_exists
                else f"{parent_dir} does not exist yet (created on first real connect)"
            ),
        )
    )

    file_exists = db_path.is_file()
    db_checks.append(
        CheckResult(
            label="Database file",
            status=READY if file_exists else OPTIONAL_MISSING,
            detail=(
                f"{db_path} exists"
                if file_exists
                else f"{db_path} does not exist -- database has not been initialized yet"
            ),
        )
    )

    database_section = Section(name="Database", checks=db_checks)

    migration_checks: List[CheckResult] = []
    if not file_exists:
        migration_checks.append(
            CheckResult(
                label="Migration status",
                status=BLOCKED,
                detail=(
                    "Database not initialized -- no migrations can have run. "
                    "Not a migration failure; run the domain migration scripts "
                    "(e.g. run_watchlist_migrations.py) or a future Activation "
                    "1.3 unified runner to initialize."
                ),
            )
        )
        return database_section, Section(name="Migrations", checks=migration_checks)

    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            has_table = cursor.fetchone() is not None
            if not has_table:
                migration_checks.append(
                    CheckResult(
                        label="Migration metadata",
                        status=BLOCKED,
                        detail=(
                            "Database file exists but has no 'schema_migrations' "
                            "table -- migration state is unavailable/uninitialized."
                        ),
                    )
                )
            else:
                cursor.execute("SELECT version, name FROM schema_migrations")
                applied = {int(row[0]): row[1] for row in cursor.fetchall()}
                expected = _expected_migrations()
                pending = [
                    (version, name, domain)
                    for version, name, domain in expected
                    if version not in applied
                ]
                if pending:
                    pending_desc = ", ".join(
                        f"{domain}:v{version} '{name}'" for version, name, domain in pending
                    )
                    migration_checks.append(
                        CheckResult(
                            label="Migration status",
                            status=BLOCKED,
                            detail=f"{len(pending)} pending migration(s): {pending_desc}",
                        )
                    )
                else:
                    migration_checks.append(
                        CheckResult(
                            label="Migration status",
                            status=READY,
                            detail=f"current -- all {len(expected)} known migration(s) applied",
                        )
                    )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        migration_checks.append(
            CheckResult(
                label="Migration status",
                status=BLOCKED,
                detail=f"Database file exists but could not be read: {exc}",
            )
        )

    return database_section, Section(name="Migrations", checks=migration_checks)


# ---------------------------------------------------------------------------
# 4.5 Provider availability
# ---------------------------------------------------------------------------

def _check_provider() -> Section:
    active_kind = _active_provider_kind()
    checks: List[CheckResult] = []

    required_vars = _REQUIRED_ENV_VARS_BY_PROVIDER_KIND.get(active_kind)
    if required_vars is None:
        checks.append(
            CheckResult(
                label="Active provider",
                status=BLOCKED,
                detail=(
                    f"ACTIVE_PROVIDER='{active_kind}' is not a recognized "
                    f"provider kind (known: {sorted(_REQUIRED_ENV_VARS_BY_PROVIDER_KIND)})"
                ),
            )
        )
        return Section(name=f"Active Provider ({active_kind})", checks=checks)

    import_name, package_label = _PROVIDER_PACKAGES[active_kind]
    dependency_ok = _is_importable(import_name)
    checks.append(
        CheckResult(
            label="Dependency installed",
            status=READY if dependency_ok else BLOCKED,
            detail=f"{package_label} {'importable' if dependency_ok else 'NOT installed'}",
        )
    )

    missing_vars = [v for v in required_vars if config.get(v) is None]
    credential_ok = not missing_vars
    checks.append(
        CheckResult(
            label="Credential/config present",
            status=READY if credential_ok else BLOCKED,
            detail=(
                "all required variables set"
                if credential_ok
                else f"missing: {', '.join(missing_vars)}"
            ),
        )
    )

    if not dependency_ok or not credential_ok:
        checks.append(
            CheckResult(
                label="Provider reachable",
                status=BLOCKED,
                detail="skipped -- dependency/credential prerequisite failed above",
            )
        )
        return Section(name=f"Active Provider ({active_kind})", checks=checks)

    if active_kind == "gemini":
        # GeminiProvider.health_check() calls the real count_tokens API --
        # a billed request. Section 11 forbids that here. connect() only
        # constructs genai.Client(api_key=...) locally (no network I/O),
        # so it is used as the safe upper bound for "can this even be
        # constructed" without ever making a call.
        try:
            from Providers.gemini import GeminiProvider

            provider = GeminiProvider()
            provider.connect()
            checks.append(
                CheckResult(
                    label="Provider reachable",
                    status=READY,
                    detail=(
                        "Gemini client constructed successfully. Actual "
                        "reachability is NOT verified here -- Gemini's only "
                        "connectivity check (count_tokens) is a billed API "
                        "call and doctor never makes one."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                CheckResult(label="Provider reachable", status=BLOCKED, detail=str(exc))
            )
    elif active_kind == "ollama":
        # OllamaProvider.health_check() is a local, free GET /api/tags --
        # built with a short, doctor-specific timeout so an unreachable
        # host cannot hang this command (Section 11).
        try:
            from Providers.ollama import OllamaProvider

            provider = OllamaProvider(timeout=3.0)
            reachable = provider.health_check()
            checks.append(
                CheckResult(
                    label="Provider reachable",
                    status=READY if reachable else BLOCKED,
                    detail=(
                        "GET /api/tags responded"
                        if reachable
                        else "Ollama host did not respond within 3s (network/host unavailable)"
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                CheckResult(label="Provider reachable", status=BLOCKED, detail=str(exc))
            )

    return Section(name=f"Active Provider ({active_kind})", checks=checks)


# ---------------------------------------------------------------------------
# 4.6 Telegram configuration
# ---------------------------------------------------------------------------

#: NOTE on these two names: source has no dedicated env-var contract for
#: Telegram credentials today -- Services/notification_service.py reads
#: them only from ServiceContext.metadata
#: (MetadataKeys.TELEGRAM_BOT_TOKEN / .TELEGRAM_CHAT_ID), supplied by
#: whatever caller builds that context; no Core.config binding exists
#: yet (Section 3 audit: no call site does
#: ``config.get("TELEGRAM_BOT_TOKEN")`` anywhere in source). These two
#: names are the natural env-var spelling of those same metadata keys,
#: consistent with this project's GEMINI_API_KEY/OLLAMA_HOST naming
#: convention -- checked here as a best-effort, clearly-labeled
#: convention, not as a confirmed source contract. See the deliverable
#: report's Out-of-Scope Findings.
_TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def _check_telegram() -> Section:
    bot_token = config.get(_TELEGRAM_BOT_TOKEN_ENV)
    chat_id = config.get(_TELEGRAM_CHAT_ID_ENV)
    missing = [
        name
        for name, value in ((_TELEGRAM_BOT_TOKEN_ENV, bot_token), (_TELEGRAM_CHAT_ID_ENV, chat_id))
        if not value
    ]

    if not missing:
        check = CheckResult(
            label="Telegram credentials",
            status=READY,
            detail=f"{_TELEGRAM_BOT_TOKEN_ENV} and {_TELEGRAM_CHAT_ID_ENV} are both set",
        )
    else:
        # Per prompt Section 4.6/2.6: Telegram is not a wired production
        # dependency today (no live command path calls
        # NotificationService.execute()), so missing credentials are
        # OPTIONAL MISSING, never BLOCKED.
        check = CheckResult(
            label="Telegram credentials",
            status=OPTIONAL_MISSING,
            detail=(
                f"not configured (missing: {', '.join(missing)}) -- Telegram "
                "is not required by any current production command path"
            ),
        )

    section = Section(name="Telegram", checks=[check])
    return section


# ---------------------------------------------------------------------------
# Phase E Task 6 -- Telegram Inbound Control Plane diagnostic section
#
# Distinct from ``_check_telegram()`` above (Activation 1.2, outbound
# notifications only, unmodified by this task). This section is about
# the Phase E inbound command path (``python main.py telegram poll`` /
# ``telegram status``) -- allowlist configuration, the durable
# long-poll offset, and the most recent inbound command outcome.
# Read-only, same hard boundaries as every other doctor section: never
# creates the database file, never runs/repairs a migration, never
# calls Telegram (no ``getUpdates``/``sendMessage`` here), never
# mutates ``Core.config.config``. Every check below is wrapped so a
# failure becomes an explicit BLOCKED line with the real exception
# message -- this section fails visibly, never silently.
# ---------------------------------------------------------------------------


def _check_telegram_inbound_control_plane(db_config: DatabaseConfig) -> Section:
    """Report allowlist configuration, credential presence, the
    ``telegram_control`` migration/table state, the durable poll
    offset, and the most recent inbound command's outcome.
    """
    checks: List[CheckResult] = []

    # --- Bot token: required for both getUpdates (polling) and replies.
    # Unlike _check_telegram()'s OPTIONAL_MISSING (no outbound command
    # path depended on it before this task), the inbound control plane
    # cannot poll or reply at all without it, so a missing token here
    # is reported BLOCKED -- it directly prevents `telegram poll` /
    # `telegram status` from working, per this module's own BLOCKED
    # definition.
    try:
        bot_token = config.get(_TELEGRAM_BOT_TOKEN_ENV)
        checks.append(
            CheckResult(
                label="Bot token",
                status=READY if bot_token else BLOCKED,
                detail=(
                    f"{_TELEGRAM_BOT_TOKEN_ENV} is set"
                    if bot_token
                    else f"{_TELEGRAM_BOT_TOKEN_ENV} is not set -- "
                    "`telegram poll`/`telegram status` cannot reach the Telegram API"
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(CheckResult(label="Bot token", status=BLOCKED, detail=str(exc)))

    # --- Allowlist: fail-closed by design (Business.telegram_allowlist_policy
    # docstring, LOCKED). An empty allowlist means every inbound chat is
    # REJECTED_UNAUTHORIZED, which is a real operational block on the
    # feature (nobody can issue a command), so it is reported BLOCKED
    # here rather than silently appearing as "0 commands executed".
    try:
        from Business.telegram_allowlist_policy import load_telegram_allowlist_policy

        policy = load_telegram_allowlist_policy()
        allowed = sorted(policy.allowed_chat_ids)
        if allowed:
            checks.append(
                CheckResult(
                    label="Allowlist",
                    status=READY,
                    detail=f"{len(allowed)} chat id(s) authorized: {', '.join(allowed)}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    label="Allowlist",
                    status=BLOCKED,
                    detail=(
                        "no TELEGRAM_ALLOWED_CHAT_IDS/TELEGRAM_CHAT_ID configured -- "
                        "fails closed: every inbound chat is REJECTED_UNAUTHORIZED"
                    ),
                )
            )
    except Exception as exc:  # noqa: BLE001
        checks.append(CheckResult(label="Allowlist", status=BLOCKED, detail=str(exc)))

    # --- Table/migration state + polling offset + most recent outcome:
    # a single read-only sqlite connection, mirroring
    # _check_database_and_migrations()'s own "mode=ro, only if the file
    # already exists" contract -- never opens/creates the database,
    # never runs a migration.
    db_path = Path(db_config.db_path)
    if not db_path.is_file():
        checks.append(
            CheckResult(
                label="telegram_control tables",
                status=BLOCKED,
                detail=(
                    f"{db_path} does not exist -- database has not been initialized; "
                    "run the domain migration scripts first"
                ),
            )
        )
        return Section(name="Telegram Inbound Control Plane", checks=checks)

    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('telegram_command_audit', 'telegram_inbound_state')"
            )
            present_tables = {row[0] for row in cursor.fetchall()}
            required_tables = {"telegram_command_audit", "telegram_inbound_state"}
            missing_tables = required_tables - present_tables

            if missing_tables:
                checks.append(
                    CheckResult(
                        label="telegram_control tables",
                        status=BLOCKED,
                        detail=(
                            f"missing table(s): {', '.join(sorted(missing_tables))} -- "
                            "run `python run_telegram_control_migrations.py`"
                        ),
                    )
                )
                return Section(name="Telegram Inbound Control Plane", checks=checks)

            checks.append(
                CheckResult(
                    label="telegram_control tables",
                    status=READY,
                    detail="telegram_command_audit and telegram_inbound_state both exist",
                )
            )

            # Durable long-poll offset (Task 1's own restart-safety state).
            cursor.execute(
                "SELECT last_update_id, updated_at FROM telegram_inbound_state "
                "WHERE state_key = 'default'"
            )
            state_row = cursor.fetchone()
            if state_row is None:
                checks.append(
                    CheckResult(
                        label="Polling state",
                        status=OPTIONAL_MISSING,
                        detail="no offset recorded yet -- `telegram poll` has never run",
                    )
                )
            else:
                last_update_id, updated_at = state_row
                checks.append(
                    CheckResult(
                        label="Polling state",
                        status=READY,
                        detail=f"last_update_id={last_update_id} (updated_at={updated_at})",
                    )
                )

            # Most recent inbound command outcome -- surfaces a real
            # failure (ERROR / EXECUTED_REPLY_FAILED) visibly rather
            # than letting it sit silently in the audit table.
            cursor.execute(
                "SELECT command, status, detail, received_at FROM telegram_command_audit "
                "ORDER BY id DESC LIMIT 1"
            )
            audit_row = cursor.fetchone()
            if audit_row is None:
                checks.append(
                    CheckResult(
                        label="Most recent command",
                        status=OPTIONAL_MISSING,
                        detail="no inbound commands recorded yet",
                    )
                )
            else:
                command, status, detail, received_at = audit_row
                failed_statuses = {"ERROR", "EXECUTED_REPLY_FAILED"}
                checks.append(
                    CheckResult(
                        label="Most recent command",
                        status=BLOCKED if status in failed_statuses else READY,
                        detail=(
                            f"{command!r} -> {status} at {received_at}"
                            + (f" ({detail})" if detail else "")
                        ),
                    )
                )
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 -- never let a diagnostic
        # read fail silently; surface it as an explicit BLOCKED line.
        checks.append(
            CheckResult(label="telegram_control tables", status=BLOCKED, detail=str(exc))
        )

    return Section(name="Telegram Inbound Control Plane", checks=checks)


# ---------------------------------------------------------------------------
# 4.7 Data provider availability
# ---------------------------------------------------------------------------

def _check_data_provider() -> Section:
    present = _is_importable("yfinance")
    if present:
        check = CheckResult(
            label="yfinance",
            status=READY,
            detail=(
                "importable. Reachability against Yahoo Finance's live "
                "service is NOT verified here -- doctor performs no network "
                "download to avoid rate limits/large transfers (Section 4.7)."
            ),
        )
    else:
        check = CheckResult(
            label="yfinance",
            status=OPTIONAL_MISSING,
            detail=(
                "not installed -- application core still starts without it, "
                "but 'scan'/'auto' need it to return real market data"
            ),
        )
    return Section(name="Market Data Provider", checks=[check])


# ---------------------------------------------------------------------------
# Phase A -- Product mode
# ---------------------------------------------------------------------------

def _check_product_mode() -> Section:
    """Report the active product mode and what it structurally allows.

    Read-only: only reads ``AIOS_PRODUCT_MODE`` via
    ``Core.product_mode.resolve_product_mode()``, which itself performs
    no I/O and mutates nothing.
    """
    status = resolve_product_mode()
    checks: List[CheckResult] = []

    checks.append(
        CheckResult(
            label="Active mode",
            status=READY if status.recognized else BLOCKED,
            detail=(
                f"AIOS_PRODUCT_MODE='{status.mode}'"
                if status.recognized
                else (
                    f"AIOS_PRODUCT_MODE='{status.mode}' is not a recognized "
                    f"product mode (known: decision_copilot). Refusing to "
                    f"guess -- treating live execution as disabled and "
                    f"broker credentials as required until this is fixed."
                )
            ),
        )
    )
    checks.append(
        CheckResult(
            label="Broker/live execution",
            status=READY if status.live_execution_disabled else BLOCKED,
            detail=(
                "disabled -- no broker adapter exists in this codebase "
                "(Activation 8 not built) and "
                "Orchestration.permission_context.PermissionContext "
                "defaults live_execution_allowed=False with no override "
                "anywhere in Core.composition_root"
                if status.live_execution_disabled
                else "NOT disabled -- this mode permits live execution"
            ),
        )
    )
    checks.append(
        CheckResult(
            label="Broker credentials",
            status=READY if not status.broker_credentials_required else OPTIONAL_MISSING,
            detail=(
                "not required -- decision_copilot never reads a broker "
                "credential and no broker connectivity check exists"
                if not status.broker_credentials_required
                else "required by this (unrecognized) mode, but none is configured"
            ),
        )
    )

    return Section(name="Product Mode", checks=checks)


# ---------------------------------------------------------------------------
# Phase A -- Scheduler state
# ---------------------------------------------------------------------------

def _check_scheduler() -> Section:
    """Report the scheduler's structural state.

    ``Orchestration.autonomous_scheduler.AutonomousScheduler`` is a
    synchronous, in-process FIFO queue -- no threading, no asyncio, no
    cron, no daemon, and no persistence of any kind (its own docstring
    is explicit: the queue lives only in the instance's process memory
    and is lost when the instance is garbage collected). There is
    therefore no on-disk/DB scheduler state for doctor to inspect or
    that could be "stale" -- this check instead confirms the module
    imports cleanly (i.e. ``python main.py scheduler tick`` would be
    able to construct it) and reports its actual persistence model so
    that absence of on-disk state is never mistaken for a problem.
    """
    try:
        from Orchestration.autonomous_scheduler import AutonomousScheduler  # noqa: F401

        check = CheckResult(
            label="Scheduler module",
            status=READY,
            detail=(
                "Orchestration.autonomous_scheduler.AutonomousScheduler "
                "importable. In-process/synchronous only -- no background "
                "daemon, no cron, no persisted job queue by design, so "
                "there is no on-disk scheduler state to report as stale."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        check = CheckResult(label="Scheduler module", status=BLOCKED, detail=str(exc))

    return Section(name="Scheduler", checks=[check])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_doctor() -> DoctorReport:
    """Run every Activation 1.2 diagnostic check and return the report.

    Read-only: builds no ``ApplicationGraph``, opens no write
    connection, sends nothing, and never calls
    ``Core.startup_validation.validate_runtime_environment()`` /
    ``Core.composition_root.build_application()`` (those enforce
    "must succeed to run" -- exactly the opposite of doctor's job,
    which is to explain *why* they would or would not succeed).
    """
    sections: List[Section] = [_check_product_mode(), _check_python_version(), _check_dependencies()]

    db_config = DatabaseConfig.from_env()
    database_section, migrations_section = _check_database_and_migrations(db_config)
    sections.append(database_section)
    sections.append(migrations_section)

    sections.append(_check_provider())
    sections.append(_check_telegram())
    sections.append(_check_telegram_inbound_control_plane(db_config))
    sections.append(_check_data_provider())
    sections.append(_check_scheduler())

    # Activation 12: additive, read-only self-diagnostic sections.
    from Core.self_diagnostic import run_self_diagnostic
    sections.extend(run_self_diagnostic(db_config))

    return DoctorReport(sections=sections)


def format_report(report: DoctorReport) -> str:
    """Render ``report`` as the CLI text block ``main.py doctor`` prints."""
    lines: List[str] = []
    lines.append("AIOS DOCTOR")
    lines.append("=" * 60)
    for section in report.sections:
        lines.append("")
        lines.append(f"{section.name}")
        for check in section.checks:
            lines.append(f"  [{check.status:<16}] {check.label}")
            if check.detail:
                lines.append(f"      {check.detail}")
        lines.append(f"  -> {section.name} overall: {section.status}")

    lines.append("")
    lines.append("-" * 60)
    lines.append(f"OVERALL: {report.overall_status}")
    lines.append("-" * 60)
    return "\n".join(lines)


def run_doctor_command(print_fn: Callable[[str], None] = print) -> int:
    """Entry point called from ``main.py``'s ``python main.py doctor`` path.

    Args:
        print_fn: Injection point for tests to capture output instead of
            writing to real stdout. Defaults to the builtin ``print``.

    Returns:
        The process exit code (see :attr:`DoctorReport.exit_code`).
    """
    report = run_doctor()
    print_fn(format_report(report))
    return report.exit_code