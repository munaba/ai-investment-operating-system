from __future__ import annotations

"""Activation 1.4 -- application bootstrap data for ``python main.py init``.

Runs *after* ``Core.init_command.run_init`` has applied every schema
migration. Where migration is responsible for structure, this module is
responsible for the minimum application data AIOS needs to be usable
without manual database configuration:

  * a default paper account (deterministic identity, never duplicated,
    never reset on rerun);
  * confirmation the watchlist is readable (it starts empty -- schema
    alone already guarantees that, see module docstring below, so this
    step verifies rather than seeds);
  * a safe, secret-free ``.env.example`` template, created only if
    absent.

Reuses existing abstractions rather than reimplementing them:
``Repository.persistence.account_repository.AccountRepository`` and
``Repository.persistence.watchlist_repository.WatchlistRepository``,
both already constructed the same way ``Core.composition_root`` builds
them (``Repository(database_manager)``) -- no new persistence code, no
bypassing the repository layer.

Domain decisions this module encodes (explicitly confirmed, not
invented -- see the Activation 1.4 audit/report that preceded this
module):

  * default paper account: ``account_id="paper"``,
    ``account_name="Munaba"``, ``mode="paper"``,
    ``asset_class="stock_id"``, ``currency="IDR"``.
  * initial balance: reuses the value of
    ``Core.analysis_pipeline._DEFAULT_ACCOUNT_BALANCE`` (100,000,000)
    -- the only existing "default account balance" convention already
    in source (used there as the position-sizing fallback when no
    account balance is otherwise known). Not re-imported directly
    (that name is private to its own module) but the same number, for
    the same reason: it is the sole established default, not a new
    invention. Flagged explicitly in the Activation 1.4 report for the
    user to override if a different default balance is wanted.

Watchlist: the ``watchlist`` table (``Database.migrations_watchlist``)
is already part of the canonical migration registry
(``Database.migration_registry.all_migrations``) that ``run_init``
applies before this module ever runs, so a fresh database already has
an empty ``watchlist`` table with zero rows -- there is no separate
watchlist "header" entity to create (see
``Repository.persistence.watchlist_repository.WatchlistRepository``'s
own docstring: a flat ``ticker``/``added_at`` table, no surrogate id).
``ensure_watchlist_ready`` therefore never inserts anything -- it only
proves the repository can read the table, which is also the evidence
``python main.py doctor`` needs (Section 13).

Config template: content mirrors the Section 8 example exactly for the
Gemini/Ollama variables, which have a confirmed contract in
``Core.startup_validation.REQUIRED_RUNTIME_ENV_VARS`` /
``OLLAMA_REQUIRED_RUNTIME_ENV_VARS``. Telegram variables are NOT given
as live template lines -- ``Core.doctor``'s own ``_check_telegram()``
docstring says plainly there is no confirmed env-var contract for them
yet, only a same-naming-convention guess -- so they are included only
as a commented-out, clearly-labeled convention, per Section 8's
instruction not to promote them to an official contract on my own
authority.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

from Core.exceptions import BootstrapError
from Database.models import Account
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.watchlist_repository import WatchlistRepository

# --- Default paper account (confirmed domain decision) ----------------

DEFAULT_PAPER_ACCOUNT_ID: str = "paper"
DEFAULT_PAPER_ACCOUNT_NAME: str = "Munaba"
DEFAULT_PAPER_ACCOUNT_MODE: str = "paper"
DEFAULT_PAPER_ACCOUNT_ASSET_CLASS: str = "stock_id"
DEFAULT_PAPER_ACCOUNT_CURRENCY: str = "IDR"

#: Initial cash/equity/buying_power for the default paper account.
#: Reuses the same value as ``Core.analysis_pipeline._DEFAULT_ACCOUNT_BALANCE``
#: -- see module docstring above for why this specific number, and that
#: it is an assumption flagged for override, not a Section-6-style
#: confirmed decision like the identity fields above it.
DEFAULT_PAPER_ACCOUNT_BALANCE: float = 100_000_000.0

# --- Crypto prototype: default USD paper account (ASSUMPTION -- flagged) --
#
# No new schema, no new repository: ``asset_class="crypto"`` and an
# arbitrary ``currency`` string were already valid under the existing
# ``accounts`` table CHECK constraints (``Database.account_constants``,
# migration version=2, applied since Sprint 3 STEP 3) -- see that
# module's docstring, which already lists ``"crypto-main"`` as an
# example ``account_id``. This block only adds a second, independent
# default-account identity, following the exact same idempotent
# create-if-absent pattern as ``ensure_default_paper_account`` below.
# No FX: currency is stored as a plain label, never converted against
# ``DEFAULT_PAPER_ACCOUNT_CURRENCY`` ("IDR") or any other currency --
# this account's cash/equity/buying_power are USD figures, full stop.
# No changes to trading logic, order validation, or any crypto
# strategy code -- this is account/bootstrap scope only.
DEFAULT_CRYPTO_ACCOUNT_ID: str = "crypto-usd"
DEFAULT_CRYPTO_ACCOUNT_NAME: str = "Crypto USD"
DEFAULT_CRYPTO_ACCOUNT_MODE: str = "paper"
DEFAULT_CRYPTO_ACCOUNT_ASSET_CLASS: str = "crypto"
DEFAULT_CRYPTO_ACCOUNT_CURRENCY: str = "USD"

#: Initial cash/equity/buying_power for the default crypto paper
#: account. UNLIKE ``DEFAULT_PAPER_ACCOUNT_BALANCE`` this is NOT a
#: reused, already-established convention -- no prior USD-denominated
#: default exists anywhere in the codebase to reuse (reusing the IDR
#: figure of 100,000,000 verbatim as if it were USD would silently
#: fabricate a $100M paper account, which is not something this
#: change should decide on its own). 100,000.0 is a placeholder pick
#: for prototype purposes ONLY -- flagged explicitly for Nabil to
#: confirm or override, same as the IDR default above was flagged
#: when it was first introduced.
DEFAULT_CRYPTO_ACCOUNT_BALANCE: float = 100_000.0

# --- Activation 9.1: default USD paper account for US stocks (ASSUMPTION) -
#
# Same reasoning and same idempotent create-if-absent pattern as the
# crypto block immediately above -- no new schema, no new repository.
# ``asset_class="stock_us"`` was already a valid value under the
# existing ``accounts`` table CHECK constraint before this Activation
# (``Database.account_constants.ACCOUNT_ASSET_CLASSES`` already listed
# it -- confirmed by reading that file, not added here). This block
# only adds a third, independent default-account identity, additive to
# both ``ensure_default_paper_account`` (IDR/stock_id) and
# ``ensure_default_crypto_account`` (USD/crypto) -- neither of those
# two functions, nor their account rows, are touched by this addition.
# No FX: currency is stored as a plain label, never converted against
# either of the other two accounts' currencies. No changes to trading
# logic, order validation, ``PaperTradingEngine``, or
# ``ExecutionPolicy`` -- this is account/bootstrap scope only, exactly
# like the crypto block.
DEFAULT_US_ACCOUNT_ID: str = "us-usd"
DEFAULT_US_ACCOUNT_NAME: str = "US Stocks USD"
DEFAULT_US_ACCOUNT_MODE: str = "paper"
DEFAULT_US_ACCOUNT_ASSET_CLASS: str = "stock_us"
DEFAULT_US_ACCOUNT_CURRENCY: str = "USD"

#: Initial cash/equity/buying_power for the default US paper account.
#: Reuses ``DEFAULT_CRYPTO_ACCOUNT_BALANCE``'s own placeholder value
#: (100,000.0) rather than inventing a third, different USD figure --
#: both are USD-denominated paper prototypes with no prior established
#: convention of their own to reuse, so this follows the closer
#: precedent (the other USD account) rather than the unrelated IDR
#: one. Flagged explicitly for Nabil to confirm or override, same as
#: the crypto figure was.
DEFAULT_US_ACCOUNT_BALANCE: float = DEFAULT_CRYPTO_ACCOUNT_BALANCE

# --- Activation 11.21: default USD paper account for Forex (ASSUMPTION) --
#
# Same reasoning and same idempotent create-if-absent pattern as the
# crypto/US blocks immediately above -- no new schema, no new
# repository. ``asset_class="forex"`` was already a valid value under
# the existing ``accounts`` table CHECK constraint before this
# Activation (``Database.account_constants.ACCOUNT_ASSET_CLASSES``
# already listed it -- confirmed by reading that file, not added
# here; it has also been the LOCKED account-currency decision since
# Activation 11.1 Decision A: "The initial Forex paper account is
# USD-only"). This block only adds a fourth, independent default-
# account identity, additive to ``ensure_default_paper_account``
# (IDR/stock_id), ``ensure_default_crypto_account`` (USD/crypto), and
# ``ensure_default_us_account`` (USD/stock_us) -- none of those three
# functions, nor their account rows, are touched by this addition.
# No FX: currency is stored as a plain label, never converted against
# any other account's currency. No changes to trading logic, order
# validation, ``PaperTradingEngine``, margin/pip/stop-loss/max-loss
# policy, or any market/analysis routing -- this is account/bootstrap
# scope only, exactly like the crypto/US blocks (Activation 11.21 is
# explicitly scoped to account bootstrap alone; paper BUY/SELL,
# ``--market forex``, and Forex analysis routing are separate,
# later atomic steps).
DEFAULT_FOREX_ACCOUNT_ID: str = "forex-usd"
DEFAULT_FOREX_ACCOUNT_NAME: str = "Forex USD"
DEFAULT_FOREX_ACCOUNT_MODE: str = "paper"
DEFAULT_FOREX_ACCOUNT_ASSET_CLASS: str = "forex"
DEFAULT_FOREX_ACCOUNT_CURRENCY: str = "USD"

#: Initial cash/equity/buying_power for the default Forex paper
#: account. Reuses ``DEFAULT_CRYPTO_ACCOUNT_BALANCE``'s own
#: placeholder value (100,000.0) rather than inventing a fourth,
#: different USD figure -- same reasoning ``DEFAULT_US_ACCOUNT_BALANCE``
#: already applied: all three USD-denominated paper prototypes
#: (crypto/US/forex) share one placeholder convention, only the
#: original IDR default is different. Flagged explicitly for Nabil to
#: confirm or override, same as the crypto/US figures were.
DEFAULT_FOREX_ACCOUNT_BALANCE: float = DEFAULT_CRYPTO_ACCOUNT_BALANCE

#: Safe-to-commit configuration template. Only variables with a
#: confirmed env-var contract (Core.startup_validation) appear as live
#: (uncommented) lines. See module docstring re: Telegram.
CONFIG_TEMPLATE_CONTENT: str = """# AIOS configuration template (Activation 1.4)
# Safe to commit: placeholders only, no real credentials.
# Copy to `.env` and fill in real values locally -- `.env` itself is
# already listed in .gitignore and must stay that way.

