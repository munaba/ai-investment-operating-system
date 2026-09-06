
# ACTIVATION 11.1 — FOREX POLICY DECISION

## Status

DECISION LOCKED

## Roadmap Basis

```
# ACTIVATION 11 — FOREX

Forex dikerjakan terakhir karena menambah risiko:

* leverage;
* margin;
* spread;
* pip value;
* lot size;
* rollover;
* session;
* liquidation;
* broker-specific rules.

## Activation awal

* analysis;
* paper forex;
* no leverage live;
* no autonomous execution.

## Acceptance Gate

Margin, pip value, stop-loss, dan maximum loss harus terbukti benar
melalui test numerik dan reconciliation.
```

Activation 11 audit finding (confirmed by direct source inspection): the repository has
no Forex implementation beyond `"forex"` being a legal `Account.asset_class` string.
`Account` (`Database/models.py`) has exactly one `currency: str` field and single
`cash`/`equity`/`buying_power` floats — no multi-currency support exists anywhere.
`buying_power` is explicitly documented as "margin/leverage, reserved for a future STEP"
(`Business/account_balance_service.py`) and is never computed. This decision record
exists to resolve the prerequisite the audit identified before any Forex code is written.

## A. Account Currency

**Decision:** The initial Forex paper account is USD-only. A single default account
(`asset_class="forex"`, `currency="USD"`) is the sole paper Forex account for this
Activation. `Account.cash`, `buying_power`-as-margin (once implemented), realized P/L,
maximum loss, and performance are all denominated in USD.

**Rationale:** This mirrors the existing, already-established pattern rather than
inventing a new one: `DEFAULT_CRYPTO_ACCOUNT_CURRENCY = "USD"` and
`DEFAULT_US_ACCOUNT_CURRENCY = "USD"` (`Core/bootstrap.py`) are both USD, each isolated
in its own account, with the IDR paper account (`DEFAULT_PAPER_ACCOUNT_CURRENCY = "IDR"`)
kept separate. `Account.currency` is already "a plain label, never converted" per
`Core/bootstrap.py`'s own comments ("No FX: currency is stored as a plain label, never
converted against ... any other currency") — USD-only for Forex requires zero change to
that existing invariant. Choosing IDR or a multi-currency account would either contradict
that documented behavior or require inventing a conversion mechanism this Activation is
not scoped to build.

**Future implications:** Any Forex pair whose quote currency is not USD requires either
(a) restricting the initial pair universe to USD-quoted pairs (see Decision E), or (b) a
conversion source, which does not exist and is not being built here (see Decision D).
`Account.currency` continues to be an unconverted label; nothing about this decision adds
FX conversion to `Account` itself.

## B. Leverage

**Decision:** Option 1 — paper Forex uses 1:1 only, no leverage, for this Activation.

**Rationale:** The roadmap's "Activation awal" list states `no leverage live` but is
silent on paper leverage. Choosing Option 2 (configurable paper leverage) would require
inventing initial margin / maintenance margin / margin level / margin call semantics —
none of which exist anywhere in the codebase today (`Account.buying_power` is reserved,
unimplemented) — purely to simulate a number with no broker-verified basis. That is
exactly the kind of ungrounded assumption Activation 11's audit-first instruction warns
against ("Do not decide by generic Forex knowledge"). 1:1 lets margin required always
equal full notional value, which is simple, numerically provable, and does not block a
later Activation from introducing configurable paper leverage once margin plumbing
(Decision H onward) actually exists and is tested.

**Paper behavior:** Every paper Forex position requires margin equal to its full notional
value (position size × price), i.e. `leverage = 1`. No margin call, no margin level, no
free/used margin split — those all reduce to trivial/constant values under 1:1 and are
therefore out of scope to build yet.

**Live behavior:** No live Forex trading exists in this Activation at all (confirmed by
audit: no broker integration, no live execution path). Live leverage is not merely
disabled — it has no code path to be disabled from.

## C. Pip Size

