"""Standalone regression checks for
``Core.human_approval_port.HumanApprovalPort``.

Covers Activation 8.3 ("HUMAN APPROVAL ONLY") in isolation from
``Business.dry_run_order_service.DryRunOrderService`` (see
``Tests/test_dry_run_order_service.py`` for the integrated scenarios):

* an unknown/undecided ``decision_key`` is always ``PENDING``, never
  raises;
* ``record_decision()`` makes ``check()`` reflect that exact decision;
* decisions are immutable -- a second ``record_decision()`` call for
  the same key raises ``ValueError`` and leaves the original decision
  untouched;
* a blank/empty ``decision_key`` is rejected;
* ``get_decision()`` returns the full ``HumanDecision`` (reviewer/note
  included) or ``None``;
* two independent ``HumanApprovalPort`` instances share no state;
* ``check()`` returns ``Core.runtime.ApprovalOutcome`` members
  (reused, not a locally reinvented enum) -- ``PENDING``/``APPROVED``/
  ``DENIED`` only, nothing else;
* this module performs no I/O of any kind: no database, no network,
  no broker, no ``Core.event.Event``/``Core.runtime.ApprovalPort``
  coupling.

Run directly with ``python Tests/test_human_approval_port.py`` -- no
external test framework required, matching
``test_dry_run_order_service.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.human_approval_port import ApprovalOutcome, HumanApprovalPort, HumanDecision  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def scenario_unknown_key_is_pending():
    print("\n[Scenario 1] an unknown decision_key is PENDING, never raises")
    port = HumanApprovalPort()
    check(port.check("nonexistent") == ApprovalOutcome.PENDING, "check() returns ApprovalOutcome.PENDING")
    check(port.get_decision("nonexistent") is None, "get_decision() returns None")


def scenario_record_and_check_approve():
    print("\n[Scenario 2] record_decision(approved=True) -> check() APPROVED")
    port = HumanApprovalPort()
    decision = port.record_decision("order-1", approved=True, reviewer="alice", note="ok")
    check(isinstance(decision, HumanDecision), "record_decision returns a HumanDecision")
    check(port.check("order-1") == ApprovalOutcome.APPROVED, "check() reflects APPROVED")
    stored = port.get_decision("order-1")
    check(stored is not None and stored.approved is True, "get_decision().approved is True")
    check(stored.reviewer == "alice" and stored.note == "ok", "reviewer/note preserved verbatim")


def scenario_record_and_check_deny():
    print("\n[Scenario 3] record_decision(approved=False) -> check() DENIED")
    port = HumanApprovalPort()
    port.record_decision("order-2", approved=False, reviewer="bob", note="too risky")
    check(port.check("order-2") == ApprovalOutcome.DENIED, "check() reflects DENIED")
    check(port.get_decision("order-2").approved is False, "get_decision().approved is False")


def scenario_decisions_are_immutable():
    print("\n[Scenario 4] a decision, once recorded, cannot be overwritten")
    port = HumanApprovalPort()
    port.record_decision("order-3", approved=True)

    raised = False
    try:
        port.record_decision("order-3", approved=False)
    except ValueError:
        raised = True
    check(raised, "a second record_decision() for the same key raises ValueError")
    check(port.check("order-3") == ApprovalOutcome.APPROVED, "the original decision is unchanged after the attempt")


def scenario_blank_decision_key_rejected():
    print("\n[Scenario 5] a blank/empty decision_key is rejected")
    port = HumanApprovalPort()
    for bad_key in ("", "   ", None):
        raised = False
        try:
            port.record_decision(bad_key, approved=True)  # type: ignore[arg-type]
        except ValueError:
            raised = True
        check(raised, f"record_decision({bad_key!r}, ...) raises ValueError")


def scenario_independent_instances_share_no_state():
    print("\n[Scenario 6] two HumanApprovalPort instances are fully independent")
    port_a = HumanApprovalPort()
    port_b = HumanApprovalPort()
    port_a.record_decision("shared-looking-key", approved=True)
    check(port_a.check("shared-looking-key") == ApprovalOutcome.APPROVED, "port_a sees its own decision")
    check(port_b.check("shared-looking-key") == ApprovalOutcome.PENDING, "port_b is unaffected -- still PENDING")


def scenario_only_three_outcomes_ever_possible():
    print("\n[Scenario 7] check() only ever returns PENDING/APPROVED/DENIED")
    port = HumanApprovalPort()
    port.record_decision("k-approve", approved=True)
    port.record_decision("k-deny", approved=False)
    outcomes = {port.check("k-unknown"), port.check("k-approve"), port.check("k-deny")}
    check(
        outcomes == {ApprovalOutcome.PENDING, ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED},
        "exactly the three ApprovalOutcome members appear, reused from Core.runtime -- no new enum invented",
    )


def scenario_no_io_no_runtime_coupling():
    print("\n[Scenario 8] HumanApprovalPort is pure in-memory, no Event/ApprovalPort coupling")
    port = HumanApprovalPort()
    attrs = vars(port)
    check(set(attrs.keys()) == {"_decisions"}, "HumanApprovalPort holds exactly one collaborator: _decisions")
    check(isinstance(attrs["_decisions"], dict), "_decisions is a plain in-memory dict, not a repository/store")
    check(not hasattr(port, "check_event") and not hasattr(port, "event"), "no Core.event.Event-shaped API exists")


def main() -> int:
    scenario_unknown_key_is_pending()
    scenario_record_and_check_approve()
    scenario_record_and_check_deny()
    scenario_decisions_are_immutable()
    scenario_blank_decision_key_rejected()
    scenario_independent_instances_share_no_state()
    scenario_only_three_outcomes_ever_possible()
    scenario_no_io_no_runtime_coupling()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 8.3 HUMAN APPROVAL PORT TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())