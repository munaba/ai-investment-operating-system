
ACTIVATION 11.18 — FOREX MARGIN SEMANTICS DECISION

Status

DECISION LOCKED

Roadmap Basis

# ACTIVATION 11 — FOREX

## Activation awal

* analysis;
* paper forex;
* no leverage live;
* no autonomous execution.

## Acceptance Gate

Margin, pip value, stop-loss, dan maximum loss harus terbukti benar
melalui test numerik dan reconciliation.

The roadmap requires margin to be proven correct — it does not require a
broker-grade margin ledger, used_margin, free_margin, maintenance margin,
margin calls, or liquidation. Those are explicitly not being invented here.

Problem

Activation 11.17's audit proved, with exact Decimal arithmetic against the
actual source, that Decision 11.1 Section I's reconciliation invariant —
required_margin <= Account.cash at any point in the trade history — is
mathematically incompatible with the two other LOCKED formulas it depends on:

Business/forex_margin_policy.py: required_margin = price * quantity
(Decision B, 1:1).

Business/account_balance_service.py: apply_trade() is asset-class-blind
and direction-blind — BUY -> cash -= gross_value + fee + tax,
SELL -> cash += gross_value - fee - tax. It has no parameter and no
collaborator that could tell it Position.direction, or whether a given
SELL is a reducing sale of owned inventory versus the opening of new SHORT
exposure (confirmed by direct inspection: its only repository dependency
is AccountRepository, and its docstring lists Position as explicitly
DILARANG to touch).

Algebraically: opening a LONG debits cash -= margin, so
cash_after = cash_before - margin. The invariant margin <= cash_after
therefore reduces to margin <= cash_before / 2 — any LONG sized over half
of starting cash violates the LOCKED invariant by construction. For SHORT,
the generic SELL credit (cash += gross_value) inflates cash by proceeds
from currency the account does not own, so the invariant numerically
"passes" but for the wrong reason: that inflated cash is fully spendable by
an unrelated later trade while the SHORT is still open.

Business/paper_trading_engine.py's Forex margin gate (Activation 11.15)
confirms the actual live behavior: it computes required_margin for a
trade's incremental new exposure only, checks it once against
account.cash at that instant (if account.cash < float(required_margin):
raise), and does nothing further — no debit of a reserved amount, no
persisted margin state. Business/reconciliation_engine.py's
_check_forex_state (Activation 11.16) confirms the gap independently: it
recomputes calculate_required_margin from persisted Position state and
checks only that the computation does not raise (reconstructability), never
that it is <= Account.cash. The Decision 11.1 Section I adequacy invariant
has no implementation anywhere in the codebase.

Database/models.py's Account dataclass has exactly cash: float,
equity: float, buying_power: float — no used_margin, reserved_margin,
or free_margin field exists. buying_power is read and passed through
unchanged by AccountBalanceService.apply_trade(), and is documented inline
as "margin/leverage, reserved for a future STEP" — it is never computed or
written to by any Forex code today.

Model A — Affordability Only

required_margin = price * quantity is a one-time pre-trade check: "can
this account currently afford to open this exposure." Account.cash
retains its single existing meaning — the generic transaction cash balance
used identically by IDX/US/Crypto. No amount is reserved after the check
passes; the trade's actual cash effect is whatever the generic BUY/SELL
formula already produces.

This is exactly the model the current code already implements — gate,
formula, and cash semantics all already match Model A verbatim. Selecting it
requires no new code, no new field, and no behavior change; the audit's own
LONG/SHORT traces are Model A's real, current output.