**Decision:** A pip is the second decimal place (`0.0001`) of the quoted exchange rate
for non-JPY-quoted pairs, and the first decimal place (`0.01`) for JPY-quoted pairs
(i.e., any pair whose quote currency is JPY). This is a fixed convention, not
configurable, for this Activation.

**Rationale:** This is the standard, unambiguous convention needed to make pip-value
arithmetic well-defined and testable; the audit found zero existing pip logic to reuse
or contradict. Restricting to exactly two fixed conventions (rather than a
per-broker-configurable pip size) keeps the initial pair universe (Decision E) small,
deterministic, and testable, per this Activation's own stated constraint, and avoids
inventing broker-specific pip conventions the roadmap explicitly forbids assuming.

## D. Pip Value / Currency Conversion

**Decision:** Initial Activation supports only pairs whose quote currency is USD (i.e.
`XXX/USD` pairs). This makes pip value computable directly with no conversion step:
`pip_value = pip_size × position_size_in_base_units`, already expressed in USD, the
account currency (Decision A).

**Same-currency quote (quote currency == USD):** Fully supported. Pip value is computed
directly, no conversion needed.

**Different-currency quote (quote currency != USD):** Not supported in this Activation.

```
BLOCKED BY EXTERNAL DEPENDENCY
```

Computing pip value correctly for a non-USD-quoted pair against a USD account requires a
live (or at minimum a deterministic, sourced) FX conversion rate, which does not exist in
this repository and which the roadmap explicitly forbids inventing ("Do NOT invent a live
FX conversion feed"). Rather than silently assume a fixed/fake conversion rate, this is
recorded as an explicit future blocker: a later Activation must either add a conversion
source or continue excluding non-USD-quoted pairs.

**Rationale:** This is the direct consequence of Decision A (USD-only account) combined
with the roadmap's Acceptance Gate requirement that pip value be "terbukti benar" (proven
correct) by numerical test — a requirement that cannot honestly be met for pairs needing
an unavailable conversion rate. Restricting to USD-quoted pairs is what makes pip value
provable now instead of deferred indefinitely.

## E. Initial Pair Universe

**Decision:** Exactly two pairs: `EUR/USD` and `GBP/USD`.

**Rationale:** Both are USD-quoted (satisfies Decision D), neither is JPY-quoted (so
Decision C's default pip-size convention applies uniformly, without yet needing to prove
the JPY branch), and two pairs is the minimum set that lets tests distinguish
pair-specific data (e.g. price, stop-loss distance) from a hard-coded single-pair
special case, while staying "small, deterministic, testable" per the roadmap's own
framing for this decision. Broker-specific pair availability was not used to choose these
— they were chosen solely to satisfy Decisions A/C/D with the smallest possible set.

## F. Quantity / Lot Unit

**Decision:** `quantity` represents base-currency units directly (e.g. `10000` means
10,000 units of the base currency), not a standardized lot count. There is no
standard/mini/micro lot conversion in this Activation.

**Rationale:** This is consistent with how `Order.quantity`/`Trade.quantity`/
`Position.quantity` already behave for every other market in the codebase (a plain
`REAL` unit count with no market-specific multiplier baked into the schema — confirmed
by `Database/migrations_orders.py`/`migrations_positions.py`/`migrations_trades.py`,
none of which have a lot-multiplier column). Reusing "quantity = base units" needs no
schema change and keeps pip-value/margin formulas (Decisions D/H) simple:
`pip_value = pip_size × quantity` with no intermediate lot-to-units conversion step to
get wrong. Standard/mini/micro lot conventions are explicitly deferred, per this
decision's own scope limit ("Do not implement standard/mini/micro lot logic yet").

## G. Spread Model

**Decision:** The initial paper model conceptually uses a deterministic spread-adjusted
execution price, not a stored bid/ask pair. That is: a single reference price plus a
policy-defined spread adjustment (BUY fills at reference + half-spread, SELL fills at
reference − half-spread, or equivalent), rather than persisting separate `bid`/`ask`
columns.

