from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.tool_permission import ToolPermission, ToolPermissionError


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    permissions = tuple(ToolPermission)
    check(
        permissions
        == (
            ToolPermission.READ_ONLY,
            ToolPermission.PAPER_EXECUTION,
            ToolPermission.LIVE_EXECUTION,
            ToolPermission.DESTRUCTIVE_ADMIN,
        ),
        "canonical four permission categories exist",
    )

    for permission in ToolPermission:
        check(
            ToolPermission.from_value(permission.value) is permission,
            f"normalize {permission.value}",
        )

    check(
        ToolPermission.from_value(" READ-ONLY ") is ToolPermission.READ_ONLY,
        "permission normalization handles whitespace/case",
    )

    for value in ("unknown", "paper", "live", "admin"):
        try:
            ToolPermission.from_value(value)
        except ToolPermissionError:
            pass
        else:
            raise AssertionError(f"invalid permission {value!r} was accepted")

    try:
        ToolPermission.from_value(None)  # type: ignore[arg-type]
    except ToolPermissionError:
        pass
    else:
        raise AssertionError("non-string permission was accepted")

    # Explicitly prove this layer has no execution semantics.
    check(
        not hasattr(ToolPermission, "execute")
        and not hasattr(ToolPermission, "authorize"),
        "permission vocabulary cannot execute or authorize a tool",
    )

    print("ACTIVATION 12.1 TOOL PERMISSION MODEL: PASS")
    print("TOTAL: 9 PASS / 0 FAIL")


if __name__ == "__main__":
    main()
