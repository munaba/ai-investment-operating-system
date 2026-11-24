"""v3 test: candidates and decision rule fixed in Docs/SIGNAL_EVALUATION.md
("v3 test plan") before this module was run.

    python Evaluation/v3_research.py            # development + validation sets

Exploratory: nothing here changes live signals.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Business.factor_model import IDX, MIN_HISTORY, US, Market, yahoo_panel
from Evaluation.factor_research import CACHE_DIR

HOLD = 20
SCHEDULES = 20
PASS_SHARE = 0.85

#: Validation universes: liquid names never used in any earlier research.
#: Today's lists (survivorship bias), but unseen by every selection so far.
IDX_VALIDATION = tuple(
    ["ADMR", "AGII", "AMMN", "APLN", "ASRI", "AVIA", "BBYB", "BFIN", "BJBR", "BJTM", "BMTR", "BNGA", "BNLI", "BRMS", "BTPS", "BUKA", "BUMI", "CMRY", "CUAN", "DEWA", "DMAS", "DOID", "DSNG", "DSSA", "ENRG", "GGRM", "GOTO", "HMSP", "INDY", "KAEF", "KIJA", "LPKR", "LPPF", "MAIN", "MBMA", "MIDI", "MPMX", "MTEL", "NCKL", "NISP", "PANI", "PNBN", "PNLF", "PTRO", "RAJA", "SILO", "SMDR", "SRTG", "SSIA", "TBIG", "TOBA", "ULTJ", "WSKT", "AUTO", "BSDE"][:-2]  # AUTO and BSDE are already in the development set
)
US_VALIDATION = ("AA", "ACI", "AFG", "AGCO", "ALK", "ALLY", "AN", "APA", "AR", "ARW", "ASH", "ATI", "AVT", "AXTA", "AYI", "BBWI", "BC", "BERY", "BJ", "BLD", "BURL", "BWA", "BYD", "CACI", "CAR", "CASY", "CBSH", "CC", "CFR", "CG", "CHDN", "CHRD", "CIEN", "CLF", "CMC", "CNX", "COHR", "COLM", "CPRI", "CR", "CROX", "CUBE", "CW", "DAR", "DCI", "DECK", "DINO", "DKS", "DT", "EHC", "ELF", "EME", "EQH", "ESAB", "EVR", "EWBC", "EXP", "FAF", "FCN", "FHN", "FIVE", "FIX", "FLR", "FN", "FND", "FNF", "FTI", "GGG", "GLPI", "GME", "GNTX", "GPK", "GXO", "H", "HOG", "HRB", "HXL", "IBKR", "ITT", "JAZZ", "JEF", "JLL", "KBR", "KEX", "KNX", "LAD", "LEA", "LECO", "LII", "LNTH", "LPX", "LSCC", "M", "MANH", "MAT", "MEDP", "MIDD", "MKSI", "MTDR", "MTZ", "MUSA", "NOV", "NVT", "NYT", "OC", "OGE", "OLED", "ORI", "OSK", "OVV", "PNFP", "POST", "PRI", "PSTG", "R", "RGA", "RGLD", "RH", "RRC", "RS", "SAIA", "SCI", "SF", "SFM", "SKX", "SNX", "SSD", "ST", "STLD", "THC", "THO", "TKR", "TOL", "TPX", "TREX", "TTEK", "TXRH", "UFPI", "UNM", "USFD", "VNT", "WAL", "WBS", "WCC", "WEX", "WFRD", "WING", "WMS", "WSM", "WSO", "XPO")


@dataclass(frozen=True)
class Candidate:
    top_k: int
    score: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame]  # (trend, vol) -> score
    vol_filter: bool = False
    regime_filter: bool = False


def _trend(trend, vol):
    return trend


def _risk_adjusted(trend, vol):
    return trend / vol


CANDIDATES = {
    "A_v2_top5": Candidate(5, _trend),
    "B_top10": Candidate(10, _trend),
    "C_top10_regime": Candidate(10, _trend, regime_filter=True),
    "D_top10_lowvol": Candidate(10, _trend, vol_filter=True),
    "E_top10_trend_per_vol": Candidate(10, _risk_adjusted),
    "F_regime_lowvol": Candidate(10, _trend, vol_filter=True, regime_filter=True),
}


def fetch(market: Market, symbols: tuple[str, ...], years: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    tag = hashlib.sha1(" ".join(symbols).encode()).hexdigest()[:8]
    path = CACHE_DIR / f"v3_{market.name}_{tag}_{years}y_{date.today().isoformat()}.pkl"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        close, volume = pd.read_pickle(path)
    else:
        end = date.today()
        close, volume = yahoo_panel(market, date(end.year - years, end.month, min(end.day, 28)), end, symbols)
        pd.to_pickle((close, volume), path)
    keep = close.index.date < date.today()
    return close[keep], volume.reindex(close.index)[keep]


def simulate(close: pd.DataFrame, cand: Candidate, cost: float) -> pd.DataFrame:
    """One row per (schedule, rebalance date)."""
    trend = close / close.rolling(200).mean() - 1
    vol = close.pct_change(fill_method=None).rolling(60).std()
    score = cand.score(trend, vol)
    fwd = close.shift(-(1 + HOLD)) / close.shift(-1) - 1
    uni = fwd.mean(axis=1)
    level = (1 + close.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    regime_down = level < level.rolling(200).mean()

    rows = []
    for offset in range(SCHEDULES):
        prev: set = set()
        for t in close.index[MIN_HISTORY + offset :: HOLD]:
            if np.isnan(uni.loc[t]):
                continue
            s = score.loc[t].replace([np.inf, -np.inf], np.nan).dropna()
            s = s[fwd.loc[t, s.index].notna()]
            if cand.vol_filter:
                v = vol.loc[t, s.index].dropna()
                s = s[v[v <= v.quantile(2 / 3)].index]
            if len(s) < 2 * cand.top_k:
                continue
            if cand.regime_filter and regime_down.loc[t]:
                rows.append({"offset": offset, "date": t, "net": 0.0, "abs": uni.loc[t], "uni": uni.loc[t],
                             "best": 0.0, "beat": np.nan, "held": False})
                prev = set()
                continue
            picks = list(s.nlargest(cand.top_k).index)
            changed = len(set(picks) - prev) / cand.top_k
            prev = set(picks)
            r = fwd.loc[t, picks]
            excess = r - uni.loc[t]
            rows.append({"offset": offset, "date": t, "net": float(excess.mean() - changed * cost),
                         "abs": float(r.mean()), "uni": float(uni.loc[t]),
                         "best": float(excess.max() / cand.top_k), "beat": float((excess > 0).mean()),
                         "held": True})
    return pd.DataFrame(rows)


def measures(df: pd.DataFrame) -> dict:
    per_schedule = df.groupby("offset")["net"].mean()
    drawdowns = []
    for _, g in df.groupby("offset"):
        equity = (1 + g.sort_values("date")["abs"]).cumprod()
        drawdowns.append(float((equity / equity.cummax() - 1).min()))
    return {
        "mean_net": float(df["net"].mean()),
        "positive_share": float((per_schedule > 0).mean()),
        "without_best": float((df["net"] - df["best"]).mean()),
        "beat_share": float(df["beat"].mean()),
        "worst_drawdown": float(np.mean(drawdowns)),  # mean over schedules of each one's worst drawdown
    }


def improvements(m: dict, base: dict) -> int:
    return sum([
        m["without_best"] > base["without_best"],
        m["beat_share"] > base["beat_share"],
        m["worst_drawdown"] > base["worst_drawdown"],  # less negative is better
    ])


def evaluate(sets: dict[str, tuple[Market, tuple[str, ...]]]) -> dict:
    out = {}
    for label, (market, symbols) in sets.items():
        close, _ = fetch(market, symbols)
        out[label] = {"stocks": int(close.shape[1]),
                      "results": {n: measures(simulate(close, c, market.round_trip_cost)) for n, c in CANDIDATES.items()}}
    return out


def qualifies(report: dict, labels: list[str], name: str) -> bool:
    for label in labels:
        res = report[label]["results"]
        if res[name]["positive_share"] < PASS_SHARE or improvements(res[name], res["A_v2_top5"]) < 2:
            return False
    return True


def _print(report: dict, title: str) -> None:
    print(f"\n=== {title}")
    for label, block in report.items():
        print(f"--- {label} ({block['stocks']} stocks)")
        print(f"{'candidate':<24}{'mean net':>9}{'pos sched':>10}{'w/o best':>9}{'beat':>6}{'drawdown':>9}")
        base = block["results"]["A_v2_top5"]
        for name, m in block["results"].items():
            mark = "" if name.startswith("A_") else f"  +{improvements(m, base)}/3"
            print(f"{name:<24}{m['mean_net']:>+9.2%}{m['positive_share']:>10.0%}{m['without_best']:>+9.2%}"
                  f"{m['beat_share']:>6.0%}{m['worst_drawdown']:>+9.0%}{mark}")


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    dev = evaluate({"IDX development": (IDX, IDX.universe), "US development": (US, US.universe)})
    _print(dev, "Stage 1: development universes")
    stage1 = [n for n in CANDIDATES if n != "A_v2_top5" and qualifies(dev, list(dev), n)]
    print(f"\nQualified on development: {stage1 or 'none'}")
    if not stage1:
        print("Decision: v2 stays (no candidate qualified).")
        return 0
    val = evaluate({"IDX validation": (IDX, IDX_VALIDATION), "US validation": (US, US_VALIDATION)})
    _print(val, "Stage 2: universes never used before")
    passed = [n for n in stage1 if qualifies(val, list(val), n)]
    if not passed:
        print("\nDecision: no qualified candidate passed validation; v2 stays.")
        return 0
    winner = max(passed, key=lambda n: min(val[k]["results"][n]["without_best"] for k in val))
    print(f"\nPassed validation: {passed}\nDecision: {winner} becomes the v3 candidate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