Under Model A, required_margin <= Account.cash is true only at the
instant the gate runs, before the trade's cash effect is applied. It is not
a claim about any later point in the trade's lifetime. The Decision 11.1
Section I sentence, as literally worded ("does not exceed Account.cash at
any point in the trade history"), is not a true statement about this
architecture and cannot be made true without adding reservation semantics
that do not exist (see Model B). Under Model A, short-opening proceeds being
immediately spendable is a direct, accepted consequence of "cash" meaning
"generic transaction balance" rather than "collateral pool" — the same way a
short sale of a stock the account does not own is not representable at all
under the same generic formula, and Forex SHORT was deliberately layered
onto it without a separate cash treatment.

Model B — Reserved Collateral

required_margin represents actual reserved collateral: cash committed to
back open exposure, unavailable for any other trade until that exposure is
reduced or closed. This requires distinguishing, at minimum, total cash
from reserved margin from available cash (available = total - reserved),
and querying that state on every gate check, not just at the moment of
opening.

None of that state exists today. buying_power is a candidate field but is
explicitly reserved and untouched by every Forex module inspected
(account_balance_service.py, paper_trading_engine.py,
reconciliation_engine.py) — repurposing it would still require: (1) a
margin lifecycle (reserve on open, partially release on reduce, fully
release on close) that AccountBalanceService cannot implement without
gaining Position.direction/Position.quantity visibility it is currently,
deliberately, forbidden from having (DILARANG ... touching Position); (2)
PaperTradingEngine's gate changing from a point-in-time affordability read
into a persisted-state read/write; (3) ReconciliationEngine gaining a real
invariant to check instead of reconstructability-only. This is a genuine
architectural change, not a formula change — none of it is implemented by
this decision.

Decision

MODEL A.

Exact Meaning of Account.cash

Unchanged from every other market. Account.cash is the single generic
transaction cash balance, debited/credited by
AccountBalanceService.apply_trade()'s existing asset-class-blind
BUY/SELL formula. It does not represent, and is not being redefined to
represent, reserved collateral for Forex. This is a confirmation of current
behavior, not a new decision about cash itself.

Exact Meaning of Required Margin

required_margin = price * quantity (Decision 11.1 B, unchanged) is a
pre-trade affordability snapshot: "does the account currently hold
enough cash to open this incremental new exposure." It is evaluated once,
at the gate in PaperTradingEngine, against Account.cash at that instant.
It is not persisted, not reserved, and not re-checked at any later point in
the position's lifetime. This is the accurate description of what
Business/forex_margin_policy.calculate_required_margin combined with the
Activation 11.15 gate already does — this decision names it, it does not
change it.

Reconciliation Invariant

Decision 11.1 Section I's sentence "Margin required ... does not exceed
Account.cash at any point in the trade history" is rewritten, since as
literally worded it describes reservation behavior this architecture does
not have and Model A does not add. It is replaced by:

For every Forex trade that adds new exposure, the required margin for
that trade's incremental new-exposure quantity, computed against the
trade's execution price, did not exceed Account.cash at the moment the
trade was accepted (i.e., the pre-trade gate's own check held at
accept-time). This is a point-in-time affordability fact about
trade acceptance, not a standing property of the account's current
state, and is not re-derivable from a closed/settled position's final
Position/Account rows alone — only from the trade-history record of
what Account.cash was immediately before that specific trade.

The remaining Decision 11.1 Section I invariants (Order/Trade/Position cash
replay, pip-value reconstructability, maximum-loss reconstructability,
stop-loss immutability) are unaffected and remain as written.

ReconciliationEngine._check_forex_state's current reconstructability-only
check (Activation 11.16 — "does the formula compute without raising")
remains correct and sufficient under the rewritten invariant above: it was
never expected to prove a standing collateral-adequacy property, because
Model A has no such property to prove. No change to
reconciliation_engine.py is required or made by this decision.

SHORT Cash Semantics

Unchanged, and explicitly accepted as correct under Model A: opening a
SHORT credits cash += gross_value via the generic SELL formula, exactly
as it does today. The resulting cash is ordinary, spendable Account.cash
— including by a later, unrelated trade — because Model A does not treat
any portion of cash as reserved. This is a known, accepted characteristic
of the paper model, not a defect requiring a fix in this Activation.

LONG Cash Semantics

Unchanged, and explicitly accepted as correct under Model A: opening a LONG
debits cash -= gross_value (plus fee/tax) via the generic BUY formula,
exactly as today. A LONG sized over 50% of starting cash will show
required_margin > cash_after, which is expected and honest under the
rewritten invariant above (a fact about accept-time affordability, not a
claim that hasn't been re-verified post-trade), and is no longer treated as
a violation.

Impact on Existing Decision 11.1

Decision 11.1 Section I is amended as described in "Reconciliation
Invariant" above. Decisions A through H of Decision 11.1 (account currency,
leverage=1:1, pip size, pip value, pair universe, quantity unit, spread
model, stop-loss/maximum-loss) are all unaffected — none of them assumed
reserved-collateral semantics, and this decision changes nothing about
their formulas or scope.

Required Future Implementation

None for this Activation. If a future Activation needs genuine reserved
collateral (Model B) — for example, to support a margin-call or
liquidation feature explicitly out of scope today — it will require, at
minimum: a new persisted "reserved margin" concept (whether via
buying_power repurposed or a new field), AccountBalanceService gaining
Position.direction/quantity awareness it is currently forbidden from
having, PaperTradingEngine's gate becoming stateful, and
ReconciliationEngine gaining a real adequacy check to replace
reconstructability-only. That is a full architectural decision of its own
and is not started here.

Explicitly Deferred

used_margin / free_margin / margin balance

maintenance margin, margin level, margin call

liquidation mechanics

configurable paper leverage (already deferred by Decision 11.1 B)

any repurposing of buying_power

any change to AccountBalanceService, PaperTradingEngine,
PositionManager, or ReconciliationEngine

Model B in its entirety, beyond being named as the future path if ever
needed

Next Atomic Step

Edit Docs/ACTIVATION 11/ACTIVATION_11_1_FOREX_POLICY_DECISION.md Section I
to replace its current margin-adequacy bullet with the rewritten invariant
text under "Reconciliation Invariant" above (documentation-only edit to
that one bullet; no other section of that file, and no code, changes). This
closes the gap Activation 11.17 found by correcting the record the
architecture is actually being measured against, rather than by building
collateral-reservation machinery the roadmap never asked for.

Files Delivered

Files created:

Docs/ACTIVATION 11/ACTIVATION_11_18_FOREX_MARGIN_SEMANTICS_DECISION.md

Files modified:

none

Files renamed:

none