ACTIVE_PROVIDER=gemini

GEMINI_API_KEY=
GEMINI_MODEL=

OLLAMA_HOST=
OLLAMA_MODEL=

# Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are read today only
# via ServiceContext.metadata (Services.notification_service), not
# through Core.config -- there is no confirmed environment-variable
# contract for them yet (see Core.doctor's own _check_telegram()
# docstring). Listed here, commented out, purely as a naming
# convention -- uncomment only once an official contract is decided.
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
"""


@dataclass
class BootstrapStepResult:
    """One completed bootstrap step, for reporting only.

    Attributes:
        step: Short machine-readable step name (matches the ``step``
            a ``BootstrapError`` would carry if this step had failed).
        status: ``"created"`` (new data written this run),
            ``"already_exists"`` (idempotent no-op), or ``"verified"``
            (read-only confirmation, e.g. the watchlist).
        detail: Human-readable extra context for the ``init`` report.
    """

    step: str
    status: str
    detail: str


def ensure_default_paper_account(account_repository: AccountRepository) -> tuple[Account, bool]:
    """Ensure the default paper account exists, without touching it if it does.

    Idempotency key: ``account_id`` (the table's own PRIMARY KEY) --
    looked up via the existing ``AccountRepository.get_by_id``, never a
    new UUID, never a fresh row on rerun.

    Args:
        account_repository: Existing repository instance to use.

    Returns:
        ``(account, created)`` -- ``account`` is the pre-existing row
        if one was found, or the freshly created one; ``created`` is
        ``True`` only if this call inserted it.

    Raises:
        RepositoryError: If the underlying statement fails (propagated
            unchanged -- ``run_bootstrap`` is what wraps this into a
            ``BootstrapError``, not this function).
    """
    existing = account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
    if existing is not None:
        return existing, False

    account = account_repository.create(
        account_id=DEFAULT_PAPER_ACCOUNT_ID,
        account_name=DEFAULT_PAPER_ACCOUNT_NAME,
        mode=DEFAULT_PAPER_ACCOUNT_MODE,
        currency=DEFAULT_PAPER_ACCOUNT_CURRENCY,
        asset_class=DEFAULT_PAPER_ACCOUNT_ASSET_CLASS,
        cash=DEFAULT_PAPER_ACCOUNT_BALANCE,
        equity=DEFAULT_PAPER_ACCOUNT_BALANCE,
        buying_power=DEFAULT_PAPER_ACCOUNT_BALANCE,
    )
    return account, True


def ensure_default_crypto_account(account_repository: AccountRepository) -> tuple[Account, bool]:
    """Ensure the default USD crypto paper account exists, without touching it if it does.

    Crypto prototype scope: creates exactly one additional account
    (``account_id="crypto-usd"``, ``mode="paper"``,
    ``asset_class="crypto"``, ``currency="USD"``) using the same
    ``AccountRepository`` and the same idempotent
    create-if-absent pattern as ``ensure_default_paper_account`` --
    no new repository method, no schema change, no FX conversion, no
    change to any trading/order/strategy code.

    Idempotency key: ``account_id`` (the table's own PRIMARY KEY) --
    looked up via the existing ``AccountRepository.get_by_id``, never
    a new UUID, never a fresh row on rerun.

    NOT called from ``run_bootstrap``/``python main.py init`` --
    deliberately kept a separate, explicitly-invoked step (same A2
    scope decision already applied to ``Database.migrations_accounts``
    itself: no composition-root changes, no automatic wiring). A
    caller invokes this function directly, e.g. from a one-off script
    or a REPL, until/unless it is explicitly promoted into the
    default bootstrap sequence.

    Args:
        account_repository: Existing repository instance to use.

    Returns:
        ``(account, created)`` -- ``account`` is the pre-existing row
        if one was found, or the freshly created one; ``created`` is
        ``True`` only if this call inserted it.

    Raises:
        RepositoryError: If the underlying statement fails (propagated
            unchanged, mirroring ``ensure_default_paper_account``).
    """
    existing = account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
    if existing is not None:
        return existing, False

    account = account_repository.create(
        account_id=DEFAULT_CRYPTO_ACCOUNT_ID,
        account_name=DEFAULT_CRYPTO_ACCOUNT_NAME,
        mode=DEFAULT_CRYPTO_ACCOUNT_MODE,
        currency=DEFAULT_CRYPTO_ACCOUNT_CURRENCY,
        asset_class=DEFAULT_CRYPTO_ACCOUNT_ASSET_CLASS,
        cash=DEFAULT_CRYPTO_ACCOUNT_BALANCE,
        equity=DEFAULT_CRYPTO_ACCOUNT_BALANCE,
        buying_power=DEFAULT_CRYPTO_ACCOUNT_BALANCE,
    )
    return account, True


def ensure_default_us_account(account_repository: AccountRepository) -> tuple[Account, bool]:
    """Ensure the default USD US-stocks paper account exists, without touching it if it does.

    Activation 9.1 scope: creates exactly one additional account
    (``account_id="us-usd"``, ``mode="paper"``, ``asset_class="stock_us"``,
    ``currency="USD"``) using the same ``AccountRepository`` and the
    same idempotent create-if-absent pattern as
    ``ensure_default_paper_account``/``ensure_default_crypto_account``
    -- no new repository method, no schema change, no FX conversion,
    no change to any trading/order/strategy code.

    Idempotency key: ``account_id`` (the table's own PRIMARY KEY) --
    looked up via the existing ``AccountRepository.get_by_id``, never
    a new UUID, never a fresh row on rerun.

    NOT called from ``run_bootstrap``/``python main.py init`` --
    deliberately kept a separate, explicitly-invoked step, mirroring
    ``ensure_default_crypto_account``'s own scope decision exactly
    (see that function's docstring for why).

    Args:
        account_repository: Existing repository instance to use.

    Returns:
        ``(account, created)`` -- ``account`` is the pre-existing row
        if one was found, or the freshly created one; ``created`` is
        ``True`` only if this call inserted it.

    Raises:
        RepositoryError: If the underlying statement fails (propagated
            unchanged, mirroring ``ensure_default_crypto_account``).
    """
    existing = account_repository.get_by_id(DEFAULT_US_ACCOUNT_ID)
    if existing is not None:
        return existing, False

    account = account_repository.create(
        account_id=DEFAULT_US_ACCOUNT_ID,
        account_name=DEFAULT_US_ACCOUNT_NAME,
        mode=DEFAULT_US_ACCOUNT_MODE,
        currency=DEFAULT_US_ACCOUNT_CURRENCY,
        asset_class=DEFAULT_US_ACCOUNT_ASSET_CLASS,
        cash=DEFAULT_US_ACCOUNT_BALANCE,
        equity=DEFAULT_US_ACCOUNT_BALANCE,
        buying_power=DEFAULT_US_ACCOUNT_BALANCE,
    )
    return account, True


def ensure_default_forex_account(account_repository: AccountRepository) -> tuple[Account, bool]:
    """Ensure the default USD Forex paper account exists, without touching it if it does.

    Activation 11.21 scope: creates exactly one additional account
    (``account_id="forex-usd"``, ``mode="paper"``, ``asset_class="forex"``,
    ``currency="USD"``) using the same ``AccountRepository`` and the
    same idempotent create-if-absent pattern as
    ``ensure_default_paper_account``/``ensure_default_crypto_account``/
    ``ensure_default_us_account`` -- no new repository method, no
    schema change, no FX conversion, no change to any trading/order/
    strategy code. ``currency="USD"`` matches Activation 11.1's LOCKED
    Decision A (the initial Forex paper account is USD-only).

    Idempotency key: ``account_id`` (the table's own PRIMARY KEY) --
    looked up via the existing ``AccountRepository.get_by_id``, never
    a new UUID, never a fresh row on rerun.

    NOT called from ``run_bootstrap``/``python main.py init`` --
    deliberately kept a separate, explicitly-invoked step, mirroring
    ``ensure_default_crypto_account``/``ensure_default_us_account``'s
    own scope decision exactly (see those functions' docstrings for
    why).

    This function creates the account row only -- it does not wire
    Forex paper BUY/SELL, ``--market forex`` routing, Forex analysis,
    or stop-loss CLI plumbing. Those remain separate, later atomic
    steps (Activation 11.20's audit identifies them explicitly).

    Args:
        account_repository: Existing repository instance to use.

    Returns:
        ``(account, created)`` -- ``account`` is the pre-existing row
        if one was found, or the freshly created one; ``created`` is
        ``True`` only if this call inserted it.

    Raises:
        RepositoryError: If the underlying statement fails (propagated
            unchanged, mirroring ``ensure_default_us_account``).
    """
    existing = account_repository.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
    if existing is not None:
        return existing, False

    account = account_repository.create(
        account_id=DEFAULT_FOREX_ACCOUNT_ID,
        account_name=DEFAULT_FOREX_ACCOUNT_NAME,
        mode=DEFAULT_FOREX_ACCOUNT_MODE,
        currency=DEFAULT_FOREX_ACCOUNT_CURRENCY,
        asset_class=DEFAULT_FOREX_ACCOUNT_ASSET_CLASS,
        cash=DEFAULT_FOREX_ACCOUNT_BALANCE,
        equity=DEFAULT_FOREX_ACCOUNT_BALANCE,
        buying_power=DEFAULT_FOREX_ACCOUNT_BALANCE,
    )
    return account, True


def ensure_watchlist_ready(watchlist_repository: WatchlistRepository) -> int:
    """Confirm the watchlist is readable, without writing anything.

    The ``watchlist`` table's migration is already part of the
    canonical registry ``run_init`` applies before this function ever
    runs, so a fresh watchlist already has zero rows -- this function
    never adds a ticker, placeholder, or header row (Section 7).

    Args:
        watchlist_repository: Existing repository instance to use.

    Returns:
        The current number of symbols on the watchlist (``0`` on a
        fresh environment; unchanged if the user already has symbols).

    Raises:
        RepositoryError: If the underlying statement fails.
    """
    return len(watchlist_repository.list_all())


def ensure_config_template(path: Path) -> bool:
    """Create ``path`` with ``CONFIG_TEMPLATE_CONTENT`` if absent.

    Never overwrites an existing file, even if its content has since
    been modified by the user (Section 8 / Scenario E) -- presence is
    the only check performed.

    Args:
        path: Where the template should live (e.g. ``<project
            root>/.env.example``).

    Returns:
        ``True`` if this call created the file, ``False`` if it
        already existed and was left untouched.

    Raises:
        OSError: If the parent directory cannot be created or the file
            cannot be written (e.g. permissions, path collides with an
            existing non-directory).
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE_CONTENT, encoding="utf-8")
    return True


def run_bootstrap(
    account_repository: AccountRepository,
    watchlist_repository: WatchlistRepository,
    config_template_path: Path,
) -> List[BootstrapStepResult]:
    """Run every Activation 1.4 bootstrap step, in the deterministic order
    from Section 4: default paper account, then watchlist, then config
    template.

    Each step's own exception (whatever type it naturally raises) is
    caught and re-raised as a single ``BootstrapError`` carrying that
    step's name, so ``Core.init_command.run_init`` can report exactly
    which step failed (Section 12) without needing to inspect exception
    types itself. A failure in one step does not attempt the later
    steps.

    Args:
        account_repository: Existing repository instance to use.
        watchlist_repository: Existing repository instance to use.
        config_template_path: Where the safe config template should
            live if it does not already exist.

    Returns:
        One ``BootstrapStepResult`` per completed step, in order.

    Raises:
        BootstrapError: If any step fails. ``.step`` names which one;
            ``.original`` is the underlying exception.
    """
    results: List[BootstrapStepResult] = []

    try:
        account, created = ensure_default_paper_account(account_repository)
    except Exception as exc:  # noqa: BLE001 -- wrapped below, not swallowed
        raise BootstrapError("default_paper_account", exc) from exc
    results.append(
        BootstrapStepResult(
            step="default_paper_account",
            status="created" if created else "already_exists",
            detail=(
                f"account_id={account.account_id!r} account_name={account.account_name!r} "
                f"currency={account.currency!r} cash={account.cash}"
            ),
        )
    )

    try:
        symbol_count = ensure_watchlist_ready(watchlist_repository)
    except Exception as exc:  # noqa: BLE001
        raise BootstrapError("watchlist", exc) from exc
    results.append(
        BootstrapStepResult(step="watchlist", status="verified", detail=f"symbols={symbol_count}")
    )

    try:
        config_created = ensure_config_template(config_template_path)
    except Exception as exc:  # noqa: BLE001
        raise BootstrapError("config_template", exc) from exc
    results.append(
        BootstrapStepResult(
            step="config_template",
            status="created" if config_created else "already_exists",
            detail=str(config_template_path),
        )
    )

    return results