"""
Activation 12.11 — Immutable Execution Request Contract.

This module defines ONLY:

1. frozen ExecutionRequest dataclass
2. normalize_execution_request(**raw_fields) -> ExecutionRequest
3. fingerprint(request: ExecutionRequest) -> str

No wiring to PermissionContext, PermissionedTool, HumanApprovalPort,
PaperExecutionTool, the Composition Root, or main.py is performed here.
"""

from dataclasses import dataclass
from typing import Optional
import hashlib
import json


@dataclass(frozen=True)
class ExecutionRequest:
    account_id: str
    symbol: str
    action: str
    quantity: float
    requested_price: float
    executed_at: str
    stop_loss: Optional[float]
    signal_evidence: object


def normalize_execution_request(**raw_fields) -> ExecutionRequest:
    account_id = raw_fields["account_id"]
    symbol = raw_fields["symbol"]
    action = raw_fields["action"]
    quantity = raw_fields["quantity"]
    requested_price = raw_fields["requested_price"]
    executed_at = raw_fields["executed_at"]
    stop_loss = raw_fields["stop_loss"]
    signal_evidence = raw_fields["signal_evidence"]

    if signal_evidence is None:
        raise ValueError("signal_evidence must be present and must not be None")

    normalized_stop_loss = None if stop_loss is None else float(stop_loss)

    return ExecutionRequest(
        account_id=str(account_id).strip(),
        symbol=str(symbol).strip().upper(),
        action=str(action).strip().upper(),
        quantity=float(quantity),
        requested_price=float(requested_price),
        executed_at=str(executed_at).strip(),
        stop_loss=normalized_stop_loss,
        signal_evidence=signal_evidence,
    )


def fingerprint(request: ExecutionRequest) -> str:
    fields = {
        "account_id": request.account_id,
        "symbol": request.symbol,
        "action": request.action,
        "quantity": request.quantity,
        "requested_price": request.requested_price,
        "executed_at": request.executed_at,
        "stop_loss": request.stop_loss,
        "signal_evidence": getattr(request.signal_evidence, "snapshot_id", None),
    }

    canonical_json = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()