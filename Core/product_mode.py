from __future__ import annotations

"""Phase A -- explicit product mode for AIOS.

This module answers one question: "what product mode is AIOS running
in, and what does that mode allow?" Phase A introduces exactly one
mode, ``decision_copilot`` -- a personal IDX decision-support and
paper-trading agent with broker/live execution structurally disabled.

Source-of-truth audit behind this module (Phase A, read-only):

  * No broker adapter exists anywhere in this repository (grep audit:
    no ``Broker*`` class, no live order-submission client, no
    live-execution HTTP/API call). Activation 8 ("Small-Capital Live
    IDX"), which the roadmap describes as the step that would
    introduce a broker adapter, has not been built.
  * ``main.py`` has no ``live`` (or similar) CLI dispatch branch --
    only ``doctor``/``init``/``init-us``/``init-forex``/``backup``/
    ``watchlist``/``preference``/``strategy-note``/
    ``previous-decision``/``lesson``/``scan``/``recommendation``/
    ``paper``/``portfolio``/``account``/``orders``/``trades``/
    ``report``/``scheduler``.
  * ``Orchestration.permission_context.PermissionContext`` already
    defaults ``live_execution_allowed=False`` (fail-closed), and
    ``Core.composition_root`` constructs exactly one
    ``PermissionContext()`` with no override anywhere in source --
    every ``ToolPermission.LIVE_EXECUTION``-tagged tool the agent tool
    path could ever call is therefore already denied.
  * ``init``/``doctor``/every ``run_*_migrations.py`` script and
    ``Core.bootstrap.run_bootstrap`` require no broker credential or
    broker connectivity of any kind (audited: no ``BROKER_*`` name
    appears in ``Core.config``/``Core.startup_validation``/
    ``Core.init_command``).

Phase A does not add a broker kill-switch that does not otherwise
exist -- it makes the *absence* of live execution an explicit,
verifiable product-mode contract instead of an implicit accident of
"Activation 8 hasn't shipped yet", and gives ``doctor`` a stable place
to report it. If a future Activation ever introduces a live-execution
path, that path must consult this module (or the ``PermissionContext``
it is built to align with) before running -- this module's job is to
make such an addition visibly a Phase-B/Activation-8 decision, never a
silent one.

Scope boundary (LOCKED for Phase A): exactly one recognized mode,
read from one env var, with no persistence, no CLI flag to change it
mid-run, and no broker-specific knowledge of any kind.
"""

import os
from dataclasses import dataclass

#: The only product mode Phase A recognizes. Deliberately not an enum
#: with multiple members -- Phase A adds no second mode. A future
#: Activation/Phase may introduce one (e.g. a live-capable mode), at
#: which point this module -- not any ad hoc check elsewhere -- is
#: where that second mode would be declared.
DECISION_COPILOT = "decision_copilot"

#: Env var used to select the product mode. Not read anywhere before
#: this module -- introduced fresh by Phase A.
_ENV_VAR = "AIOS_PRODUCT_MODE"

#: Every mode this build of AIOS recognizes. Exactly one entry in
#: Phase A.
_KNOWN_MODES = (DECISION_COPILOT,)


@dataclass(frozen=True)
class ProductModeStatus:
    """The resolved product mode plus what it implies, for diagnostics.

    Attributes:
        mode: The raw value read from ``AIOS_PRODUCT_MODE`` (or the
            ``decision_copilot`` default if unset).
        recognized: Whether ``mode`` is one Phase A knows about. An
            unrecognized value is a configuration error -- Phase A
            must never silently fall back to treating an unknown mode
            as safe.
        live_execution_disabled: Whether this mode disables broker/
            live order execution. Always ``True`` for
            ``decision_copilot`` (Phase A defines no mode where this
            is ``False``).
        broker_credentials_required: Whether this mode requires any
            broker credential/connectivity to start. Always ``False``
            for ``decision_copilot``.
    """

    mode: str
    recognized: bool
    live_execution_disabled: bool
    broker_credentials_required: bool


def active_product_mode_name() -> str:
    """Return the raw ``AIOS_PRODUCT_MODE`` value, defaulting to
    ``decision_copilot`` when unset. Does not validate -- see
    :func:`resolve_product_mode` for the validated form doctor uses.
    """
    return os.environ.get(_ENV_VAR, DECISION_COPILOT)


def resolve_product_mode() -> ProductModeStatus:
    """Resolve the active product mode into a :class:`ProductModeStatus`.

    Never raises: an unrecognized mode is reported via
    ``recognized=False`` (and, conservatively, both capability flags
    are reported as the *safest* values -- live execution treated as
    disabled, broker credentials treated as required-unknown/True --
    rather than the code guessing what an unrecognized mode intends).
    """
    mode = active_product_mode_name()
    if mode not in _KNOWN_MODES:
        return ProductModeStatus(
            mode=mode,
            recognized=False,
            live_execution_disabled=True,
            broker_credentials_required=True,
        )
    # Phase A: the one recognized mode, decision_copilot, always
    # disables live execution and never requires broker credentials.
    return ProductModeStatus(
        mode=mode,
        recognized=True,
        live_execution_disabled=True,
        broker_credentials_required=False,
    )
