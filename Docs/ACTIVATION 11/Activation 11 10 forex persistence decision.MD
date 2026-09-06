
# ACTIVATION 11.10 — FOREX PERSISTENCE DECISION

## Status

DECISION LOCKED

## Roadmap Basis

```
# ACTIVATION 11 — FOREX
```

Activation 11.9 confirmed:

```
Numerical proof:            ✅
Reconciliation proof:       NOT YET IMPLEMENTED
```

because no Forex state is persisted yet. Activation 11.1 (LOCKED) already fixed the
policy inputs this decision must build on top of without contradicting:

- USD-only account, `asset_class="forex"`, `currency="USD"` (11.1-A)
- 1:1 leverage, no margin call/level (11.1-B)
- pip size: `0.0001` non-JPY / `0.01` JPY (11.1-C)
- pip value only computable for USD-quoted pairs (11.1-D)
- `EUR/USD`, `GBP/USD` initial pair universe (11.1-E)
- `quantity` = base-currency units, no lot conversion (11.1-F)
- single reference price + deterministic spread adjustment, no bid/ask columns (11.1-G)
- `maximum_loss = pip_distance(entry, stop_loss, pip_size) × pip_value_per_pip(quantity)`,
  stop-loss required at entry (11.1-H)

Direct source inspection for this decision confirmed:

- `Database/models.py`: `Account` has one `cash`/`equity`/`buying_power` float set, no
  multi-currency fields. `Position` has an **unsigned** `quantity: float`, `status` is
  `CHECK`-constrained (SQL, baked into the applied `version=3` migration) to exactly
  `("open", "closed")` — no direction/side column exists anywhere.
- `Business/position_manager.py` (`PositionManager`): BUY with no OPEN position creates
  a position; BUY with an OPEN position merges (weighted-average `average_price`); SELL
  requires an OPEN position and raises `ValidationError` if `trade.quantity` exceeds the
  held `quantity` (never allowed to go negative). This is structurally **long-only** —
  there is no code path that opens a position from a SELL.
- `PositionManager.set_stop_loss_take_profit` hard-codes the LONG rule
  (`stop_loss < average_price`, `take_profit > average_price`) and its own docstring
  states this project has no short-position concept anywhere else, so no OPPOSITE-
  direction branch exists.
- `Business/account_balance_service.py`: `Account.buying_power` is read and passed
  straight back through, unchanged, on every trade — "margin/leverage, reserved for a
  future STEP." Nothing computes it.
- `Business/execution_service.py`: `Trade.fill_price` is sourced from
  `Order.requested_price` (or a future policy-computed price) — one price field, no
  bid/ask, consistent with 11.1-G.
- `Business/reconciliation_engine.py`: replays `Trade` history against the *exact*
  `PositionManager`/`AccountBalanceService` formulas already in production, per symbol,
  from an empty starting position — it does not invent new formulas, it re-executes the
  existing ones. Whatever this decision locks for direction/margin/stop-loss must stay
  something `PositionManager`'s formulas can be *generalized* to replay, not a parallel
  computation.

---

## A. Account Model

**Decision:** Reuse `Account` as-is. `asset_class="forex"`, `currency="USD"`, one default
account, exactly as Activation 11.1-A already locked. No separate Forex account table.

**Rationale:** `Account` already carries everything a USD, 1:1-leverage paper account
needs (`cash`, `equity`, `buying_power`, `asset_class` as a plain label). The existing
crypto/US-market accounts already prove the "one `Account` row per asset class, same
schema" pattern works without a dedicated table per market. A separate table would only
be justified if Forex needed a field generic `Account` structurally cannot hold — it
doesn't; margin is handled entirely by Decision E below without touching `Account`'s
shape.

## B. Position Model

**Decision:** Option 1 — extend generic `Position`, not a separate Forex position table,
via exactly one new column: `direction` (`TEXT`, values `"LONG"`/`"SHORT"`, `NOT NULL`,
defaulting existing non-Forex rows to `"LONG"`).

