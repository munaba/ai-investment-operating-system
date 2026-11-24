"""v2 ranking: model rule, persistence and rebalance schedule (offline)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Business import factor_model as fm
from Business.v2_ranking_service import V2RankingService
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migration_registry import expected_migrations
from Database.migrations import MigrationRunner
from Database.migrations_v2_rankings import V2_RANKINGS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.v2_ranking_repository import V2RankingRepository

NOW = datetime(2026, 11, 25, 1, 30, tzinfo=UTC)


def _prices(days: int = 400, n: int = 30, seed: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-03-03", periods=days)
    drift = np.linspace(0.002, -0.001, n)  # S00 rises fastest, S29 falls
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(drift, 0.01, (days, n)), axis=0),
                         index=index, columns=[f"S{i:02d}" for i in range(n)])
    return close, pd.DataFrame(1e6, index=index, columns=close.columns)


@pytest.fixture()
def repo(tmp_path: Path):
    cfg = DatabaseConfig(db_path=tmp_path / "v2.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(V2_RANKINGS_MIGRATIONS)
    yield V2RankingRepository(DatabaseManager(db, cfg))
    db.disconnect()


def _service(repo, close, volume) -> V2RankingService:
    return V2RankingService(repo, fetch=lambda market, start, end: (close, volume))


def test_rule_ranks_by_distance_above_200_day_average() -> None:
    close, volume = _prices()
    ranking = fm.rank_universe(fm.IDX, close, volume)
    expected = (close / close.rolling(200).mean() - 1).iloc[-1].sort_values(ascending=False)
    assert list(ranking.scores.index) == list(expected.index)
    assert ranking.scores.iloc[0] == pytest.approx(expected.iloc[0])
    assert ranking.signal_date == close.index[-1].date()


def test_rule_uses_no_future_data() -> None:
    close, volume = _prices()
    cut = fm.rank_universe(fm.IDX, close.iloc[:300], volume.iloc[:300])
    full_trend = (close / close.rolling(200).mean() - 1).iloc[299].sort_values(ascending=False)
    assert list(cut.scores.index) == list(full_trend.index)


def test_stocks_without_a_year_of_history_are_not_ranked() -> None:
    close, volume = _prices()
    close.loc[close.index[:-100], "S00"] = np.nan  # listed 100 sessions ago
    assert "S00" not in fm.rank_universe(fm.IDX, close, volume).scores.index


def test_bars_dated_as_of_or_later_are_ignored(repo) -> None:
    close, volume = _prices()
    as_of = close.index[-1].date()  # today's bar is a live quote
    result = _service(repo, close, volume).run(fm.IDX, as_of, NOW)
    assert result.signal_date == close.index[-2].date().isoformat()


def test_first_run_is_a_rebalance_and_stores_the_picks(repo) -> None:
    close, volume = _prices()
    result = _service(repo, close, volume).run(fm.IDX, date(2027, 1, 1), NOW)
    assert result.is_rebalance and len(result.picks) == fm.TOP_K
    stored = repo.get_ranking("idx", result.signal_date)
    assert len(stored) == result.ranked
    assert [r.symbol for r in stored if r.picked] == result.picks
    assert stored[0].rank == 1 and stored[0].model_version == fm.MODEL_VERSION


def test_rerun_for_the_same_signal_date_changes_nothing(repo) -> None:
    close, volume = _prices()
    service = _service(repo, close, volume)
    first = service.run(fm.IDX, date(2027, 1, 1), NOW)
    again = service.run(fm.IDX, date(2027, 1, 1), NOW)
    assert again.already_stored and again.picks == first.picks


def test_next_rebalance_comes_after_hold_sessions(repo) -> None:
    close, volume = _prices()
    first_cut = len(close.index) - 30
    service = V2RankingService(repo, fetch=lambda m, s, e: (close, volume))
    first = service.run(fm.IDX, close.index[first_cut].date(), NOW)  # signal = row first_cut-1
    assert first.is_rebalance
    # 19 sessions later: not yet.
    mid = service.run(fm.IDX, close.index[first_cut + 19].date(), NOW)
    assert not mid.is_rebalance and mid.picks == [] and mid.sessions_since_rebalance == 19
    # 20 sessions later: rebalance.
    due = service.run(fm.IDX, close.index[first_cut + 20].date(), NOW)
    assert due.is_rebalance and due.sessions_since_rebalance == 20
    assert repo.last_rebalance_date("idx") == due.signal_date


def test_markets_are_kept_apart(repo) -> None:
    close, volume = _prices()
    service = _service(repo, close, volume)
    service.run(fm.IDX, date(2027, 1, 1), NOW)
    us = service.run(fm.US, date(2027, 1, 1), NOW)
    assert us.is_rebalance and not us.already_stored  # its own first rebalance


def test_too_little_history_is_refused(repo) -> None:
    close, volume = _prices(days=200)
    with pytest.raises(RuntimeError, match="completed sessions"):
        _service(repo, close, volume).run(fm.IDX, date(2027, 1, 1), NOW)


def test_migration_is_registered_with_a_new_version() -> None:
    versions = [v for v, _, _ in expected_migrations()]
    assert 35 in versions and len(versions) == len(set(versions))


class _FakeNotifier:
    def __init__(self) -> None:
        self.sent = []

    def notify(self, event) -> None:
        self.sent.append(event)


def test_cli_ranks_stores_and_notifies_once(repo, monkeypatch, capsys) -> None:
    import main
    from Business import v2_ranking_service as svc_module

    close, volume = _prices()
    monkeypatch.setattr(svc_module, "yahoo_panel", lambda market, start, end: (close, volume))
    notifier = _FakeNotifier()
    app = type("App", (), {"database_manager": repo._database_manager, "notification_manager": notifier})()

    assert main._run_v2_command(app, ["rank", "--market", "us", "--as-of", "2027-01-01"]) == 0
    out = capsys.readouterr().out
    assert "rebalance=True" in out and "picks" in out
    assert len(notifier.sent) == 1 and "AIOS v2 picks US" in notifier.sent[0].title
    assert "\n1. " in notifier.sent[0].message

    # Same signal date again: nothing new, no second notification.
    assert main._run_v2_command(app, ["rank", "--market", "us", "--as-of", "2027-01-01"]) == 0
    assert len(notifier.sent) == 1


def test_cli_rejects_bad_arguments(capsys) -> None:
    import main

    app = object()
    assert main._run_v2_command(app, []) == 2
    assert main._run_v2_command(app, ["rank", "--market", "jp"]) == 2
    assert main._run_v2_command(app, ["rank", "--market", "idx", "--as-of", "yesterday"]) == 2
    assert "Usage" in capsys.readouterr().out
