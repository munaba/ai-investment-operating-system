from __future__ import annotations

from Core.approval import (
    AlwaysApproveApprovalPort,
    DenyAllApprovalPort,
    ToolBlacklistApprovalPort,
    ToolWhitelistApprovalPort,
)
from Core.config import config
from Core.exceptions import ConfigurationError
from Core.runtime import ApprovalPort

_DEFAULT_POLICY: str = "always_approve"

_ALWAYS_APPROVE: str = "always_approve"
_DENY_ALL: str = "deny_all"
_TOOL_WHITELIST: str = "tool_whitelist"
_TOOL_BLACKLIST: str = "tool_blacklist"

_KNOWN_POLICIES: frozenset[str] = frozenset(
    {_ALWAYS_APPROVE, _DENY_ALL, _TOOL_WHITELIST, _TOOL_BLACKLIST}
)


def _parse_tool_list(raw: str) -> list[str]:
    """Split a comma-separated env value into trimmed, non-empty tool names.

    Same tolerance as other comma-separated env values in this codebase:
    surrounding whitespace around each item is stripped, empty items
    (e.g. from a trailing comma) are dropped.
    """
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_approval_port() -> ApprovalPort:
    """Select and construct the ``ApprovalPort`` to use, from ``Core.config``.

    Mirrors ``Database/database_config.py::DatabaseConfig.from_env()``:
    reads env vars via the shared ``Core.config.config`` singleton,
    falls back to a documented default, and constructs one of the
    existing ``Core.approval`` implementations -- this module does not
    define any new ``ApprovalPort`` implementation itself (Stage 9.2 is
    LOCKED and already provides everything this stage selects from).

    Env vars read:
        APPROVAL_POLICY: one of ``"always_approve"`` (default),
            ``"deny_all"``, ``"tool_whitelist"``, ``"tool_blacklist"``.
            Case-insensitive, surrounding whitespace ignored.
        APPROVAL_TOOL_WHITELIST: comma-separated tool names. Required
            (non-empty after parsing) when ``APPROVAL_POLICY`` is
            ``"tool_whitelist"``; ignored otherwise.
        APPROVAL_TOOL_BLACKLIST: comma-separated tool names. Used when
            ``APPROVAL_POLICY`` is ``"tool_blacklist"``; an empty/unset
            value is valid there (equivalent in effect to
            ``always_approve``, via a different class). Ignored
            otherwise.

    ``PredicateApprovalPort`` is intentionally not selectable here --
    it takes a Python callable, which cannot be expressed as a plain
    env var without introducing a code-loading mechanism (import path,
    eval, plugin, reflection, ...). That is out of this stage's scope
    by deliberate design decision; ``PredicateApprovalPort`` remains
    usable only via direct construction in code.

    Returns:
        A constructed ``ApprovalPort`` instance.

    Raises:
        ConfigurationError: If ``APPROVAL_POLICY`` is not one of the
            known values, or if it is ``"tool_whitelist"`` but
            ``APPROVAL_TOOL_WHITELIST`` is missing/empty after parsing.
            Fail-fast: a misconfigured whitelist never silently becomes
            deny-all.
    """
    policy = config.get_str("APPROVAL_POLICY", _DEFAULT_POLICY).strip().lower()

    if policy == _ALWAYS_APPROVE:
        return AlwaysApproveApprovalPort()

    if policy == _DENY_ALL:
        return DenyAllApprovalPort()

    if policy == _TOOL_WHITELIST:
        raw = config.get_str("APPROVAL_TOOL_WHITELIST", "") or ""
        tools = _parse_tool_list(raw)
        if not tools:
            raise ConfigurationError(
                "APPROVAL_POLICY=tool_whitelist requires a non-empty "
                "APPROVAL_TOOL_WHITELIST (comma-separated tool names) -- "
                "an empty whitelist is refused rather than silently "
                "treated as deny-all.",
                details={"policy": policy, "APPROVAL_TOOL_WHITELIST": raw},
            )
        return ToolWhitelistApprovalPort(allowed_tools=tools)

    if policy == _TOOL_BLACKLIST:
        raw = config.get_str("APPROVAL_TOOL_BLACKLIST", "") or ""
        tools = _parse_tool_list(raw)
        return ToolBlacklistApprovalPort(blocked_tools=tools)

    raise ConfigurationError(
        f"Unknown APPROVAL_POLICY: {policy!r}. Known values: "
        f"{sorted(_KNOWN_POLICIES)}.",
        details={"policy": policy, "known_policies": sorted(_KNOWN_POLICIES)},
    )