**Rationale:** `quantity` is already an unsigned magnitude everywhere in the codebase
(`Order`, `Trade`, `Position`, `RankingEngine`, etc.) — overloading it to carry sign would
be a silent behavior change for every non-Forex market that already assumes
`quantity >= 0` (the SELL-exceeds-held guard in `_reduce_sell` compares two unsigned
magnitudes directly). A Forex-specific position table (Option 3) would duplicate
`account_id`/`symbol`/`average_price`/`realized_pnl`/`stop_loss`/`take_profit`/
`buy_fee_accumulated` wholesale for one extra concept, which the roadmap's own Decision K
constraint ("do not redesign the database... do not create a Forex universe table")
rules out. One additive, nullable-free `direction` column is the minimum change that
lets `quantity` keep meaning "how much is held," while `direction` answers "held which
way" — the two are orthogonal, so they don't need to be fused into a signed number.

## C. Short Position Semantics

**Decision:** `direction` is set once when a position opens from flat and is immutable
for that position's lifetime (mirrors `Position.status`'s "closed rows are never
reopened" pattern — a reversal is a new position, not a mutation of `direction`).

- **BUY with no OPEN position (any account):** unchanged from today — opens
  `direction="LONG"`, `quantity=trade.quantity`, `average_price=trade.fill_price`.