**Rationale:** `Order`/`Trade` currently have exactly one price field each
(`requested_price`/`filled_price`/`fill_price` — confirmed by audit), matching every
other market in the codebase. A spread-adjusted single price is additive to that existing
shape (no schema change forced), whereas a true bid/ask model would require a schema
change to every order/trade path, including non-Forex ones, or a Forex-only side table —
a larger structural decision this Activation is not scoped to make. No real-world spread
value or broker spread is chosen here — this decision is architecture-only, per this
decision's own scope limit.

## H. Stop-Loss / Maximum Loss

**Decision:** Maximum loss is calculated from a required stop-loss at trade entry, as a
pre-trade invariant (a paper Forex order without a stop-loss is not accepted), using the
core formula below. Spread is included (via the spread-adjusted execution price from
Decision G) since it affects the actual fill price the stop-loss distance is measured
from; fees/commissions are not included, since no Forex-specific fee policy exists yet
(only `ExecutionPolicy`'s generic fee, which is out of scope here) and inventing one
would duplicate Decision-D-style ungrounded assumption.

**Maximum-loss currency:** USD (the account currency, per Decision A), consistent with
pip value already being computed in USD under the USD-quote-only restriction (Decision
D).

**Core invariant:**

```
maximum_loss = pip_distance(entry_price, stop_loss, pip_size)
               × pip_value_per_pip(quantity)
```

where `pip_value_per_pip` is exactly Decision D's formula and `pip_distance` uses
Decision C's pip size. This is provisional in form only insofar as its inputs
(account currency, pip value, quantity unit) are now fixed by Decisions A/C/D/F — the
formula itself will not change shape without revisiting one of those.

**Rationale:** This directly targets the roadmap's Acceptance Gate ("Margin, pip value,
stop-loss, dan maximum loss harus terbukti benar melalui test numerik dan
reconciliation") by making maximum loss a strict function of already-decided,
provable quantities, with no new unresolved inputs.

## I. Reconciliation

**Required invariants** (for a future implementation step — `ReconciliationEngine` is
not modified by this decision record):

- Every Forex `Order`/`Trade`/`Position` replays to the same `Account.cash` change as
  every other market (existing generic invariant, unchanged).
- For every Forex trade that adds new exposure, the required margin for
  that trade's incremental new-exposure quantity, computed against the
  trade's execution price, did not exceed `Account.cash` at the moment the
  trade was accepted (i.e., the pre-trade gate's own check held at
  accept-time). This is a point-in-time affordability fact about trade
  acceptance, not a standing property of the account's current state,
  and is not re-derivable from a closed/settled position's final
  `Position`/`Account` rows alone — only from the trade-history record of
  what `Account.cash` was immediately before that specific trade.
  (Activation 11.18, MODEL A — affordability only.)
- Pip value used at trade time (Decision D) is reproducible from the persisted
  `entry_price`/pair/quantity alone, with no hidden or external input.
- Maximum loss (Decision H) as calculated pre-trade matches the maximum loss recomputed
  from the persisted stop-loss, entry price, and quantity.
- Stop-loss, once persisted on a `Position`, is never silently altered outside an
  explicit update path (already true generically per `PositionManager`'s locked
  contract — no new behavior required, only confirmation it holds for Forex too).

## Explicitly Deferred

- broker-specific rules
- live leverage
- live broker API
- rollover/swap
- liquidation mechanics
- broker-specific spread
- broker-specific contract size
- autonomous execution
- non-USD-quoted pairs / live FX conversion feed (Decision D)
- standard/mini/micro lot conversion (Decision F)
- configurable paper leverage (Decision B, Option 2 deferred, not rejected)

## Next Implementation Step

Implement the smallest testable slice of Decision D's formula in isolation: a pure,
dependency-free `Business/forex_pip_policy.py` module providing pip-size (Decision C)
and pip-value (Decision D, USD-quote-only) calculation functions plus unit tests proving
them numerically correct for `EUR/USD` and `GBP/USD` (Decision E) — no wiring into
`PaperTradingEngine`, `main.py`, or any account/schema change in this next step. This is
the one atomic step every later Forex phase (margin, stop-loss, maximum-loss,
reconciliation) depends on, and it can be built and proven entirely from Decisions
A/C/D/E/F without touching any existing production path.
