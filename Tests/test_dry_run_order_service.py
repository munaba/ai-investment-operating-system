"""Standalone regression checks for
``Business.dry_run_order_service.DryRunOrderService``.

Covers Activation 8.2 (broker-agnostic dry-run flow):

* the pipeline order request -> validation -> estimated value -> fee
  -> risk -> approval -> dry-run result, using the exact reused
  components (``OrderLifecycleService._validate``, ``ExecutionPolicy``,
  ``RiskManagementService``, ``OrderValidationSkill``);
* a structurally invalid request short-circuits at the validation
  stage: every downstream field is ``None``/``"SKIPPED"``, and
  ``status == "REJECTED"``;
* a structurally valid BUY reaches ``approval_status == "APPROVED"``
  (the automatic recommendation) but, per Activation 8.3, still has
  ``would_submit is False`` until a human explicitly approves the
  same ``decision_key`` via ``HumanApprovalPort``;
* a structurally valid SELL reaches ``approval_status == "EXIT"`` and
  ``would_submit is False`` regardless of any human decision (only an
  automatic ``"APPROVED"`` recommendation *and* an explicit human
  approval together ever set ``would_submit``);
* fee/tax are sourced from the supplied ``ExecutionPolicy`` using the
  exact same by-action rule ``ExecutionService.execute_order`` uses
  (BUY -> ``buy_fee_rate``/no tax, SELL -> ``sell_fee_rate``/
  ``sell_tax_rate``);
* the risk stage is skipped (not failed) when risk parameters are
  omitted, computed when all four are supplied, and reported as
  failed (without raising, without failing the whole dry run) when
  ``RiskManagementService`` itself rejects them;
* ``broker_called``/``network_called``/``order_persisted`` are always
  ``False`` and ``dry_run`` is always ``True``, on every outcome;
* this module performs no I/O: no repository, no database file, no
  network socket is opened anywhere in this test.

Run directly with ``python Tests/test_dry_run_order_service.py`` --
no external test framework required, matching
``test_order_lifecycle_service.py``/``test_execution_service.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.dry_run_order_service import (  # noqa: E402
    RISK_STATUS_COMPUTED,
    RISK_STATUS_FAILED,
    RISK_STATUS_SKIPPED,
    DryRunOrderService,
)
from Business.execution_policy_config import ExecutionPolicy  # noqa: E402
from Business.order_lifecycle_service import (  # noqa: E402
    REASON_INVALID_ACTION,
    REASON_INVALID_PRICE,
    REASON_INVALID_QUANTITY,
    REASON_INVALID_SYMBOL,
)
from Core.human_approval_port import HumanApprovalPort  # noqa: E402

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


def _witness_flags_untouched(result) -> bool:
    return (
        result.broker_called is False
        and result.network_called is False
        and result.order_persisted is False
        and result.dry_run is True
    )


# ---------------------------------------------------------------------------
# Scenario 1: happy-path BUY reaches every stage and is APPROVED
# ---------------------------------------------------------------------------
def scenario_happy_path_buy_approved():
    print("\n[Scenario 1] happy-path BUY: full pipeline, APPROVED, would_submit")
    service = DryRunOrderService()
    result = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=100,
        requested_price=9000,
    )

    check(result.request["symbol"] == "BBCA", "request echoes the input unchanged")
    check(result.validation_status == "PASSED", "validation_status is PASSED")
    check(result.estimated_value == 900000.0, "estimated_value == quantity * requested_price")
    check(result.fee == 0.0 and result.tax == 0.0, "default ExecutionPolicy fee/tax are 0.0")
    check(result.estimated_net_amount == 900000.0, "estimated_net_amount == value + fee + tax for BUY")
    check(result.risk_status == RISK_STATUS_SKIPPED, "risk stage skipped: no risk params supplied")
    check(result.risk is None, "risk payload is None when skipped")
    check(result.approval_status == "APPROVED", "approval_status APPROVED for BUY with positive capital")
    check(result.approval_reason == "ready for execution", "approval_reason matches OrderValidationSkill Rule 1")
    check(result.status == "APPROVED", "overall status mirrors the automatic approval_status when validation passed")
    check(
        result.human_approval_status == "PENDING",
        "Activation 8.3: human_approval_status is PENDING by default (no human has decided)",
    )
    check(
        result.would_submit is False,
        "Activation 8.3: would_submit False on an automatic APPROVED alone -- human approval is also required",
    )
    check(_witness_flags_untouched(result), "broker/network/persist witness flags correct, dry_run True")


# ---------------------------------------------------------------------------
# Scenario 2: happy-path SELL reaches EXIT, never would_submit
# ---------------------------------------------------------------------------
def scenario_happy_path_sell_exit():
    print("\n[Scenario 2] happy-path SELL: approval EXIT, would_submit False")
    service = DryRunOrderService()
    result = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="SELL",
        quantity=50,
        requested_price=9500,
    )

    check(result.validation_status == "PASSED", "validation passes for a well-formed SELL")
    check(result.approval_status == "EXIT", "approval_status EXIT for SELL (OrderValidationSkill Rule 3)")
    check(result.status == "EXIT", "overall status mirrors approval_status")
    check(result.would_submit is False, "would_submit False for EXIT (only APPROVED sets it True)")
    check(_witness_flags_untouched(result), "witness flags correct for SELL too")


# ---------------------------------------------------------------------------
# Scenario 3: structural rejection short-circuits the whole pipeline
# ---------------------------------------------------------------------------
def scenario_structural_rejection_short_circuits():
    print("\n[Scenario 3] structural validation failure short-circuits downstream stages")
    service = DryRunOrderService()
    cases = [
        (dict(symbol="", action="BUY", quantity=10, requested_price=100), REASON_INVALID_SYMBOL),
        (dict(symbol="BBCA", action="HOLD", quantity=10, requested_price=100), REASON_INVALID_ACTION),
        (dict(symbol="BBCA", action="BUY", quantity=-10, requested_price=100), REASON_INVALID_QUANTITY),
        (dict(symbol="BBCA", action="BUY", quantity=10, requested_price=0), REASON_INVALID_PRICE),
    ]
    for kwargs, expected_reason in cases:
        result = service.dry_run(account_id="acc-1", **kwargs)
        check(
            result.validation_status == "REJECTED" and result.validation_reason == expected_reason,
            f"validation REJECTED with reason={expected_reason!r} for {kwargs}",
        )
        check(
            result.estimated_value is None
            and result.fee is None
            and result.tax is None
            and result.estimated_net_amount is None,
            "estimated value / fee / tax are all None after a validation rejection",
        )
        check(result.risk_status == RISK_STATUS_SKIPPED and result.risk is None, "risk stage skipped after rejection")
        check(result.approval_status is None, "approval stage never runs after a validation rejection")
        check(
            result.human_approval_status == "SKIPPED"
            and result.human_approval_reviewer is None
            and result.human_approval_note is None,
            "human approval gate never runs after a validation rejection",
        )
        check(result.status == "REJECTED", "overall status is REJECTED")
        check(result.would_submit is False, "would_submit False on rejection")
        check(_witness_flags_untouched(result), "witness flags still correct on the rejection path")


# ---------------------------------------------------------------------------
# Scenario 4: fee/tax are read from the supplied ExecutionPolicy,
# using the same by-action rule as ExecutionService.execute_order.
# ---------------------------------------------------------------------------
def scenario_fee_tax_sourced_from_execution_policy():
    print("\n[Scenario 4] fee/tax sourced from ExecutionPolicy, by action")
    policy = ExecutionPolicy(buy_fee_rate=1500.0, sell_fee_rate=2000.0, sell_tax_rate=500.0)
    service = DryRunOrderService(execution_policy=policy)

    buy_result = service.dry_run(account_id="acc-1", symbol="BBCA", action="BUY", quantity=10, requested_price=1000)
    check(buy_result.fee == 1500.0, "BUY fee == policy.buy_fee_rate")
    check(buy_result.tax == 0.0, "BUY tax is always 0.0 (no BUY tax leg on IDX)")
    check(
        buy_result.estimated_net_amount == buy_result.estimated_value + 1500.0,
        "BUY estimated_net_amount == estimated_value + fee",
    )

    sell_result = service.dry_run(account_id="acc-1", symbol="BBCA", action="SELL", quantity=10, requested_price=1000)
    check(sell_result.fee == 2000.0, "SELL fee == policy.sell_fee_rate")
    check(sell_result.tax == 500.0, "SELL tax == policy.sell_tax_rate")
    check(
        sell_result.estimated_net_amount == sell_result.estimated_value - 2000.0 - 500.0,
        "SELL estimated_net_amount == estimated_value - fee - tax",
    )


# ---------------------------------------------------------------------------
# Scenario 5: risk stage -- skipped / computed / failed
# ---------------------------------------------------------------------------
def scenario_risk_stage_skipped_computed_failed():
    print("\n[Scenario 5] risk stage: skipped, computed, and failed paths")
    service = DryRunOrderService()

    skipped = service.dry_run(account_id="acc-1", symbol="BBCA", action="BUY", quantity=10, requested_price=1000)
    check(skipped.risk_status == RISK_STATUS_SKIPPED, "risk skipped when no risk params supplied at all")

    partial = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        stop_loss_percent=2,
        take_profit_percent=4,
        # risk_per_trade_percent and account_balance omitted
    )
    check(partial.risk_status == RISK_STATUS_SKIPPED, "risk skipped when only some risk params are supplied")

    computed = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        stop_loss_percent=2,
        take_profit_percent=4,
        risk_per_trade_percent=1,
        account_balance=10_000_000,
    )
    check(computed.risk_status == RISK_STATUS_COMPUTED, "risk computed when all four params are supplied")
    check(
        isinstance(computed.risk, dict)
        and {
            "stop_loss_price",
            "take_profit_price",
            "risk_amount",
            "position_size",
            "risk_reward_ratio",
        }
        <= computed.risk.keys(),
        "computed risk payload has RiskManagementService's five fields",
    )
    check(computed.risk["stop_loss_price"] == 980.0, "stop_loss_price matches RiskManagementService's own formula")

    failed = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        stop_loss_percent=-2,  # invalid: RiskManagementService requires > 0
        take_profit_percent=4,
        risk_per_trade_percent=1,
        account_balance=10_000_000,
    )
    check(failed.risk_status == RISK_STATUS_FAILED, "risk stage reports FAILED, not an exception, on bad risk input")
    check(
        isinstance(failed.risk, dict) and "error" in failed.risk,
        "FAILED risk payload carries RiskManagementService's own failure message",
    )
    check(failed.validation_status == "PASSED", "a risk failure does not affect structural validation")
    check(failed.approval_status is not None, "a risk failure does not block the later approval stage")


# ---------------------------------------------------------------------------
# Scenario 5b (Activation 8.3): human approval gate -- pending by
# default, approved/denied only after an explicit human decision,
# immutable once recorded, and skipped after a structural rejection.
# ---------------------------------------------------------------------------
def scenario_human_approval_gate_pending_by_default():
    print("\n[Scenario 5b.1] human approval gate is PENDING by default")
    service = DryRunOrderService()
    result = service.dry_run(account_id="acc-1", symbol="BBCA", action="BUY", quantity=10, requested_price=1000)
    check(result.human_approval_status == "PENDING", "PENDING when no human has ever recorded a decision")
    check(
        result.human_approval_reviewer is None and result.human_approval_note is None,
        "no reviewer/note reported while PENDING",
    )
    check(result.would_submit is False, "would_submit False while PENDING, even with an APPROVED recommendation")


def scenario_human_approval_gate_approved_unlocks_would_submit():
    print("\n[Scenario 5b.2] an explicit human APPROVE unlocks would_submit")
    service = DryRunOrderService()
    service.human_approval_port.record_decision("order-42", approved=True, reviewer="alice", note="looks good")

    result = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        request_id="order-42",
    )
    check(result.human_approval_status == "APPROVED", "human_approval_status reflects the recorded decision")
    check(result.human_approval_reviewer == "alice", "reviewer identity is reported back")
    check(result.human_approval_note == "looks good", "note is reported back")
    check(
        result.would_submit is True,
        "would_submit True only once BOTH automatic APPROVED and human APPROVED are present",
    )


def scenario_human_approval_gate_denied_blocks_would_submit():
    print("\n[Scenario 5b.3] an explicit human DENY blocks would_submit")
    service = DryRunOrderService()
    service.human_approval_port.record_decision("order-99", approved=False, reviewer="bob", note="too risky")

    result = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        request_id="order-99",
    )
    check(result.human_approval_status == "DENIED", "human_approval_status DENIED after an explicit deny")
    check(result.would_submit is False, "would_submit False after an explicit human deny")
    check(result.approval_status == "APPROVED", "the automatic recommendation is unaffected by the human decision")


def scenario_human_decisions_are_immutable_and_isolated_by_key():
    print("\n[Scenario 5b.4] human decisions are immutable, and isolated per decision_key")
    service = DryRunOrderService()
    service.human_approval_port.record_decision("dup-key", approved=True)

    raised = False
    try:
        service.human_approval_port.record_decision("dup-key", approved=False)
    except ValueError:
        raised = True
    check(raised, "recording a second decision for the same key raises ValueError")
    check(
        service.human_approval_port.get_decision("dup-key").approved is True,
        "the original decision is untouched after the rejected second attempt",
    )

    other = service.dry_run(
        account_id="acc-1",
        symbol="BBCA",
        action="BUY",
        quantity=10,
        requested_price=1000,
        request_id="a-completely-different-key",
    )
    check(other.human_approval_status == "PENDING", "an unrelated decision_key is unaffected -- still PENDING")


def scenario_human_approval_port_reusable_standalone():
    print("\n[Scenario 5b.5] HumanApprovalPort is usable standalone, not just via DryRunOrderService")
    port = HumanApprovalPort()
    check(port.check("never-seen").value == "PENDING", "an unknown key is PENDING, never raises")
    check(port.get_decision("never-seen") is None, "get_decision returns None for an unknown key")

    port.record_decision("k1", approved=True)
    check(port.check("k1").value == "APPROVED", "check() reflects an approved decision")

    port2 = HumanApprovalPort()
    check(port2.check("k1").value == "PENDING", "a second, independent HumanApprovalPort shares no state")

    raised = False
    try:
        port.record_decision("   ", approved=True)
    except ValueError:
        raised = True
    check(raised, "a blank decision_key is rejected with ValueError")


# ---------------------------------------------------------------------------
# Scenario 6: no I/O -- default construction touches no repository,
# no database, no network.
# ---------------------------------------------------------------------------
def scenario_no_io_dependencies():
    print("\n[Scenario 6] DryRunOrderService opens no repository/database/network")
    service = DryRunOrderService()
    attrs = vars(service)
    check(
        set(attrs.keys())
        == {"_execution_policy", "_order_validation_skill", "_risk_management_service", "_human_approval_port"},
        "DryRunOrderService holds exactly its four reused, in-memory collaborators",
    )
    for name, value in attrs.items():
        check(
            not hasattr(value, "_connection") and not hasattr(value, "conn"),
            f"{name} exposes no live DB connection attribute",
        )


# ---------------------------------------------------------------------------
# Scenario 7: repeated calls are deterministic (pure function of input)
# ---------------------------------------------------------------------------
def scenario_deterministic():
    print("\n[Scenario 7] repeated dry_run() calls with identical input are deterministic")
    service = DryRunOrderService()
    kwargs = dict(account_id="acc-1", symbol="BBCA", action="BUY", quantity=100, requested_price=9000)
    first = service.dry_run(**kwargs)
    second = service.dry_run(**kwargs)
    check(first == second, "two calls with the same input produce field-equal DryRunResults")


def main() -> int:
    scenario_happy_path_buy_approved()
    scenario_happy_path_sell_exit()
    scenario_structural_rejection_short_circuits()
    scenario_fee_tax_sourced_from_execution_policy()
    scenario_risk_stage_skipped_computed_failed()
    scenario_human_approval_gate_pending_by_default()
    scenario_human_approval_gate_approved_unlocks_would_submit()
    scenario_human_approval_gate_denied_blocks_would_submit()
    scenario_human_decisions_are_immutable_and_isolated_by_key()
    scenario_human_approval_port_reusable_standalone()
    scenario_no_io_dependencies()
    scenario_deterministic()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 8.2/8.3 DRY-RUN SERVICE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())