- **SELL with no OPEN position, Forex account only:** opens `direction="SHORT"`,
  `quantity=trade.quantity` (still the unsigned magnitude sold-to-open),
  `average_price=trade.fill_price` (the short's entry price). For every non-Forex
  account this path stays exactly what it is today: `ValidationError`, "no OPEN position
  to sell from" — this decision does not change that behavior for the stock/crypto paths.
- **Same-direction trade (BUY on LONG, or SELL on SHORT):** generalizes
  `_merge_buy` — magnitude increases, `average_price` becomes the quantity-weighted
  average of the old position and the new trade, exactly the existing formula, direction
  unchanged.
- **Opposite-direction trade (SELL on LONG, or BUY on SHORT):** generalizes
  `_reduce_sell` — magnitude decreases by the trade's quantity; `average_price` is left
  untouched; realized P/L is direction-signed:

  - LONG close: `realized_pnl += (fill_price - average_price) * trade.quantity - fee - tax`
    (today's formula, unchanged).
  - SHORT close: `realized_pnl += (average_price - fill_price) * trade.quantity - fee - tax`
    (sign flipped — a SHORT profits when price falls).

  `status` becomes `"closed"` once magnitude reaches zero, otherwise `"open"` — the
  existing two-value domain is sufficient; no new status is introduced.
- **Opposite-direction trade whose quantity exceeds the held magnitude (i.e. an
  attempted same-trade reversal, e.g. BUY 2 lots against a 1-lot SHORT):** stays a
  `ValidationError`, identical in shape to today's SELL-exceeds-held guard. Reversing
  a position in a single trade (close-and-flip) is explicitly **out of scope** for the
  initial paper Forex implementation — a caller must close to flat, then open the
  opposite direction as a second trade. This is a direct, intentional consequence of not
  touching `_reduce_sell`'s bounds-check shape, not an oversight.

## D. Stop-Loss Persistence

**Decision:** Option 1 — keep the existing `Position.stop_loss` column; only its writer
semantics become direction-aware (a future implementation-step change to
`set_stop_loss_take_profit`, not a schema change):

```
LONG  → stop_loss < entry   (unchanged from today)
SELL/SHORT → stop_loss > entry   (new branch, mirrors take_profit's existing "> average_price" check)
```

**Rationale:** `stop_loss`/`take_profit` are already generic, nullable, position-level
columns with no LONG-only assumption baked into the schema itself — only the Python
validation in `set_stop_loss_take_profit` is LONG-only. Reading `Position.direction`
(Decision B) inside that same method to pick which inequality to enforce is a pure logic
change, zero persistence change, and keeps the Activation 11.5 invariant
(`BUY → stop_loss < entry`, `SELL → stop_loss > entry`) intact by construction rather
than by a new column.

## E. Required Margin

**Decision:** Option 3 — required margin stays **derived**, not persisted.
`Account.buying_power` remains untouched/inert, exactly as it is today.

**Rationale:** Under the 11.1-B lock (`leverage = 1:1`), `required_margin = price × quantity` is a pure function of `Position.average_price × Position.quantity` (both
already persisted) for any open Forex position, or `Order.requested_price × Order.quantity` pre-trade. Writing it into `Account.buying_power` would require
`AccountBalanceService` to start computing and persisting a value it explicitly never
has (its own docstring: "margin/leverage, reserved for a future STEP") — a business-logic
change this decision record is not authorized to make. The roadmap's own instruction
("do not assume `buying_power` must be used merely because it exists") is a direct
signal against reusing it here just because the field is sitting there unused; nothing
about margin reconciliation needs a persisted value when it is 100% reconstructable from
Position/Order rows that are persisted regardless.

## F. Maximum Loss

**Decision:** Derived, not persisted.

**Rationale:** Activation 11.1-H already locked `maximum_loss` as a deterministic
function of `entry_price` (`Position.average_price`/`Order.requested_price`),
`stop_loss` (`Position.stop_loss`), `quantity` (`Position.quantity`), and `pair`
(`Position.symbol`) — all four inputs are already persisted columns under this decision.
Persisting the output as a fifth value would create a redundant, driftable copy with no
auditability benefit: unlike `realized_pnl` (which reflects trades that already
happened and can never be recomputed once a trade is deleted/lost), `maximum_loss` is
recomputable at any time from state that is never mutated except through the same
BUY/SELL paths reconciliation already replays.

## G. Pip Value

**Decision:** Derived, not persisted.

**Rationale:** Direct continuation of Activation 11.1-D: `pip_value = pip_size(pair) × quantity`, and both `pair` (`Position.symbol`/`Trade.symbol`) and `quantity` are already
persisted for every other market. Persisting it would duplicate a value that changes
every time `quantity` changes (i.e. on every trade) for no reconciliation benefit — the
reconciliation contract (Decision J) only needs the *inputs* to be stable and persisted,
which they already are.

## H. Execution Price / Spread

**Decision:** `Order.requested_price` and `Trade.fill_price` are sufficient. No bid/ask
columns are added.

**Rationale:** Per Activation 11.1-G (LOCKED), the spread adjustment is applied *into*
the single execution price before it is persisted (BUY fills at reference + half-spread,
SELL fills at reference − half-spread) — the adjustment is a computation that happens
before the write, not a second value that needs its own column. `Trade.fill_price` is
already the append-only, immutable record of what price a Forex trade actually executed
at, which is exactly what future reconciliation needs to verify maximum-loss/pip-value
math against. Adding bid/ask now would be schema surface with no consumer, contradicting
Decision K.

## I. Order / Trade Model

**Decision:** Existing `Order`/`Trade` persist Forex orders/trades with **zero schema
change**.

**Rationale, field by field:**

- `action` (`BUY`/`SELL`) — already the only two values `PositionManager`/
  `AccountBalanceService` understand; Decision C reinterprets what a SELL-with-no-
  open-position *means* for a Forex account, but the column and its domain are
  unchanged.
- `quantity`/`requested_price`/`filled_price`/`filled_quantity`/`executed_at` — already
  generic, unit-agnostic magnitudes; 11.1-F already established `quantity` = base-
  currency units with no schema implication.
- `fee`/`tax` — Forex has no fee/tax policy yet (Activation 11.1-H explicitly excluded
  fees from `maximum_loss` "since no Forex-specific fee policy exists yet"); the existing
  `ExecutionPolicy` default (`0.0`/`0.0`) applies unchanged until a future Activation
  defines Forex-specific rates. No new column needed to represent "no policy yet" — it's
  the same `0.0` every other not-yet-priced path already uses.
- stop-loss association — lives on `Position` (Decision D), not `Order`/`Trade`; this is
  already true for every other market and Forex introduces no exception.
- margin/risk reconstruction — possible entirely from `Position.direction` (new,
  Decision B) + `average_price` + `quantity` + `stop_loss`, without any `Order`/`Trade`
  change.

## J. Reconciliation Contract

**Persisted source-of-truth:**

```
Account.cash
Position.direction        (new column, Decision B)
Position.quantity, average_price, realized_pnl, status, stop_loss
Order.action, quantity, requested_price, filled_price, filled_quantity, filled_at
Trade.action, quantity, fill_price, fee, tax, executed_at
```

**Deterministic derived values (never persisted):**

```
required_margin   = average_price × quantity                        (Decision E)
maximum_loss       = pip_distance(entry, stop_loss, pip_size) × pip_value_per_pip(quantity)   (Decision F)
pip_value           = pip_size(pair) × quantity                       (Decision G)
```

**Rationale:** This is a direct extension of `ReconciliationEngine`'s existing design —
it already replays `Trade` history through `PositionManager`'s exact formulas rather than
trusting persisted aggregates blindly. A future reconciliation step adds exactly one more
replay: direction-aware realized P/L (Decision C) plus the three derived formulas above,
recomputed from the same persisted `Position`/`Order`/`Trade` rows the engine already
reads — no new repository, no new read path, no hidden external state (satisfies 11.1-D's
"no live/external FX feed" constraint by construction, since nothing here needs one).

## K. Minimum Schema Change

**Decision:** Exactly one new column: `Position.direction` (`TEXT NOT NULL`, `CHECK direction IN ('LONG', 'SHORT')`, default `'LONG'` for all pre-existing rows on
migration). No changes to `Account`, `Order`, or `Trade`. No new tables.

**Rationale:** Every other requirement in this record (margin, maximum loss, pip value,
stop-loss direction, USD account) is satisfiable either by reusing an existing column
as-is (Decisions A, D, H, I) or by deriving on demand (Decisions E, F, G). `direction` is
the single fact that genuinely cannot be derived from anything already persisted — an
unsigned `quantity` alone cannot tell a replay whether a position is LONG or SHORT, and
that ambiguity is exactly what blocks Decision C's two-sided replay today. This is the
smallest change that unblocks two-sided positioning without redesigning the schema, a
Forex-only table, or a generic multi-market abstraction.

## L. Paper-Only Boundary

Explicitly out of scope for the initial paper Forex implementation, unchanged from
Activation 11.1's "Explicitly Deferred" list:

```
No live leverage
No broker execution
No autonomous execution
No deposits/withdrawals
No custody
No rollover/swap
No liquidation mechanics
No broker-specific spread/contract size
No non-USD-quoted pairs / live FX conversion feed
No standard/mini/micro lot conversion
No same-trade position reversal (close-and-flip) — see Decision C
```

## Explicitly Deferred

- The `direction` migration itself (schema change — next step, below).
- `PositionManager` generalization to read/write `direction` and compute signed
  realized P/L (Decision C).
- `set_stop_loss_take_profit` direction-aware validation branch (Decision D).
- `ReconciliationEngine` extension to replay direction-aware P/L and verify the three
  derived formulas (Decision J).
- Forex account creation, CLI wiring, `PaperTradingEngine` integration — none of this
  record creates an account or wires anything, per the HARD RULE.
- Same-trade position reversal (close-and-flip in one order) — Decision C.

## Next Implementation Step

Add a single additive migration (`Database/migrations_positions.py`, next version = 18)
that adds `Position.direction TEXT NOT NULL DEFAULT 'LONG' CHECK (direction IN ('LONG', 'SHORT'))`, update `Database.models.Position` with the new field (defaulting to
`"LONG"`, mirroring how `buy_fee_accumulated` was added additively at version=17), and
update `PositionRepository.create`/`update`/row-mapping to read/write it — with unit
tests proving: (a) every existing non-Forex test still passes with `direction` defaulting
to `"LONG"` and behaving identically to today, and (b) a position can be constructed
directly with `direction="SHORT"` and round-trips through the repository correctly. This
step deliberately does NOT touch `PositionManager`, does NOT create a Forex account, and
does NOT wire `PaperTradingEngine` — it only makes the one new column this decision
record identified (Decision B/K) real and persistable, which every later Forex step
(short-open logic, direction-aware stop-loss, reconciliation) depends on.
