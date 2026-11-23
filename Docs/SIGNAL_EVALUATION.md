# Signal evaluation (pre-registered)

Registered: **2026-11-24**, before any signal from the automated scheduler
(first automated trading day) had an outcome. The rules below are fixed.
Changing them later requires a new, dated section that explains why, and the
official verdict must keep reporting results under the original rules.

Implementation: `Evaluation/signal_evaluation.py` (tests:
`Tests/test_signal_evaluation.py`).

## Question

Do AIOS `BUY` recommendations pick IDX watchlist stocks that outperform the
rest of the watchlist over the following week?

## Definitions

| Term | Rule |
|---|---|
| Signal | One `ranking_snapshots` row with `status = 'success'` and a recommendation of `BUY`, `WAIT` or `SELL`. |
| One signal per stock per day | The scheduler scans every 5 minutes during the session, so only the **first** successful scan of a symbol on a given WIB calendar date counts. Later scans that day are ignored. |
| Entry | Closing price on the **first trading day after** the scan date (WIB). Using the next close avoids look-ahead when the scan ran during or after that day's session. |
| Exit | Closing price **5 trading days after entry**. Trading days are the dates on which the symbol has a daily bar. Only fully closed sessions count: a bar dated today (WIB) is ignored, because it is a live quote until the closing auction ends. |
| Forward return | `exit / entry - 1`. Prices are daily closes from Yahoo Finance (`<SYMBOL>.JK`, auto-adjusted). |
| Benchmark | Equal-weight mean forward return of **every watchlist symbol** over the same entry and exit dates. |
| Excess return | Forward return minus benchmark. |
| Hit | `BUY`: excess > 0. `SELL`: excess < 0. `WAIT` has no hit definition. |
| Pending | A signal whose exit date has not happened yet. Not counted. |

## Verdict (BUY only)

| Condition | Verdict |
|---|---|
| Fewer than **30** completed `BUY` signals | `DATA_TIDAK_CUKUP` |
| Mean excess return > 0 **and** hit rate > 50% | `PASS` |
| Otherwise | `FAIL` |

`WAIT` and `SELL` are reported (count, mean return, mean excess, SELL hit
rate) but have no pass/fail verdict.

## In-sample vs. out-of-sample

Only signals dated **on or after 2026-11-24** count toward the official
verdict. Earlier scans (August to November 2026) are shown separately as
*exploratory*: they were generated while the system was still being built,
partly from manual and test runs.

## Known limitations

- **Survivorship and selection:** the watchlist is hand-picked large caps; a
  win against this benchmark says nothing about the wider market.
- **No costs:** fees, taxes and slippage are not deducted.
- **Small, correlated sample:** signals on the same day share market moves,
  so 30 signals is a minimum, not proof. Treat a `PASS` as "worth a longer
  look", not as an edge.
- **Data source:** Yahoo Finance bars can be missing or revised; a symbol
  without both an entry and an exit close is left pending.
