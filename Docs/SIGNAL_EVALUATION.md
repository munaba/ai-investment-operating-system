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

## 2026-11-24 addendum: diagnostics and a proposed v2 (rules above unchanged)

`Evaluation/signal_diagnostics.py` (tests: `Tests/test_signal_diagnostics.py`)
breaks the scored signals down by confidence, score tercile and score factor.
It is exploratory only: it never feeds the official verdict.

First run on the exploratory sample (53 completed signals, August to November
2026, prices up to 2026-11-23):

| Finding | Evidence |
|---|---|
| News sentiment never votes | 222 of 225 successful scans record `news=neutral`; the sentiment factor is 0 in every row. The Yahoo news endpoint fails for `.JK` tickers, `MarketNewsTool` turns zero headlines into `neutral`, and missing data is therefore counted as neutral evidence. |
| The effective rule is two-factor | With news stuck at neutral, BUY means "price trend bullish and valuation undervalued". 71% of scans are BUY, and HIGH confidence (3 of 3 votes) is practically unreachable. |
| The score mostly restates the label | The recommendation weight contributes 10 to 30 of a 11 to 38 range. |
| Nothing predicts excess return yet | Every Spearman correlation with excess return is below 0.2 (score +0.10, valuation +0.17); higher-score tercile +0.37% vs. -0.25% mean excess, both near a coin flip. Too small to act on. |

Proposed v2 (not deployed):

1. Report missing news as `unavailable`, not `neutral`, and decide on the two
   axes that have data, saying so in the evidence; or restore a working news
   source (an Indonesian-language source, since the keyword lexicon is
   English) before news is allowed to vote.
2. Make BUY selective: require a minimum score margin or rank cut-off instead
   of firing on most of the watchlist.
3. Scale the score to its stated 0 to 100 range so the dashboard's score bars
   mean something.

Deployment rule: v2 changes which signals exist, so it cannot be mixed into
the v1 sample. Either v1 runs to its verdict first, or v1 is closed with
zero completed official signals and the test is re-registered for v2 with a
new date in a new section. Both choices are recorded here when made.

### Backtest of candidate price rules (2026-11-24, exploratory)

`Evaluation/backtest_rules.py` (tests: `Tests/test_backtest_rules.py`) scores
simple price rules on five years of Yahoo daily closes with the outcome
definition above (entry next close, excess vs. the equal-weight universe).
The first 70% of the history is used to compare rules; the last 30%
(2025-05-29 to 2026-11-23) is a holdout. Valuation and news cannot be
backtested this way: Yahoo only gives today's PE.

| Universe, holding period | Result |
|---|---|
| Watchlist (11, six of them banks), 5 days | No rule has an edge. The v1 price input ("price above the previous close") is -0.05% / -0.04% mean excess; every rule has non-overlapping \|t\| < 1. |
| 40 liquid IDX stocks, 5 days | Still nothing significant. Top-3 by 60-day momentum is positive in both periods (+0.34% / +0.21%, t 0.8 / 0.5). Buying the 5-day losers is clearly worse in the holdout (-0.91%, t -3.1). |
| 40 liquid IDX stocks, 20 days | Top-3 by 60-day momentum: +1.64% selection / +1.63% holdout mean excess per 20 days, t 1.0 / 1.2, hit rate about 50% (gains come from a few large winners). The only rule consistent across both periods. |

Reading: the v1 price input carries no information, and at a five-day
horizon no simple price rule does better. Medium-term momentum over a
monthly holding period is the one direction worth a longer look. It is not
proven: t is about 1, six rules were tried, and the 40-stock list is today's
liquid names (survivorship bias in its favour). A v2 built on it would need
its own pre-registration, probably with a 20-day horizon.

### Factor research for v2 (2026-11-24, exploratory)

`Evaluation/factor_research.py` (tests: `Tests/test_factor_research.py`)
ranks 59 liquid IDX stocks on nine factors (momentum, residual momentum,
52-week high, trend, low volatility, reversal, liquidity, and a v1-like
1-day return), buys the top 5 at the next close every 20 trading days,
holds 20 days and charges 0.4% round trip on changed names. Seven years of
Yahoo data; rebalances from 2020-12 to 2024-12 are the selection period,
2025-01 to 2026-10 the holdout. Candidates: single factors, a composite
fixed from published evidence, an IC-weighted composite whose weights come
only from earlier outcomes, and a ridge regression retrained each period on
earlier outcomes (a small stand-in for Qlib's Alpha158 + LightGBM).

Net excess per 20-day period, selection / holdout, in four configurations
(top 5 / hold 20, top 10, hold 10, top 3):

| Logic | Holdout results | Note |
|---|---|---|
| IC-weighted walk-forward | +1.08%, +0.90%, +0.31%, +0.61% | The only logic positive in every holdout (and every selection period). Holdout hit rate 60-64%. t below 1.1 everywhere. |
| Ridge walk-forward | -1.26%, -0.66%, -1.38%, -1.79% | Strong in selection, negative in every holdout: overfitting. |
| v1-like (1-day return) | -2.36%, -1.81%, +0.11%, -2.70% | Buying yesterday's risers loses to the universe. |
| "Best on selection" | evidence composite, residual momentum, momentum 120d skip 20 | The selection winner changes with the configuration, and two of them were negative in some holdouts. |

Reading: picking the best backtest is unreliable here; an adaptive
weighting learned only from past outcomes held up best. That was noticed
after looking at the holdouts, so it is a hypothesis, not a result. A v2
based on it (IC-weighted, top 5, 20-day hold; `--today` prints current
picks) must be pre-registered and judged on live signals like v1.
Survivorship bias (today's liquid names) and the IDX cost estimate are the
main known distortions.
