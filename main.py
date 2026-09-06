from __future__ import annotations

import math
import os
import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from Services.decision_brief_service import RiskInputs

from Business.forex_pip_policy import SUPPORTED_PIP_VALUE_PAIRS, _normalize_pair
from Business.idx_market_calendar import (
    POST_CLOSE_END,
    PRE_MARKET_OPEN,
    load_idx_market_calendar,
)
from Business.notification_event import NotificationEvent
from Business.report_service import Report
from Business.us_market_policy import is_valid_us_symbol
from Core.bootstrap import (
    DEFAULT_CRYPTO_ACCOUNT_ID,
    DEFAULT_FOREX_ACCOUNT_ID,
    DEFAULT_PAPER_ACCOUNT_ID,
    DEFAULT_US_ACCOUNT_ID,
)
from Core.composition_root import build_application
from Core.doctor import run_doctor_command
from Core.exceptions import RepositoryError, ValidationError
from Core.init_command import run_init
from Core.init_forex_command import run_init_forex
from Core.init_us_command import run_init_us
from Core.logger import get_logger
from Core.market_config import is_crypto_symbol
from Core.startup_validation import validate_runtime_environment
from Core.request_defaults import DEFAULT_INTERVAL, DEFAULT_MAX_NEWS, DEFAULT_PERIOD
from Orchestration.autonomous_agent import AutonomousAgentStatus
from Orchestration.autonomous_host import AutonomousHost
from Database.backup import create_backup, verify_backup
from Database.database_config import DatabaseConfig
from Database.models import RankingSnapshot
from Orchestration.autonomous_agent import AutonomousAgentError
from Orchestration.memory import LessonRecord
from Orchestration.memory import MemoryError as PreferenceMemoryError
from Orchestration.memory import PreferenceRecord
from Orchestration.memory import PreviousDecisionRecord
from Orchestration.memory import StrategyNoteRecord
from Orchestration.planner import Goal
from Orchestration.runtime_analysis_pipeline import VISION_CHART_PATH_METADATA_KEY
from Orchestration.tool_context import ToolContext
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext

logger = get_logger(__name__)

#: Actions this module's "paper" command recognizes -- mirrors
#: ``Business.paper_trading_engine._BUY``/``_SELL`` (deliberately
#: re-declared here, not imported, same as that module re-declares
#: rather than importing ``OrderLifecycleService``'s private constants
#: -- this is CLI-layer dispatch, not a second definition of the
#: engine's own action domain, which remains the sole validator via
#: gate 4 "symbol valid"/structural checks inside ``submit_order()``).
_PAPER_BUY = "BUY"
_PAPER_SELL = "SELL"


def _build_autonomous_metadata(ticker: str) -> dict:
    """Same metadata shape StockAgent._run_service_pipeline already seeds
    for its Stage L12 (RuntimeAnalysisPipeline) path: ticker/period/
    interval/max_news, plus the shared chart-path bridge the vision step
    reads afterwards. Reused as-is here, not reimplemented differently.
    """
    chart_path = tempfile.NamedTemporaryFile(
        prefix="chart_", suffix=".png", delete=False
    ).name
    return {
        MetadataKeys.TICKER: ticker,
        MetadataKeys.PERIOD: DEFAULT_PERIOD,
        MetadataKeys.INTERVAL: DEFAULT_INTERVAL,
        MetadataKeys.MAX_NEWS: DEFAULT_MAX_NEWS,
        MetadataKeys.IMAGE_PATH: chart_path,
        VISION_CHART_PATH_METADATA_KEY: chart_path,
    }


def _run_autonomous(app, ticker: str, iterations: int) -> None:
    """Production runtime caller for AutonomousAgent (Phase 22).

    Builds one Goal + one ServiceContext for ``ticker``, hands the Goal
    to the already-injected GoalPlanner via ``plan_goal()``, then drives
    ``iterations`` real cycles through ``app.autonomous_agent.run()`` --
    the same singleton ApplicationGraph already builds and wires with
    RuntimeAnalysisPipeline/GoalPlanner/the ten L18-L27 stages. No new
    component is constructed here; this only calls what already exists.
    """
    ticker = ticker.upper()
    metadata = _build_autonomous_metadata(ticker)
    context = ServiceContext(
        agent_name=app.agent_name,
        provider_name=app.provider_name,
        request_id=str(uuid.uuid4()),
        user_input=f"autonomous analysis: {ticker}",
        conversation_history=[],
        metadata=metadata,
    )
    agent = app.autonomous_agent

    try:
        agent.set_goal(Goal(metadata=metadata))
        plan = agent.plan_goal()
        print(f"[auto] GoalPlanner built a {len(plan.steps)}-step plan for {ticker}")
    except AutonomousAgentError as exc:
        print(f"[auto] goal/plan step skipped: {exc}")

    try:
        results = agent.run(context, max_iterations=iterations)
    except AutonomousAgentError as exc:
        print(f"[auto] run stopped: {exc}")
        return

    for result in results:
        state = "ok" if result.success else "FAILED"
        print(f"[auto] cycle {result.iteration}: {state} at {result.timestamp}")


def _print_manual_scan_report(report: Report) -> None:
    """Render a ``Report`` to the console (Sprint 5 STEP 7, LOCKED
    DECISION 4/6).

    Purely display logic -- reads ``report.total_symbols``/
    ``report.recommendations`` and prints them, computing nothing that
    ``ManualScanService``/``ReportService``/``RecommendationService``
    did not already produce (no new sorting, filtering, or scoring).

    ``report.total_symbols == 0`` (LOCKED DECISION 6, empty watchlist)
    prints ``"No symbols found."`` and returns -- not treated as an
    error, no non-zero exit, no exception.

    The BUY/WAIT/SELL counts mirror the exact three recommendation
    labels ``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
    already normalizes every recommendation to (LOCKED DECISION 4's own
    example spelled the middle bucket "HOLD"; this project's real data
    only ever produces "WAIT" for that bucket, so the label here matches
    what the pipeline actually emits -- content, not just format, must
    match the real data).
    """
    if report.total_symbols == 0:
        print("No symbols found.")
        return

    buy_count = sum(1 for rec in report.recommendations if rec.recommendation == "BUY")
    wait_count = sum(1 for rec in report.recommendations if rec.recommendation == "WAIT")
    sell_count = sum(1 for rec in report.recommendations if rec.recommendation == "SELL")

    print("Manual Scan Completed")
    print()
    print(f"Total Symbols : {report.total_symbols}")
    print()
    print(f"BUY  : {buy_count}")
    print(f"WAIT : {wait_count}")
    print(f"SELL : {sell_count}")
    print()
    for rec in report.recommendations:
        print(rec.symbol)
        print(rec.recommendation)
        print(rec.confidence)
        print()


def _print_scan_snapshot_rows(app, generated_at: str) -> None:
    """Section 2.8 CLI scanner -- print the persisted
    ``ranking_snapshots`` rows for this scan (both success and
    ``status="error"`` rows), read back from ``app.snapshot_repository``
    via ``list_by_scan_time(generated_at)``.

    This is purely a read-and-print of what ``ManualScanService.run_scan()``
    already persisted (LOCKED pipeline, unchanged) -- no new scoring,
    ranking, or filtering happens here. Failed tickers, which
    ``RankingEngine.rank()`` silently excludes from ``Report``, are
    still visible here because ``ManualScanService`` already persists
    them as ``status="error"`` rows (Activation 2.7). Displayed here
    as ``DATA_ERROR`` per the Section 2.8 acceptance gate wording --
    or, as of the IDX-scan-status fix, as the real
    ``DATA_ERROR``/``ANALYSIS_FAILED``/``INSUFFICIENT_DATA``/``SKIPPED``
    status when ``RankingEngine._diagnose_failure`` reported one of
    those four explicit values, so a symbol excluded for having
    insufficient data is no longer mislabeled as a generic data error.
    """
    rows = app.snapshot_repository.list_by_scan_time(generated_at)
    if not rows:
        print("No symbols found.")
        return

    print(f"Scan snapshot -- generated_at: {generated_at}")
    print()
    for row in rows:
        if row.status == "error":
            # Activation IDX-scan-status fix: RankingEngine._diagnose_failure
            # now reports one of the four explicit upstream failure
            # statuses verbatim (see Business/ranking_engine.py) instead
            # of always synthesizing "unrecognized recommendation: ...".
            # Display that real status directly rather than collapsing
            # every excluded symbol into "DATA_ERROR" regardless of why
            # it was excluded. Anything else (a genuine, unanticipated
            # error reason) still falls back to the original "DATA_ERROR
            # reason=..." wording, unchanged.
            if row.error_message in ("DATA_ERROR", "ANALYSIS_FAILED", "INSUFFICIENT_DATA", "SKIPPED"):
                print(f"{row.symbol:<8} {row.error_message}")
            else:
                print(f"{row.symbol:<8} DATA_ERROR   reason={row.error_message}")
        else:
            print(
                f"{row.symbol:<8} rank={row.rank:<3} score={row.score:<4} "
                f"{row.recommendation:<4} confidence={row.confidence:<6} "
                f"evidence={row.evidence_summary!r}"
            )
    print()


def _run_manual_scan(app) -> None:
    """Manual scan command entry point (Sprint 5 STEP 7).

    Does exactly three things, in exactly this order (LOCKED DECISION 2):

        1. ``generated_at`` is created here, at the moment this command
           runs (LOCKED DECISION 3 -- ``ManualScanService`` never
           generates its own timestamp, see its own docstring).
        2. ``app.manual_scan_service.run_scan(generated_at)`` -- the
           one and only call into the Sprint 5 pipeline (LOCKED
           DECISION 1: never ``WatchlistScanner``/``RankingEngine``/
           ``RecommendationService``/``ReportService``/
           ``SnapshotRepository`` directly).
        3. The returned ``Report`` is printed via
           ``_print_manual_scan_report``.

    No ``try``/``except`` here (LOCKED DECISION 7): any exception
    ``ManualScanService.run_scan()`` raises propagates unchanged, with
    no wrapper and no custom error type.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    report = app.manual_scan_service.run_scan(generated_at)
    _print_manual_scan_report(report)


def _run_watchlist_add(app, tickers: list[str]) -> int:
    """``python main.py watchlist add TICKER [TICKER ...]``.

    Calls the existing, unmodified ``WatchlistRepository.add()`` once
    per ticker (idempotent -- see that method's own docstring). No
    new validation, normalization, or storage logic is introduced
    here beyond upper-casing the ticker for display/consistency.
    """
    if not tickers:
        print("Usage: python main.py watchlist add TICKER [TICKER ...]")
        return 1
    normalized = [t.upper() for t in tickers]
    for ticker in normalized:
        app.watchlist_repository.add(ticker)
    print(f"Added to watchlist: {', '.join(normalized)}")
    return 0


def _run_watchlist_list(app) -> int:
    """``python main.py watchlist list``.

    Calls the existing, unmodified ``WatchlistRepository.list_all()``
    and prints each ticker, oldest addition first (that method's own
    ordering).
    """
    tickers = app.watchlist_repository.list_all()
    if not tickers:
        print("Watchlist is empty.")
        return 0
    print(f"Watchlist ({len(tickers)}):")
    for ticker in tickers:
        print(f"  {ticker}")
    return 0


def _run_watchlist_remove(app, tickers: list[str]) -> int:
    """``python main.py watchlist remove TICKER [TICKER ...]``.

    Activation 4 Session 1. Calls the existing, unmodified
    ``WatchlistRepository.remove()`` once per ticker (idempotent --
    see that method's own docstring: removing a ticker not on the
    watchlist is a no-op, not an error). No new validation,
    normalization, or storage logic beyond upper-casing the ticker
    for display/consistency -- mirrors ``_run_watchlist_add`` exactly.
    """
    if not tickers:
        print("Usage: python main.py watchlist remove TICKER [TICKER ...]")
        return 1
    normalized = [t.upper() for t in tickers]
    for ticker in normalized:
        app.watchlist_repository.remove(ticker)
    print(f"Removed from watchlist: {', '.join(normalized)}")
    return 0


def _run_watchlist_command(app, argv: list[str]) -> int:
    if not argv:
        print("Usage: python main.py watchlist <add|remove|list> [TICKER ...]")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "add":
        return _run_watchlist_add(app, rest)
    if subcommand == "remove":
        return _run_watchlist_remove(app, rest)
    if subcommand == "list":
        return _run_watchlist_list(app)
    print(f"Unknown watchlist subcommand: {subcommand!r} (expected 'add', 'remove', or 'list')")
    return 1


def _run_preference_set(app, argv: list[str]) -> int:
    """``python main.py preference set KEY VALUE``.

    Activation 12, Phase 3. Stores one non-financial user preference as a
    fresh :class:`~Orchestration.memory.PreferenceRecord`, added to the
    existing, unmodified ``app.memory_store`` -- the same ``MemoryStore``
    instance the ApplicationGraph already built and wires into the
    observation/reflection path. No second store is constructed here.

    ``MemoryStore.add()`` is append-only and keyed by each record's own
    fresh ``record_id`` (see ``Orchestration.memory.MemoryStore.add``) --
    it has no notion of replacing an existing value for a given ``key``.
    So "set" is honest about that actual store contract: setting the same
    key again does not overwrite the prior record, it adds a new one:
    ``_run_preference_get``/``_run_preference_list`` below resolve that by
    reading the most recently added record for a given key.
    """
    if len(argv) < 2:
        print("Usage: python main.py preference set KEY VALUE")
        return 1
    key, value = argv[0], argv[1]
    try:
        record = PreferenceRecord(key=key, value=value, source="cli")
    except PreferenceMemoryError as exc:
        print(f"Invalid preference: {exc}")
        return 1
    app.memory_store.add(record)
    print(f"Preference set: {key} = {value}")
    return 0


def _run_preference_get(app, argv: list[str]) -> int:
    """``python main.py preference get KEY``.

    Activation 12, Phase 3. Reads back from the same ``app.memory_store``
    ``_run_preference_set`` just wrote to, within the same running
    application -- no separate lookup path, no persistence across
    restarts. Since ``MemoryStore`` never dedupes by ``key`` (see
    ``_run_preference_set``), this scans ``memory_store.list()`` (already
    a fresh, insertion-ordered tuple per that method's own contract) for
    every ``PreferenceRecord`` matching ``key`` and reports the most
    recently added one.
    """
    if not argv:
        print("Usage: python main.py preference get KEY")
        return 1
    key = argv[0]
    matches = [
        record
        for record in app.memory_store.list()
        if isinstance(record, PreferenceRecord) and record.key == key
    ]
    if not matches:
        print(f"No preference set for '{key}'.")
        return 1
    print(f"{key} = {matches[-1].value}")
    return 0


def _run_preference_list(app) -> int:
    """``python main.py preference list``.

    Activation 12, Phase 3. Lists every ``PreferenceRecord`` currently in
    ``app.memory_store``, in insertion order, alongside any
    observation-derived ``MemoryRecord`` entries the same store may also
    hold (those are simply skipped here via the ``isinstance`` check --
    this command never touches or reports on them).
    """
    records = [
        record
        for record in app.memory_store.list()
        if isinstance(record, PreferenceRecord)
    ]
    if not records:
        print("No preferences set.")
        return 0
    print(f"Preferences ({len(records)}):")
    for record in records:
        print(f"  {record.key} = {record.value}")
    return 0


def _run_preference_command(app, argv: list[str]) -> int:
    """``python main.py preference <set|get|list> ...``.

    Activation 12, Phase 3. Dispatch shell mirroring
    ``_run_watchlist_command`` immediately above -- same argv-slicing
    style, same "print usage and return 1" behavior on missing/unknown
    input.
    """
    if not argv:
        print("Usage: python main.py preference <set|get|list> [KEY] [VALUE]")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "set":
        return _run_preference_set(app, rest)
    if subcommand == "get":
        return _run_preference_get(app, rest)
    if subcommand == "list":
        return _run_preference_list(app)
    print(f"Unknown preference subcommand: {subcommand!r} (expected 'set', 'get', or 'list')")
    return 1


def _run_strategy_note_add(app, argv: list[str]) -> int:
    """``python main.py strategy-note add TEXT...``.

    Activation 12 Memory -- Strategy Notes CLI. Joins every remaining
    argv token into one free-text note, stores it as a fresh
    :class:`~Orchestration.memory.StrategyNoteRecord` (``source="cli"``),
    added to the existing, unmodified ``app.memory_store`` -- the same
    ``MemoryStore`` instance the ApplicationGraph already built. No
    second store is constructed here, mirroring
    ``_run_preference_set`` immediately above.

    ``StrategyNoteRecord.__post_init__`` is the sole validator/
    normalizer for ``text`` (strips whitespace, rejects empty) -- this
    function does not duplicate that logic, it only catches the
    resulting ``MemoryError`` (imported here as ``PreferenceMemoryError``,
    the same exception type ``_run_preference_set`` already catches) and
    prints a clean one-line error instead of a raw traceback.
    """
    text = " ".join(argv).strip()
    try:
        record = StrategyNoteRecord(text=text, source="cli")
    except PreferenceMemoryError as exc:
        print(f"Invalid strategy note: {exc}")
        return 1
    app.memory_store.add(record)
    print(f"Strategy note added: {record.text}")
    return 0


def _run_strategy_note_list(app) -> int:
    """``python main.py strategy-note list``.

    Activation 12 Memory -- Strategy Notes CLI. Lists every
    ``StrategyNoteRecord`` currently in ``app.memory_store``, in the
    exact insertion order ``MemoryStore.list()`` returns (never
    reversed or sorted here) -- mirroring ``_run_preference_list``
    immediately above. Any other record kind the same store may also
    hold (``MemoryRecord``, ``PreferenceRecord``) is simply skipped via
    the ``isinstance`` check -- this command never touches or reports
    on them.
    """
    records = [
        record
        for record in app.memory_store.list()
        if isinstance(record, StrategyNoteRecord)
    ]
    print(f"Strategy Notes ({len(records)}):")
    for index, record in enumerate(records, start=1):
        print(f"  {index}. {record.text}")
    return 0


def _run_strategy_note_command(app, argv: list[str]) -> int:
    """``python main.py strategy-note <add|list> ...``.

    Activation 12 Memory -- Strategy Notes CLI. Dispatch shell
    mirroring ``_run_preference_command`` immediately above -- same
    argv-slicing style, same "print usage and return 1" behavior on
    missing/unknown input.
    """
    if not argv:
        print("Usage: python main.py strategy-note <add|list> [TEXT ...]")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "add":
        return _run_strategy_note_add(app, rest)
    if subcommand == "list":
        return _run_strategy_note_list(app)
    print(f"Unknown strategy-note subcommand: {subcommand!r} (expected 'add' or 'list')")
    return 1


def _run_previous_decision_add(app, argv: list[str]) -> int:
    """``python main.py previous-decision add DECISION RATIONALE...``.

    Activation 12 Memory -- Previous Decisions CLI. The first argv token
    is the ``decision``; every remaining token is joined with a single
    space into the free-text ``rationale``, exactly mirroring how
    ``_run_strategy_note_add`` joins its free-text ``text`` argv. Stores
    a fresh :class:`~Orchestration.memory.PreviousDecisionRecord`
    (``source="cli"``, ``reference_id=None``), added to the existing,
    unmodified ``app.memory_store`` -- the same ``MemoryStore`` instance
    the ApplicationGraph already built. No second store is constructed
    here, mirroring ``_run_strategy_note_add``/``_run_preference_set``
    immediately above.

    ``PreviousDecisionRecord.__post_init__`` is the sole validator/
    normalizer for ``decision`` and ``rationale`` (strips whitespace,
    rejects empty) -- this function does not duplicate that logic, it
    only catches the resulting ``MemoryError`` (imported here as
    ``PreferenceMemoryError``, the same exception type
    ``_run_strategy_note_add``/``_run_preference_set`` already catch)
    and prints a clean one-line error instead of a raw traceback.
    """
    if len(argv) < 2:
        print("Usage: python main.py previous-decision add DECISION RATIONALE...")
        return 1
    decision = argv[0]
    rationale = " ".join(argv[1:]).strip()
    try:
        record = PreviousDecisionRecord(
            decision=decision,
            rationale=rationale,
            source="cli",
            reference_id=None,
        )
    except PreferenceMemoryError as exc:
        print(f"Invalid previous decision: {exc}")
        return 1
    app.memory_store.add(record)
    print(f"Previous decision added: {record.decision} | {record.rationale}")
    return 0


def _run_previous_decision_list(app) -> int:
    """``python main.py previous-decision list``.

    Activation 12 Memory -- Previous Decisions CLI. Lists every
    ``PreviousDecisionRecord`` currently in ``app.memory_store``, in the
    exact insertion order ``MemoryStore.list()`` returns (never
    reversed or sorted here) -- mirroring ``_run_strategy_note_list``
    immediately above. Any other record kind the same store may also
    hold (``MemoryRecord``, ``PreferenceRecord``, ``StrategyNoteRecord``)
    is simply skipped via the ``isinstance`` check -- this command never
    touches or reports on them. Only fields actually present on
    ``PreviousDecisionRecord`` (``decision``, ``rationale``) are
    displayed -- no approval status, trade outcome, account state,
    performance, or order status is fabricated.
    """
    records = [
        record
        for record in app.memory_store.list()
        if isinstance(record, PreviousDecisionRecord)
    ]
    print(f"Previous Decisions ({len(records)}):")
    for index, record in enumerate(records, start=1):
        print(f"  {index}. decision={record.decision} | rationale={record.rationale}")
    return 0


def _run_previous_decision_command(app, argv: list[str]) -> int:
    """``python main.py previous-decision <add|list> ...``.

    Activation 12 Memory -- Previous Decisions CLI. Dispatch shell
    mirroring ``_run_strategy_note_command`` immediately above -- same
    argv-slicing style, same "print usage and return 1" behavior on
    missing/unknown input.
    """
    if not argv:
        print("Usage: python main.py previous-decision <add|list> [DECISION] [RATIONALE ...]")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "add":
        return _run_previous_decision_add(app, rest)
    if subcommand == "list":
        return _run_previous_decision_list(app)
    print(f"Unknown previous-decision subcommand: {subcommand!r} (expected 'add' or 'list')")
    return 1


def _run_lesson_add(app, argv: list[str]) -> int:
    """``python main.py lesson add TEXT...``.

    Activation 12 Memory -- Lessons From Failed Trades CLI. Joins every
    remaining argv token into one free-text lesson, stores it as a
    fresh :class:`~Orchestration.memory.LessonRecord` (``source="cli"``,
    ``reference_id=None``), added to the existing, unmodified
    ``app.memory_store`` -- the same ``MemoryStore`` instance the
    ApplicationGraph already built. No second store is constructed
    here, mirroring ``_run_strategy_note_add``/``_run_preference_set``
    immediately above.

    ``LessonRecord.__post_init__`` is the sole validator/normalizer for
    ``text`` (strips whitespace, rejects empty) -- this function does
    not duplicate that logic, it only catches the resulting
    ``MemoryError`` (imported here as ``PreferenceMemoryError``, the
    same exception type ``_run_strategy_note_add``/
    ``_run_preference_set`` already catch) and prints a clean one-line
    error instead of a raw traceback.

    This is a user-authored passive memory command only: it performs
    no database lookup, no automatic failed-trade classification, and
    no ``reference_id`` inference. The lesson is exactly the text the
    caller typed.
    """
    text = " ".join(argv).strip()
    try:
        record = LessonRecord(text=text, source="cli", reference_id=None)
    except PreferenceMemoryError as exc:
        print(f"Invalid lesson: {exc}")
        return 1
    app.memory_store.add(record)
    print(f"Lesson added: {record.text}")
    return 0


def _run_lesson_list(app) -> int:
    """``python main.py lesson list``.

    Activation 12 Memory -- Lessons From Failed Trades CLI. Lists every
    ``LessonRecord`` currently in ``app.memory_store``, in the exact
    insertion order ``MemoryStore.list()`` returns (never reversed or
    sorted here) -- mirroring ``_run_strategy_note_list``/
    ``_run_previous_decision_list`` immediately above. Any other record
    kind the same store may also hold (``MemoryRecord``,
    ``PreferenceRecord``, ``StrategyNoteRecord``,
    ``PreviousDecisionRecord``) is simply skipped via the ``isinstance``
    check -- this command never touches or reports on them. Only the
    field actually present on ``LessonRecord`` (``text``) is displayed
    -- no P/L, failure rate, order status, rejection reason, trade
    details, account state, or portfolio state is fabricated.
    """
    records = [
        record
        for record in app.memory_store.list()
        if isinstance(record, LessonRecord)
    ]
    print(f"Lessons ({len(records)}):")
    for index, record in enumerate(records, start=1):
        print(f"  {index}. {record.text}")
    return 0


def _run_lesson_command(app, argv: list[str]) -> int:
    """``python main.py lesson <add|list> ...``.

    Activation 12 Memory -- Lessons From Failed Trades CLI. Dispatch
    shell mirroring ``_run_strategy_note_command`` immediately above --
    same argv-slicing style, same "print usage and return 1" behavior
    on missing/unknown input.
    """
    if not argv:
        print("Usage: python main.py lesson <add|list> [TEXT ...]")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "add":
        return _run_lesson_add(app, rest)
    if subcommand == "list":
        return _run_lesson_list(app)
    print(f"Unknown lesson subcommand: {subcommand!r} (expected 'add' or 'list')")
    return 1


def _run_scan_command(app, argv: list[str]) -> int:
    """``python main.py scan --market idx``.

    ``--market`` is required and, for this Section 2.8 scope, only
    ``idx`` is a recognized value (this project's ``ManualScanService``
    pipeline has no other market's data source wired). Any other or
    missing ``--market`` value is rejected before the scan runs -- the
    real Sprint 5 pipeline is never invoked with an unsupported market.

    On a recognized ``--market idx``, runs the exact same production
    call ``_run_manual_scan()`` already uses
    (``app.manual_scan_service.run_scan(generated_at)``), then also
    prints the persisted per-ticker snapshot rows (including any
    ``DATA_ERROR`` ticker) via ``_print_scan_snapshot_rows``.
    """
    market = None
    i = 0
    while i < len(argv):
        if argv[i] == "--market" and i + 1 < len(argv):
            market = argv[i + 1]
            i += 2
        else:
            i += 1

    if market is None:
        print("Usage: python main.py scan --market idx|us|forex")
        return 1
    normalized_market = market.lower()
    if normalized_market not in ("idx", "us", "forex"):
        print(f"Unsupported market: {market!r} (supported: 'idx', 'us', 'forex')")
        return 1

    # Activation 9.2: previously ``--market`` was validated but never
    # actually applied -- the scan always ran under whatever
    # ``AIOS_MARKET`` happened to already be set to in the process
    # environment (defaulting to "idx"), so ``scan --market us`` and
    # ``scan --market idx`` produced identical provider-symbol
    # resolution (Core.market_config.resolve_provider_symbol, read by
    # Orchestration.market_price_tool/market_fundamental_tool/
    # market_news_tool). Setting it here, for the duration of this
    # one scan call only, is the actual wiring: a US scan now resolves
    # bare tickers (no ".JK" suffix) the same way ``resolve_
    # provider_symbol`` already does for AIOS_MARKET=us. Restored in
    # ``finally`` so this command never leaves a process-wide side
    # effect behind for whatever runs next -- IDX's own
    # ``scan --market idx`` behavior is unchanged (still resolves to
    # the "idx" branch, same as when this variable was never touched).
    previous_market = os.environ.get("AIOS_MARKET")
    os.environ["AIOS_MARKET"] = normalized_market
    try:
        generated_at = datetime.now(timezone.utc).isoformat()
        report = app.manual_scan_service.run_scan(generated_at)
        _print_manual_scan_report(report)
        _print_scan_snapshot_rows(app, generated_at)
    finally:
        if previous_market is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market
    return 0


def _run_backup_command(argv: list[str]) -> int:
    """``python main.py backup`` (Activation 7 FIX blocker 3).

    Manual database backup, LOCKED SCOPE: this is the sole entry
    point this fix adds -- no scheduler, no automatic trigger from
    any other command. Running this command IS the manual backup
    action; there is no other way this fix causes a backup to be
    created.

    Reads the database path from the exact same ``DatabaseConfig.
    from_env()`` every other command already uses (``DB_PATH`` env
    var, same default), so the backup always targets the live,
    already-configured database -- never a second, independently
    guessed path. Does not require ``build_application()`` (no
    business-layer dependency of any kind), mirroring how ``doctor``/
    ``init`` are dispatched before that call -- this command must be
    runnable even when the rest of the environment (provider
    credentials, etc.) is not ready.

    Delegates all actual copying to ``Database.backup.create_backup()``
    (SQLite's own online backup API -- see that module's docstring for
    why), then immediately runs ``Database.backup.verify_backup()`` on
    the result so a failed/corrupt backup is never reported as a
    success. Prints a clean, labelled outcome either way -- no raw
    traceback -- and returns a non-zero status on failure.
    """
    if argv:
        print(f"Unknown backup argument(s): {argv!r} (usage: python main.py backup)")
        return 1

    db_config = DatabaseConfig.from_env()
    try:
        backup_path = create_backup(db_config.db_path)
    except Exception as exc:
        print("BACKUP FAILED: could not create a database backup.")
        print(f"  - {exc}")
        logger.error(
            "Manual database backup failed for db_path=%s -- source database "
            "was not modified.",
            db_config.db_path,
            exc_info=True,
        )
        return 1

    if not verify_backup(backup_path):
        print("BACKUP FAILED: backup file was created but failed verification (not a valid SQLite database).")
        print(f"  - {backup_path}")
        logger.error(
            "Manual database backup for db_path=%s produced an unverifiable file at %s.",
            db_config.db_path,
            backup_path,
        )
        return 1

    print("Backup Created")
    print(f"  source : {db_config.db_path}")
    print(f"  backup : {backup_path}")
    print("  verified: OK (PRAGMA integrity_check passed)")
    return 0


def _print_daily_report_event(event: NotificationEvent) -> None:
    """Print the sent ``NotificationEvent`` returned by
    ``DailyReportOrchestrator.run_daily_report()`` (Activation 6.4).

    Purely display logic -- prints the event's own already-built
    fields (LOCKED, ``NotificationBuilder.build_daily_report()``),
    computing nothing new.
    """
    print("Daily Report Sent")
    print()
    print(event.message)


def _run_report_daily(app, account_id: str) -> int:
    """``python main.py report daily`` (Activation 6.4; Activation 7
    FIX blocker 2: clean failure handling on a Telegram
    credential/network failure).

    Does exactly two things, in exactly this order:

        1. ``generated_at`` is created here, at the moment this
           command runs (mirrors ``_run_manual_scan()``'s own
           ``generated_at`` contract -- ``DailyReportOrchestrator``
           never generates its own timestamp).
        2. ``app.daily_report_orchestrator.run_daily_report(account_id,
           generated_at)`` -- the one and only call into the
           Activation 6.4 pipeline (never
           ``ManualScanService``/``PerformanceSummaryProductionService``/
           ``NotificationBuilder``/``NotificationManager`` directly).

    Also serves as this command's own retry: running
    ``python main.py report daily`` again re-runs the exact same
    pipeline from a fresh scan.

    Failure handling (Activation 7 FIX blocker 2): reuses the exact
    catch-log-print-non-zero pattern already established by
    ``_run_post_trade_snapshot_and_reconciliation()`` for the CLI
    boundary -- this is the one place a raised exception is turned
    into something the caller can observe cleanly, never inside
    ``DailyReportOrchestrator`` itself (its own "no try/except"
    contract, LOCKED, is untouched). ``run_daily_report()`` can fail
    for real -- most commonly a Telegram credential/network failure
    surfacing as ``NotificationManager.notify()`` raising -- and by
    the time that happens, ``ManualScanService.run_scan()`` has
    already committed real scan-snapshot rows. This function never
    attempts to undo that already-committed state; it only prevents a
    raw traceback from reaching the operator. Any exception is caught
    here, logged with a full traceback via ``logger.error(...,
    exc_info=True)`` (so nothing is silently dropped), and reported to
    the caller as a clean, labelled failure message plus a non-zero
    return code -- mirroring the reconciliation-failure branch of
    ``_run_post_trade_snapshot_and_reconciliation()`` exactly.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        event = app.daily_report_orchestrator.run_daily_report(account_id, generated_at)
    except Exception as exc:
        print("DAILY REPORT FAILED: could not complete the daily report/notification pipeline.")
        print(f"  - {exc}")
        logger.error(
            "Daily report failed for account_id=%s -- any prior step's "
            "already-committed state (e.g. scan snapshots) remains "
            "committed; nothing is rolled back.",
            account_id,
            exc_info=True,
        )
        return 1
    _print_daily_report_event(event)
    return 0


def _print_performance_summary(performance) -> None:
    """Print every field of a real ``PerformanceSummary`` (Sprint 6 STEP 7 /
    Activation 5.5) -- Activation 7 roadmap item: "Strategy validation"
    lists ``net expectancy setelah fee``, ``profit factor``, ``maximum
    drawdown``, ``win rate``, ``average win``, and ``average loss`` as
    minimum validation dimensions, and the Live Readiness Gate itself
    hard-stops on "negative expectancy setelah biaya". Every one of
    those six engines was already built and wired
    (``PerformanceSummaryProductionService``, already on
    ``ApplicationGraph``) but, before this command, none of their
    output beyond ``win_rate``/``maximum_drawdown`` was ever printed
    anywhere -- an operator had no way to actually see the numbers the
    gate is supposed to be checked against.

    Purely display logic -- prints ``performance``'s own already-
    computed fields verbatim, computes nothing new, and recomputes no
    formula. Read-only, same as ``_print_account``/``_print_orders``.
    """
    trade_statistics = performance.trade_statistics
    position_statistics = performance.position_statistics

    print("Performance Summary")
    print()
    print("Trade statistics:")
    print(f"  total_trades     : {trade_statistics.total_trades}")
    print(f"  buy_trades       : {trade_statistics.buy_trades}")
    print(f"  sell_trades      : {trade_statistics.sell_trades}")
    print(f"  total_volume     : {trade_statistics.total_volume}")
    print(f"  total_fees       : {trade_statistics.total_fees}")
    print(f"  total_tax        : {trade_statistics.total_tax}")
    print(f"  first_trade_time : {trade_statistics.first_trade_time}")
    print(f"  last_trade_time  : {trade_statistics.last_trade_time}")
    print()
    print("Position statistics:")
    print(f"  winning_positions  : {position_statistics.winning_positions}")
    print(f"  losing_positions   : {position_statistics.losing_positions}")
    print(f"  breakeven_positions: {position_statistics.breakeven_positions}")
    print(f"  gross_profit       : {position_statistics.gross_profit}")
    print(f"  gross_loss         : {position_statistics.gross_loss}")
    print(f"  net_profit         : {position_statistics.net_profit}")
    print(f"  average_win        : {position_statistics.average_win}")
    print(f"  average_loss       : {position_statistics.average_loss}")
    print()
    print(f"Win rate          : {performance.win_rate:.2%}")
    print(f"Expectancy        : {performance.expectancy.expectancy}")
    print(f"Profit factor     : {performance.profit_factor.profit_factor}")
    print(f"Maximum drawdown  : {performance.maximum_drawdown.maximum_drawdown:.2%}")


def _run_report_performance(app, account_id: str) -> int:
    """``python main.py report performance`` (Activation 7 roadmap item:
    Strategy validation dimensions).

    Read-only. Calls the existing, unmodified
    ``PerformanceSummaryProductionService.get_performance_summary()``
    (Activation 5.5, already wired on ``ApplicationGraph``) for
    ``account_id`` and prints the result via
    ``_print_performance_summary``. No new engine, no new formula, no
    new repository call -- purely an additive display command over an
    already-real, already-computed summary, mirroring the
    ``ValidationError``-catch pattern already used by
    ``_run_paper_buy_command``/``_run_paper_sell_command`` for an
    unknown account.
    """
    try:
        performance = app.performance_summary_production_service.get_performance_summary(
            account_id
        )
    except ValidationError as exc:
        print(f"Cannot build performance summary: {exc.message}")
        return 1
    _print_performance_summary(performance)
    return 0


def _print_evidence_report(
    app,
    account_id: str,
    attributions,
    strategy_performance,
    execution_rate,
    regime_performance=None,
    market_condition_variety=None,
) -> None:
    """Purely display logic for ``report evidence`` (Activation 7
    CLOSEOUT). Prints already-computed fields verbatim -- no new
    formula, no threshold, no pass/fail verdict. Mirrors
    ``_print_performance_summary``'s read-only-display convention.
    """
    print(f"Activation 7 Evidence Report -- account_id={account_id}")
    print()

    print(f"Execution rate (order-level, platform-wide, all accounts):")
    print(f"  resolved_total           : {execution_rate.resolved_total}")
    print(f"  filled_orders            : {execution_rate.filled_orders}")
    print(f"  partially_filled_orders  : {execution_rate.partially_filled_orders}")
    print(f"  non_executed_orders      : {execution_rate.non_executed_orders}")
    print(f"  execution_rate           : {execution_rate.execution_rate:.2%}")
    print()

    print(f"Trade attribution ({len(attributions)} trade(s) for {account_id}):")
    if not attributions:
        print("  No trades yet.")
    for attribution in attributions:
        holding = (
            f"{attribution.holding_period_seconds:.0f}s"
            if attribution.holding_period_seconds is not None
            else "open (not yet closed)"
        )
        print(
            f"  trade_id={attribution.trade_id}  symbol={attribution.symbol}  "
            f"action={attribution.action}  strategy={attribution.strategy}  "
            f"market={attribution.market}  risk_category={attribution.risk_category}  "
            f"holding_period={holding}"
        )
    print()

    print(f"Performance per strategy ({len(strategy_performance)} strategy label(s), closed episodes only):")
    if not strategy_performance:
        print("  No closed position episodes yet.")
    for strategy, statistics in strategy_performance.items():
        print(
            f"  {strategy}: closed_episodes={statistics.closed_episodes}  "
            f"winning={statistics.winning_episodes}  losing={statistics.losing_episodes}  "
            f"breakeven={statistics.breakeven_episodes}  net_profit={statistics.net_profit}  "
            f"average_win={statistics.average_win}  average_loss={statistics.average_loss}"
        )
    print()

    if regime_performance is not None:
        print(
            f"Performance per market regime ({len(regime_performance)} regime label(s), "
            "closed episodes only):"
        )
        if not regime_performance:
            print("  No closed position episodes yet.")
        for regime, statistics in regime_performance.items():
            print(
                f"  {regime}: closed_episodes={statistics.closed_episodes}  "
                f"winning={statistics.winning_episodes}  losing={statistics.losing_episodes}  "
                f"breakeven={statistics.breakeven_episodes}  net_profit={statistics.net_profit}  "
                f"average_win={statistics.average_win}  average_loss={statistics.average_loss}"
            )
        print(
            "  Note: a regime of 'insufficient_data' means real OHLCV history was not "
            "sufficient to classify that episode's opening moment -- not a fabricated "
            "regime label."
        )
        print()

    if market_condition_variety is not None:
        print("Market-condition variety (real, currently-observed, from the live watchlist):")
        print(f"  observed_regimes          : {market_condition_variety['observed_regimes']}")
        print(f"  regime_count              : {market_condition_variety['regime_count']}")
        print(f"  symbols_classified        : {market_condition_variety['symbols_classified']}")
        print(
            "  symbols_insufficient_data : "
            f"{market_condition_variety['symbols_insufficient_data']}"
        )
        for symbol, regime in market_condition_variety["per_symbol"].items():
            print(f"    {symbol}: {regime}")


def _run_report_evidence(app, account_id: str) -> int:
    """``python main.py report evidence [account_id]`` (Activation 7
    CLOSEOUT).

    Read-only. Wires three already-built, already-LOCKED, already
    ``ApplicationGraph``-wired production services/engines --
    ``app.execution_rate_engine`` (Activation 7, order-level execution
    rate), ``app.trade_attribution_service`` (Activation 5.6, per-trade
    strategy/market/holding-period attribution), and
    ``app.strategy_performance_service`` (Activation 7,
    performance-per-strategy over closed episodes) -- none of which had
    any CLI/production entry point before this command, exactly the
    same gap ``report performance`` (Activation 7 roadmap item) closed
    for ``PerformanceSummaryProductionService`` earlier. No new engine,
    no new formula, no new repository call -- purely an additive
    display command over already-real, already-computed results.
    """
    try:
        attributions = app.trade_attribution_service.get_attribution(account_id)
        strategy_performance = app.strategy_performance_service.get_performance_by_strategy(
            account_id
        )
        regime_performance = app.market_regime_attribution_service.get_performance_by_regime(
            account_id
        )
    except ValidationError as exc:
        print(f"Cannot build evidence report: {exc.message}")
        return 1
    execution_rate = app.execution_rate_engine.calculate()
    market_condition_variety = app.market_regime_attribution_service.get_market_condition_variety()
    _print_evidence_report(
        app,
        account_id,
        attributions,
        strategy_performance,
        execution_rate,
        regime_performance=regime_performance,
        market_condition_variety=market_condition_variety,
    )
    return 0


def _print_paper_review_report(result) -> None:
    """Purely display logic for ``report paper-review`` (Phase G Task
    5). Prints every field of the already-computed, already-frozen
    ``Services.paper_review_service.PaperReviewResult`` verbatim --
    no new formula, no threshold, no recalculated metric. Mirrors
    ``_print_performance_summary``/``_print_evidence_report``'s
    read-only-display convention exactly.

    ``NOT_AVAILABLE`` (collaborator never injected) and
    ``INSUFFICIENT_DATA`` (collaborator injected, but the underlying
    persisted data does not exist yet) are both printed exactly as
    the service reports them -- never silently dropped, never
    translated into a fabricated number.
    """
    print(f"Paper Review -- account_id={result.account_id}")
    print(f"  generated_at : {result.generated_at}")
    print(f"  period       : since={result.period_since!r}  until={result.period_until!r}")
    print()

    print("Decision counts:")
    print(f"  total_reviewed_decisions : {result.total_reviewed_decisions}")
    print(f"  TAKE                     : {result.take_count}")
    print(f"  SKIP                     : {result.skip_count}")
    print(f"  WAIT                     : {result.wait_count}")
    print()

    print("Execution linkage:")
    print(f"  approved_paper_count : {result.approved_paper_count}")
    print(f"  linked_order_count   : {result.linked_order_count}")
    print(f"  linked_trade_count   : {result.linked_trade_count}")
    print()

    print("Strategy breakdown:")
    if isinstance(result.strategy_breakdown, str):
        print(f"  {result.strategy_breakdown}")
    elif not result.strategy_breakdown:
        print("  (real empty dict -- zero closed episodes)")
    else:
        for strategy, statistics in result.strategy_breakdown.items():
            print(
                f"  {strategy}: closed_episodes={statistics.closed_episodes}  "
                f"winning={statistics.winning_episodes}  losing={statistics.losing_episodes}  "
                f"breakeven={statistics.breakeven_episodes}  net_profit={statistics.net_profit}  "
                f"average_win={statistics.average_win}  average_loss={statistics.average_loss}"
            )
    print()

    print("Market-regime breakdown:")
    if isinstance(result.market_regime_breakdown, str):
        print(f"  {result.market_regime_breakdown}")
    elif not result.market_regime_breakdown:
        print("  (real empty dict -- zero closed episodes)")
    else:
        for regime, statistics in result.market_regime_breakdown.items():
            print(
                f"  {regime}: closed_episodes={statistics.closed_episodes}  "
                f"winning={statistics.winning_episodes}  losing={statistics.losing_episodes}  "
                f"breakeven={statistics.breakeven_episodes}  net_profit={statistics.net_profit}  "
                f"average_win={statistics.average_win}  average_loss={statistics.average_loss}"
            )
    print()

    print("Adherence summary:")
    for label, count in result.adherence_summary.items():
        print(f"  {label:<14}: {count}")
    print()

    vf = result.valuation_freshness
    print("Valuation freshness (PortfolioSnapshot.valuation_status):")
    print(f"  status      : {vf.status}")
    print(f"  fresh       : {vf.fresh}")
    print(f"  stale       : {vf.stale}")
    print(f"  unavailable : {vf.unavailable}")
    print()

    print(f"Decision traces ({len(result.decision_traces)}):")
    if not result.decision_traces:
        print("  No reviewed decisions in this period.")
    for trace in result.decision_traces:
        outcome = trace.outcome_status if trace.outcome_status is not None else "NOT_AVAILABLE"
        order_id = trace.order_id if trace.order_id is not None else "NOT_AVAILABLE"
        trade_id = trace.trade_id if trace.trade_id is not None else "NOT_AVAILABLE"
        print(
            f"  entry_id={trace.entry_id}  brief_id={trace.brief_id}  symbol={trace.symbol}  "
            f"decision={trace.decision}  decided_at={trace.decided_at}"
        )
        print(
            f"    risk_policy_status={trace.risk_policy_status}  outcome_status={outcome}  "
            f"approved_paper={trace.approved_paper}  order_id={order_id}  trade_id={trade_id}  "
            f"adherence={trace.adherence}"
        )


def _run_report_paper_review(
    app,
    account_id: str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> int:
    """``python main.py report paper-review [account_id] [since] [until]``
    (Phase G Task 5).

    Read-only. Calls the existing, unmodified
    ``Services.paper_review_service.PaperReviewService.review()``
    (Phase G Task 4, wired onto ``ApplicationGraph`` in
    ``Core.composition_root`` for this task only) for ``account_id``
    and prints the resulting ``PaperReviewResult`` via
    ``_print_paper_review_report``. No new engine, no new formula, no
    new repository call, no order/trade is ever created by this
    command -- purely an additive display command over an
    already-real, already-computed review, mirroring the
    ``ValidationError``-catch pattern already used by
    ``_run_report_performance``/``_run_report_evidence`` for an
    unknown account.
    """
    try:
        result = app.paper_review_service.review(account_id, since=since, until=until)
    except ValidationError as exc:
        print(f"Cannot build paper review: {exc.message}")
        return 1
    _print_paper_review_report(result)
    return 0


def _run_report_sustained_use(
    app,
    *,
    account_id: Optional[str] = None,
    window_id: Optional[int] = None,
) -> int:
    """``python main.py report sustained-use [account_id] [window_id]``
    (Phase H Task 3, "Sustained-Use Review Report").

    Read-only, two steps, both against already-complete, LOCKED
    components:

        1. ``app.sustained_use_review_service.generate_review(
           window_id=window_id, account_id=account_id)`` (Phase H Task
           2, unmodified) -- builds the real
           ``SustainedUseReviewResult`` evidence snapshot for the
           requested window (or the currently ``ACTIVE`` one when
           ``window_id`` is omitted).
        2. ``app.sustained_use_report_service.build_report(result)``
           (Phase H Task 3, this task's only new service) -- turns
           that result into a durable, human-readable text report,
           printed verbatim below.

    Neither step ever creates an order, a trade, a journal entry, or
    an ``ObservationWindow``, and neither ever makes a CONTINUE/
    SIMPLIFY/AUTHORIZE-FUTURE-BROKER-INVESTIGATION decision -- that
    decision remains a separate, future, human step outside this
    command's scope. Mirrors the ``ValidationError``-catch pattern
    already used by ``_run_report_paper_review``/
    ``_run_report_performance`` for an unknown account or window.
    """
    try:
        result = app.sustained_use_review_service.generate_review(
            window_id=window_id, account_id=account_id
        )
    except ValidationError as exc:
        print(f"Cannot build sustained-use review report: {exc.message}")
        return 1
    report = app.sustained_use_report_service.build_report(result)
    print(report.text)
    return 0


def _print_final_review_record(record) -> None:
    """Display a ``FinalReviewRecord`` (Phase H Task 4). Read-only:
    displays exactly what ``SustainedUseFinalReviewService`` persisted
    -- never computes, infers, or fabricates a decision."""
    print(f"Final Review Record #{record.review_id} (window #{record.observation_window_id})")
    print()
    print(f"Reviewed At           : {record.reviewed_at}")
    print(f"Evidence Status       : {record.evidence_status}")
    print(f"Known Limitations     : {record.known_limitations}")
    print(f"Operator Feedback IDs : {record.operator_feedback_ids}")
    print(f"Human Decision        : {record.human_decision}")
    if record.decision_note:
        print(f"Decision Note         : {record.decision_note}")
    if record.decided_at:
        print(f"Decided At            : {record.decided_at}")
    if record.decided_by:
        print(f"Decided By            : {record.decided_by}")
    print(f"Created At            : {record.created_at}")
    print(f"Updated At            : {record.updated_at}")


def _run_report_sustained_use_final(app, *, window_id: Optional[int] = None) -> int:
    """``python main.py report sustained-use-final [window_id]``
    (Phase H Task 4, "Operator Feedback + Final Review Record").

    Purely read-only from the operator's perspective: refreshes the
    resolved window's ``FinalReviewRecord`` evidence-derived columns
    from real, current evidence (``SustainedUseFinalReviewService.
    refresh_review`` -- the only writes this performs land on the new
    ``final_review_records``/``operator_feedback`` bookkeeping tables,
    never on any trading/risk table), then prints it. Never sets or
    changes ``human_decision`` -- that only ever happens via the
    separate, explicit ``sustained-use-final decide`` command below.
    """
    try:
        record = app.sustained_use_final_review_service.refresh_review(window_id=window_id)
    except ValidationError as exc:
        print(f"Cannot build final review record: {exc.message}")
        return 1
    _print_final_review_record(record)
    return 0


def _parse_sustained_use_final_feedback_args(
    argv: list[str],
) -> tuple[Optional[dict], Optional[str]]:
    """Parse ``sustained-use-final feedback`` flags (Phase H Task 4).

    Mirrors ``_parse_observation_window_open_args``'s own flag-parsing
    style. ``--window-id`` is optional (omitted -> the single
    currently ``ACTIVE`` window, resolved by
    ``SustainedUseFinalReviewService.record_feedback`` itself). Every
    other flag is optional too -- an operator may only have time to
    fill in one field on a given day; nothing here is required or
    defaulted to a guessed value.

    ``--concern`` may be repeated to build up the ``concerns`` list
    (e.g. ``--concern too_many_alerts --concern stale_data``).

    Returns:
        ``(parsed_dict_or_None, error_message_or_None)``.
    """
    flags = {
        "--window-id": None,
        "--rating": None,
        "--alert-usefulness": None,
        "--data-reliability": None,
        "--decision-quality": None,
        "--workflow-usability": None,
        "--free-text": None,
        "--operator-label": None,
    }
    concerns: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--concern" and i + 1 < len(argv):
            concerns.append(argv[i + 1])
            i += 2
            continue
        if token in flags and i + 1 < len(argv):
            flags[token] = argv[i + 1]
            i += 2
            continue
        i += 1

    window_id: Optional[int] = None
    if flags["--window-id"] is not None:
        try:
            window_id = int(flags["--window-id"])
        except ValueError:
            return None, f"--window-id must be an integer, got {flags['--window-id']!r}."

    rating: Optional[int] = None
    if flags["--rating"] is not None:
        try:
            rating = int(flags["--rating"])
        except ValueError:
            return None, f"--rating must be an integer, got {flags['--rating']!r}."

    return (
        {
            "window_id": window_id,
            "operator_rating": rating,
            "alert_usefulness": flags["--alert-usefulness"],
            "data_reliability_feedback": flags["--data-reliability"],
            "decision_quality_feedback": flags["--decision-quality"],
            "workflow_usability_feedback": flags["--workflow-usability"],
            "free_text": flags["--free-text"],
            "concerns": concerns or None,
            "operator_label": flags["--operator-label"],
        },
        None,
    )


def _print_operator_feedback(feedback) -> None:
    """Display an ``OperatorFeedback`` row (Phase H Task 4). Read-only:
    displays exactly what ``SustainedUseFinalReviewService`` persisted
    -- never computes, infers, or fabricates a rating/label.
    """
    print(
        f"Operator Feedback #{feedback.feedback_id} "
        f"(window #{feedback.observation_window_id})"
    )
    print()
    print(f"Recorded At               : {feedback.recorded_at}")
    if feedback.operator_rating is not None:
        print(f"Operator Rating           : {feedback.operator_rating}")
    if feedback.alert_usefulness:
        print(f"Alert Usefulness          : {feedback.alert_usefulness}")
    if feedback.data_reliability_feedback:
        print(f"Data Reliability Feedback : {feedback.data_reliability_feedback}")
    if feedback.decision_quality_feedback:
        print(f"Decision Quality Feedback : {feedback.decision_quality_feedback}")
    if feedback.workflow_usability_feedback:
        print(f"Workflow Usability        : {feedback.workflow_usability_feedback}")
    if feedback.free_text:
        print(f"Free Text                 : {feedback.free_text}")
    print(f"Concerns                  : {feedback.concerns}")
    if feedback.operator_label:
        print(f"Operator Label            : {feedback.operator_label}")


def _run_sustained_use_final_feedback_command(app, argv: list[str]) -> int:
    """``python main.py sustained-use-final feedback [--window-id ID]
    [--rating N] [--alert-usefulness "..."] [--data-reliability "..."]
    [--decision-quality "..."] [--workflow-usability "..."]
    [--free-text "..."] [--concern LABEL ...] [--operator-label "..."]``
    (Phase H Task 4, "Operator Feedback + Final Review Record").

    Records exactly one real, explicitly-given piece of operator
    feedback via ``SustainedUseFinalReviewService.record_feedback`` --
    every field is optional and stored verbatim, nothing is inferred.
    This also refreshes the window's ``FinalReviewRecord`` evidence-
    derived columns (never ``human_decision``) so its linked-feedback
    list stays current. Writes land only on the ``operator_feedback``/
    ``final_review_records`` bookkeeping tables -- never a trading,
    risk-limit, or permission table.
    """
    parsed, error = _parse_sustained_use_final_feedback_args(argv)
    if error:
        print(error)
        print(
            "Usage: python main.py sustained-use-final feedback [--window-id ID] "
            "[--rating N] [--alert-usefulness TEXT] [--data-reliability TEXT] "
            "[--decision-quality TEXT] [--workflow-usability TEXT] "
            "[--free-text TEXT] [--concern LABEL ...] [--operator-label TEXT]"
        )
        return 1

    try:
        feedback = app.sustained_use_final_review_service.record_feedback(**parsed)
    except ValidationError as exc:
        print(f"Cannot record operator feedback: {exc.message}")
        return 1

    _print_operator_feedback(feedback)
    return 0


def _parse_sustained_use_final_decide_args(
    argv: list[str],
) -> tuple[Optional[dict], Optional[str]]:
    """Parse ``sustained-use-final decide`` flags (Phase H Task 4).

    Mirrors ``_parse_sustained_use_final_feedback_args``'s own
    flag-parsing style. ``--decision`` is the only required flag --
    this command never infers, defaults, or recommends a decision;
    the caller must supply one of ``PENDING``/``CONTINUE``/
    ``SIMPLIFY``/``AUTHORIZE_FUTURE_INVESTIGATION`` explicitly every
    time (validated again, by exact value, inside
    ``SustainedUseFinalReviewService.record_decision``).

    Returns:
        ``(parsed_dict_or_None, error_message_or_None)``.
    """
    flags = {
        "--decision": None,
        "--window-id": None,
        "--note": None,
        "--decided-by": None,
    }
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in flags and i + 1 < len(argv):
            flags[token] = argv[i + 1]
            i += 2
            continue
        i += 1

    if flags["--decision"] is None:
        return None, "Missing required flag: --decision."

    window_id: Optional[int] = None
    if flags["--window-id"] is not None:
        try:
            window_id = int(flags["--window-id"])
        except ValueError:
            return None, f"--window-id must be an integer, got {flags['--window-id']!r}."

    return (
        {
            "human_decision": flags["--decision"],
            "window_id": window_id,
            "decision_note": flags["--note"],
            "decided_by": flags["--decided-by"],
        },
        None,
    )


def _run_sustained_use_final_decide_command(app, argv: list[str]) -> int:
    """``python main.py sustained-use-final decide --decision
    <PENDING|CONTINUE|SIMPLIFY|AUTHORIZE_FUTURE_INVESTIGATION>
    [--window-id ID] [--note "..."] [--decided-by "..."]`` (Phase H
    Task 4, "Operator Feedback + Final Review Record").

    Records ONE explicit, human-supplied decision via
    ``SustainedUseFinalReviewService.record_decision``. ``--decision``
    has no default -- the operator must type the exact value every
    time; this command never infers, scores, or recommends a
    decision, and never calls an LLM/provider of any kind. Rejected
    with a non-zero exit code (and the service's own explanation
    printed verbatim) when the resolved window's real evidence is
    insufficient for a non-PENDING decision -- see
    ``SustainedUseFinalReviewService`` module docstring for the exact,
    derived-not-fabricated gate. Writes land only on the
    ``final_review_records`` bookkeeping table -- never a trading,
    risk-limit, or permission table; no order/position/account
    repository is reachable from this command.
    """
    parsed, error = _parse_sustained_use_final_decide_args(argv)
    if error:
        print(error)
        print(
            "Usage: python main.py sustained-use-final decide --decision "
            "<PENDING|CONTINUE|SIMPLIFY|AUTHORIZE_FUTURE_INVESTIGATION> "
            "[--window-id ID] [--note TEXT] [--decided-by TEXT]"
        )
        return 1

    try:
        record = app.sustained_use_final_review_service.record_decision(**parsed)
    except ValidationError as exc:
        print(f"Cannot record final decision: {exc.message}")
        return 1

    _print_final_review_record(record)
    return 0


def _run_sustained_use_final_command(app, argv: list[str]) -> int:
    """``python main.py sustained-use-final <feedback|decide> ...``
    dispatch (Phase H Task 4, "Operator Feedback + Final Review
    Record").

    Two explicit subcommands only, both against the already-complete,
    LOCKED ``SustainedUseFinalReviewService``:

        * ``feedback`` -- records one real, explicitly-given piece of
          operator feedback (:func:`_run_sustained_use_final_feedback_command`).
        * ``decide`` -- records one explicit, human-supplied final
          decision (:func:`_run_sustained_use_final_decide_command`).

    Read-only viewing of the current ``FinalReviewRecord`` remains
    ``python main.py report sustained-use-final`` (unchanged, Phase H
    Task 4's original read-only surface) -- this command never
    duplicates that. Neither subcommand here ever creates an order,
    a trade, a journal entry, or changes a risk limit or permission;
    both write exclusively to the ``operator_feedback``/
    ``final_review_records`` bookkeeping tables.
    """
    if not argv:
        print("Usage: python main.py sustained-use-final <feedback|decide> ...")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "feedback":
        return _run_sustained_use_final_feedback_command(app, rest)
    if subcommand == "decide":
        return _run_sustained_use_final_decide_command(app, rest)
    print(
        f"Unknown sustained-use-final subcommand: {subcommand!r} "
        "(expected 'feedback' or 'decide')"
    )
    return 1


def _run_report_command(app, argv: list[str]) -> int:
    """``python main.py report <daily|performance>`` (Activation 6.4;
    Activation 7 roadmap: adds the ``performance`` subcommand).

    ``daily`` wires exactly one pipeline
    (``ManualScanService.run_scan()`` ->
    ``PerformanceSummaryProductionService.get_performance_summary()``
    -> ``NotificationBuilder.build_daily_report()`` ->
    ``NotificationManager.notify()``), for the single default paper
    account (``DEFAULT_PAPER_ACCOUNT_ID``, the same account every
    other one-shot CLI command in this module already reads/writes).
    ``daily``'s own pipeline and ``NotificationBuilder.
    build_daily_report()``'s LOCKED message/metadata contract are
    untouched by the addition below.

    ``performance`` calls only
    ``PerformanceSummaryProductionService.get_performance_summary()``
    directly (no scan, no notification) and prints every field of the
    resulting ``PerformanceSummary`` -- see ``_run_report_performance``.
    """
    if not argv:
        print(
            "Usage: python main.py report "
            "<daily|performance|evidence|paper-review|sustained-use|sustained-use-final> "
            "[account_id] [since|window_id] [until]"
        )
        return 1
    subcommand = argv[0]
    if subcommand == "daily":
        return _run_report_daily(app, DEFAULT_PAPER_ACCOUNT_ID)
    if subcommand == "performance":
        account_id = argv[1] if len(argv) > 1 else DEFAULT_PAPER_ACCOUNT_ID
        return _run_report_performance(app, account_id)
    if subcommand == "evidence":
        account_id = argv[1] if len(argv) > 1 else DEFAULT_PAPER_ACCOUNT_ID
        return _run_report_evidence(app, account_id)
    if subcommand == "paper-review":
        # Phase G Task 5: python main.py report paper-review
        #   [account_id] [since] [until]
        # account_id defaults to DEFAULT_PAPER_ACCOUNT_ID, same
        # convention as "performance"/"evidence" above. since/until
        # are optional, already-supported PaperReviewService.review()
        # filters (inclusive ISO-8601 lower bound / exclusive upper
        # bound on JournalEntry.decided_at) -- no new query language.
        account_id = argv[1] if len(argv) > 1 else DEFAULT_PAPER_ACCOUNT_ID
        since = argv[2] if len(argv) > 2 else None
        until = argv[3] if len(argv) > 3 else None
        return _run_report_paper_review(app, account_id, since=since, until=until)
    if subcommand == "sustained-use":
        # Phase H Task 3: python main.py report sustained-use
        #   [account_id] [window_id]
        # account_id defaults to DEFAULT_PAPER_ACCOUNT_ID, same
        # convention as "performance"/"evidence"/"paper-review" above.
        # window_id is optional and, when omitted, resolves to the
        # single currently ACTIVE ObservationWindow -- the same
        # explicit-only selection rule
        # SustainedUseReviewService._resolve_window() already
        # enforces; no new query language is introduced here.
        account_id = argv[1] if len(argv) > 1 else DEFAULT_PAPER_ACCOUNT_ID
        window_id = int(argv[2]) if len(argv) > 2 else None
        return _run_report_sustained_use(app, account_id=account_id, window_id=window_id)
    if subcommand == "sustained-use-final":
        # Phase H Task 4: python main.py report sustained-use-final [window_id]
        # window_id is optional and, when omitted, resolves to the
        # single currently ACTIVE ObservationWindow -- same rule as
        # "sustained-use" above.
        window_id = int(argv[1]) if len(argv) > 1 else None
        return _run_report_sustained_use_final(app, window_id=window_id)
    print(
        f"Unknown report subcommand: {subcommand!r} "
        "(expected 'daily', 'performance', 'evidence', 'paper-review', 'sustained-use', "
        "or 'sustained-use-final')"
    )
    return 1


class _ReadOnlySchedulerJobAgent:
    """Activation 12 Scheduler, atomic step 1 -- the minimal, additive
    adapter needed to let ``AutonomousScheduler.schedule()``/
    ``AutonomousHost.start_all()`` accept one of the three already-
    existing, already-production-proven read-only capabilities (scan,
    performance report, data health check) as a queued job.

    ``AutonomousScheduler.schedule()`` and ``AutonomousHost.start_all()``
    both require, by duck typing only, that every "agent" passed to
    them be non-None and expose a callable ``run(context, iterations)``
    and a ``status`` attribute -- the exact same shape a real
    ``Orchestration.autonomous_agent.AutonomousAgent`` already has.
    This class exposes exactly those two things and nothing else: it
    is NOT an ``AutonomousAgent`` (never constructed as one, never
    isinstance-checked as one by anything downstream -- both
    ``schedule()``/``start_all()`` check shape, not type), never talks
    to ``RuntimeAnalysisPipeline``/``GoalPlanner``/``Runtime``, and
    never mutates ``Order``/``Trade``/``Account``/``Position`` state --
    it only ever calls the one zero-argument, already-existing,
    already-read-only callable it was constructed with (one of
    ``manual_scan_service.run_scan``, ``performance_summary_production_
    service.get_performance_summary``, or ``run_doctor_command``, each
    wrapped by the three small module-level closures immediately
    below), and returns whatever that callable returns.

    ``status`` is set once, at construction, to
    ``AutonomousAgentStatus.IDLE`` (Activation 2/Sprint 1's real,
    unmodified enum) purely so a real ``AutonomousHost.start()``'s own
    ``agent.status is AutonomousAgentStatus.STOPPED``/``...ERROR``
    guard reads a legitimate value from this codebase's own vocabulary
    -- this class never transitions ``status`` itself (there is no
    lifecycle here to model: each job is exactly one call, then done).

    ``context``/``iterations`` (``run()``'s own two parameters, forced
    on this class by the shape ``AutonomousHost.start_all()`` already
    requires of every agent it drives) carry no meaning for a one-shot,
    read-only job and are therefore accepted but never read here --
    the wrapped action already knows everything it needs (the already-
    built production ``app`` singletons it closed over when the caller
    constructed this instance's action).
    """

    def __init__(self, action):
        self._action = action
        self.status = AutonomousAgentStatus.IDLE

    def run(self, context, iterations):
        return (self._action(),)


def _scheduler_scan_job(app):
    """Activation 12 Scheduler job 1 -- morning scan.

    Reuses ``app.manual_scan_service.run_scan()`` and
    ``_print_manual_scan_report`` exactly as ``_run_manual_scan()``
    already does for ``python main.py scan`` -- no new scan
    implementation, no time-of-day/"morning" gating (LOCKED scope for
    this atomic step: "morning scan" means this existing scan
    capability is available as a scheduler job, not that a clock
    condition is enforced). ``generated_at`` is created here, at call
    time, exactly as ``_run_manual_scan()`` already does -- never
    generated inside ``ManualScanService`` itself.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    report = app.manual_scan_service.run_scan(generated_at)
    _print_manual_scan_report(report)
    return report


def _scheduler_performance_job(app):
    """Activation 12 Scheduler job 2 -- performance report.

    Reuses ``app.performance_summary_production_service.
    get_performance_summary()`` and ``_print_performance_summary``
    exactly as ``_run_report_performance()`` already does for
    ``python main.py report performance`` -- no new performance
    engine, no new formula. Read-only, for the same default paper
    account (``DEFAULT_PAPER_ACCOUNT_ID``) every other one-shot
    command in this module already reads.
    """
    performance = app.performance_summary_production_service.get_performance_summary(
        DEFAULT_PAPER_ACCOUNT_ID
    )
    _print_performance_summary(performance)
    return performance


def _scheduler_market_close_recap_job(app):
    """Activation 12 Scheduler job 4 -- market-close recap.

    Builds a read-only close recap from the two already-existing production
    capabilities used elsewhere in the CLI: the current scan and the
    account-scoped performance summary. This deliberately does NOT call the
    daily-report notification pipeline, because scheduler tick must remain
    usable without Telegram credentials and must not introduce an external
    side effect merely to expose a recap capability. No new formula, ranking,
    notification channel, or financial mutation is introduced here.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    report = app.manual_scan_service.run_scan(generated_at)
    _print_manual_scan_report(report)
    performance = app.performance_summary_production_service.get_performance_summary(
        DEFAULT_PAPER_ACCOUNT_ID
    )
    _print_performance_summary(performance)
    print("MARKET CLOSE RECAP")
    print("  scan: completed")
    print("  performance: completed")
    return {"report": report, "performance": performance}


def _scheduler_health_job(app):
    """Activation 12 Scheduler job 3 -- data health check.

    Reuses ``Core.doctor.run_doctor_command()`` exactly as ``python
    main.py doctor`` already does -- same function, same read-only
    diagnostic, same printed output. Not the broader Activation 12
    Self-Diagnostic requirement (a separate, not-yet-audited item);
    this is only the smallest existing read-only health-check path
    the Scheduler audit identified. ``app`` is accepted only for a
    uniform job-callable signature with the other two jobs above --
    ``run_doctor_command()`` itself needs no ``app`` argument (it
    reads global config/env directly, exactly as the CLI ``doctor``
    dispatch already does).
    """
    return run_doctor_command()


def _run_scheduler_tick_command(app, argv: list[str]) -> int:
    """``python main.py scheduler tick`` (Activation 12 Scheduler,
    atomic step 1 -- manual trigger only).

    Intentionally the only ``scheduler`` subcommand added in this
    step (no ``run``/``start``/``stop``/``daemon``/``cron``/
    ``schedule`` -- LOCKED scope). Proves the chain "production graph
    -> scheduler -> schedule() -> tick() -> existing read-only
    capability" end to end, without adding any background scheduling
    or autonomous execution:

        1. Builds one ``AutonomousHost()`` (stateless, no constructor
           arguments -- the same class ``AutonomousScheduler.tick()``
           already delegates every queued job's execution to via
           ``host.start_all()``; a fresh instance here is exactly as
           valid as any other, since ``AutonomousHost`` holds no
           state of its own).
        2. Schedules exactly four jobs on ``app.scheduler`` -- the
           one, already-constructed, production
           ``AutonomousScheduler`` singleton this graph exposes
           (never a second, independently constructed scheduler) --
           via its real, unmodified ``schedule()`` method, each
           wrapping one of the three read-only job closures above in
           a ``_ReadOnlySchedulerJobAgent``.
        3. Calls ``app.scheduler.tick()`` -- its real, unmodified
           ``tick()`` method -- exactly once, which drains and runs
           all three jobs in FIFO order, exactly in the order they
           were scheduled immediately above (scan, then performance,
           then data health check).

    Every job is a plain, synchronous, in-process call -- no thread,
    no asyncio, no cron, no persistence of any kind is introduced.
    None of the three read-only jobs constructs an ``Order``,
    ``Trade``, mutates an ``Account``/``Position``, or references
    ``PaperTradingEngine``/``ExecutionService``/any broker adapter --
    each is exactly the same call the existing manual CLI command for
    that capability already makes.

    The market-close recap reuses the existing
    ``DailyReportOrchestrator``. It is still a synchronous manual
    ``tick`` job: no clock gating, background daemon, or persistent
    scheduler state is introduced.
    """
    if not argv or argv[0] != "tick":
        print("Usage: python main.py scheduler tick")
        return 1

    host = AutonomousHost()
    context = object()
    jobs = (
        _ReadOnlySchedulerJobAgent(lambda: _scheduler_scan_job(app)),
        _ReadOnlySchedulerJobAgent(lambda: _scheduler_performance_job(app)),
        _ReadOnlySchedulerJobAgent(lambda: _scheduler_health_job(app)),
        _ReadOnlySchedulerJobAgent(lambda: _scheduler_market_close_recap_job(app)),
    )
    for job_agent in jobs:
        app.scheduler.schedule(host, [job_agent], context, 1)

    results = app.scheduler.tick()
    print(f"scheduler tick: executed {len(results)} job(s)")
    return 0


def _print_idx_tick_result(result) -> None:
    """Print one ``Orchestration.idx_daily_scheduler.TickResult`` --
    shared by ``scheduler idx-tick`` and ``scheduler simulate-day``
    (one tick's worth of output, never aggregated/reinterpreted here).
    """
    print(
        f"IDX SCHEDULER TICK  now={result.now}  trading_date={result.trading_date}  "
        f"session={result.session}"
    )
    if not result.jobs:
        print("  (no job considered this tick -- non-trading day, or no gate reached)")
        return
    for job in result.jobs:
        line = f"  - {job.job_type}: attempted={job.attempted} outcome={job.outcome}"
        if job.detail:
            line += f" detail={job.detail}"
        print(line)


def _print_scheduler_status_snapshot(snapshot) -> None:
    """Print one ``Services.health_audit_service.HealthSnapshot`` --
    verbatim field dump, no recomputation (mirrors that service's own
    "invents nothing, computes nothing" contract).
    """
    print(f"SCHEDULER STATUS  trading_date={snapshot.trading_date}")
    print("  jobs:")
    if not snapshot.jobs:
        print("    (none)")
    for job in snapshot.jobs:
        print(
            f"    - {job.job_type}: status={job.status} attempt={job.attempt} "
            f"started_at={job.started_at} finished_at={job.finished_at} "
            f"next_retry_at={job.next_retry_at}"
        )
    print("  dedup_states:")
    if not snapshot.dedup_states:
        print("    (none)")
    for dedup_state in snapshot.dedup_states:
        print(
            f"    - {dedup_state.alert_type}: last_status={dedup_state.last_status} "
            f"last_signature={dedup_state.last_signature} last_sent_at={dedup_state.last_sent_at} "
            f"updated_at={dedup_state.updated_at}"
        )
    print("  recent_events:")
    if not snapshot.recent_events:
        print("    (none)")
    for event in snapshot.recent_events:
        print(f"    - [{event.created_at}] {event.event_type}: {event.payload}")


def _run_scheduler_idx_tick_command(app, argv: list[str]) -> int:
    """``python main.py scheduler idx-tick [--now ISO8601]`` (Phase
    D.1 CLI wiring).

    Calls ``app.idx_daily_scheduler.tick()`` -- the one, already-built
    Phase D ``IDXDailyScheduler`` singleton this graph exposes -- with
    the caller-supplied moment, exactly mirroring that method's own
    "now is caller-supplied, never generated internally" contract.
    ``--now`` omitted defaults to the real current UTC time (this is a
    manual one-shot CLI trigger, not a restart-safety concern -- the
    scheduler's own idempotency/backoff state is what makes repeated
    invocations safe, not anything this command does).
    """
    now_raw: Optional[str] = None
    i = 0
    while i < len(argv):
        if argv[i] == "--now" and i + 1 < len(argv):
            now_raw = argv[i + 1]
            i += 2
        else:
            i += 1

    if now_raw is not None:
        try:
            now = datetime.fromisoformat(now_raw)
        except ValueError:
            print(f"Invalid --now value {now_raw!r}: expected ISO-8601 (e.g. 2026-08-23T09:15:00+07:00)")
            return 1
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    result = app.idx_daily_scheduler.tick(now)
    _print_idx_tick_result(result)
    return 0


def _run_scheduler_simulate_day_command(app, argv: list[str]) -> int:
    """``python main.py scheduler simulate-day [--date YYYY-MM-DD]
    [--interval-minutes N]`` (Phase D.1 CLI wiring).

    Drives ``app.idx_daily_scheduler.tick()`` repeatedly, once per
    ``interval_minutes`` step, from the IDX pre-market open through
    the post-close window on ``--date`` (IDX-local/Asia-Jakarta,
    via the same ``PRE_MARKET_OPEN``/``POST_CLOSE_END`` boundaries
    ``Business.idx_market_calendar`` already defines) -- a full-day
    dry run of the real, unmodified scheduler against whatever
    real/fake collaborators this process's ``app`` was built with.
    Every simulated moment is still a real, explicit caller-supplied
    ``now`` passed straight to ``tick()`` -- no internal clock, no new
    scheduling logic; this command only generates the sequence of
    ``now`` values an operator would otherwise have to pass to
    ``idx-tick`` one at a time.
    """
    date_raw: Optional[str] = None
    interval_minutes = 5
    i = 0
    while i < len(argv):
        if argv[i] == "--date" and i + 1 < len(argv):
            date_raw = argv[i + 1]
            i += 2
        elif argv[i] == "--interval-minutes" and i + 1 < len(argv):
            try:
                interval_minutes = int(argv[i + 1])
            except ValueError:
                print(f"Invalid --interval-minutes value {argv[i + 1]!r}: expected an integer")
                return 1
            i += 2
        else:
            i += 1

    if interval_minutes <= 0:
        print("Usage: python main.py scheduler simulate-day [--date YYYY-MM-DD] [--interval-minutes N] (N must be > 0)")
        return 1

    calendar = load_idx_market_calendar()
    if date_raw is not None:
        try:
            target_date = date.fromisoformat(date_raw)
        except ValueError:
            print(f"Invalid --date value {date_raw!r}: expected YYYY-MM-DD")
            return 1
    else:
        target_date = calendar.local_date(datetime.now(timezone.utc))

    local_tz = calendar.timezone()
    moment = datetime.combine(target_date, PRE_MARKET_OPEN, tzinfo=local_tz)
    end_moment = datetime.combine(target_date, POST_CLOSE_END, tzinfo=local_tz)
    step = timedelta(minutes=interval_minutes)

    tick_count = 0
    while moment <= end_moment:
        result = app.idx_daily_scheduler.tick(moment.astimezone(timezone.utc))
        _print_idx_tick_result(result)
        tick_count += 1
        moment += step

    print(f"scheduler simulate-day: {tick_count} tick(s) simulated for {target_date.isoformat()}")
    return 0


def _run_scheduler_status_command(app, argv: list[str]) -> int:
    """``python main.py scheduler status [--date YYYY-MM-DD]`` (Phase
    D.1 CLI wiring).

    Purely a read: delegates to ``app.health_audit_service.
    get_snapshot()`` -- the already-built Phase D read-only aggregator
    -- and prints its ``HealthSnapshot`` verbatim. ``--date`` omitted
    lets that service derive "today" itself (its own documented
    default), never recomputed here.
    """
    date_raw: Optional[str] = None
    i = 0
    while i < len(argv):
        if argv[i] == "--date" and i + 1 < len(argv):
            date_raw = argv[i + 1]
            i += 2
        else:
            i += 1

    snapshot = app.health_audit_service.get_snapshot(trading_date=date_raw)
    _print_scheduler_status_snapshot(snapshot)
    return 0


def _run_scheduler_command(app, argv: list[str]) -> int:
    """``python main.py scheduler <subcommand>`` (Activation 12
    Scheduler atomic step 1, extended by Phase D.1 CLI wiring).

    ``tick`` remains exactly as it was (Activation 12 Scheduler,
    unmodified). Phase D.1 adds three new, read-mostly subcommands
    that drive/inspect the separate Phase D ``IDXDailyScheduler``
    (``app.idx_daily_scheduler``) instead: ``idx-tick``,
    ``simulate-day``, and ``status``.
    """
    if not argv:
        print("Usage: python main.py scheduler tick|idx-tick|simulate-day|status")
        return 1
    subcommand = argv[0]
    if subcommand == "tick":
        return _run_scheduler_tick_command(app, argv)
    if subcommand == "idx-tick":
        return _run_scheduler_idx_tick_command(app, argv[1:])
    if subcommand == "simulate-day":
        return _run_scheduler_simulate_day_command(app, argv[1:])
    if subcommand == "status":
        return _run_scheduler_status_command(app, argv[1:])
    print(
        f"Unknown scheduler subcommand: {subcommand!r} "
        "(expected 'tick', 'idx-tick', 'simulate-day', or 'status')"
    )
    return 1


def _print_telegram_poll_outcome(result) -> None:
    """Print one ``Orchestration.telegram_inbound_control_plane.PollOutcome``
    (Phase E Task 6 CLI wiring) as plain, human-readable text.

    Read-only formatting only -- prints exactly what ``poll_once()``
    already returned, never recomputes or reinterprets any status.
    """
    if result.polling_failed:
        print(f"telegram poll: FAILED -- {result.polling_error}")
        return

    if not result.updates:
        print(f"telegram poll: OK -- no new updates (last_update_id={result.last_update_id})")
        return

    print(f"telegram poll: OK -- {len(result.updates)} update(s) processed")
    for outcome in result.updates:
        reply_note = "replied" if outcome.reply_sent else "no reply"
        detail_note = f" -- {outcome.detail}" if outcome.detail else ""
        print(
            f"  update_id={outcome.update_id} chat_id={outcome.chat_id} "
            f"command={outcome.command!r} status={outcome.status} ({reply_note}){detail_note}"
        )
    print(f"  last_update_id={result.last_update_id}")


def _run_telegram_poll_command(app, argv: list[str]) -> int:
    """``python main.py telegram poll`` (Phase E Task 6 CLI wiring).

    Delegates to this graph's existing, unmodified
    ``app.telegram_inbound_control_plane.poll_once()`` (Task 5) exactly
    once -- one ``getUpdates`` call, deterministic per-update
    processing, and the durable offset advance, all already owned by
    that class. This function performs no polling loop, no retry, and
    no broker/live-execution call of any kind; it is a thin CLI
    front-end that prints the returned ``PollOutcome`` and maps
    ``polling_failed`` to a non-zero exit code.
    """
    result = app.telegram_inbound_control_plane.poll_once()
    _print_telegram_poll_outcome(result)
    return 1 if result.polling_failed else 0


def _run_telegram_status_command(app, argv: list[str]) -> int:
    """``python main.py telegram status`` (Phase E Task 6 CLI wiring).

    Purely a read: prints the configured allowlist
    (``app.telegram_allowlist_policy``, Task 2, unmodified) and the
    durable long-poll offset
    (``app.telegram_inbound_state_repository.get()``, Task 1,
    unmodified). No Telegram network call is made by this command --
    for the current, actually-fetched inbound state, use ``telegram
    poll`` above.

    If the ``telegram_control`` tables (``telegram_inbound_state`` /
    ``telegram_command_audit``) have not yet been migrated, the two
    read calls below raise ``Core.exceptions.RepositoryError`` --
    caught here and reported as a clean, actionable one-line message
    (matching ``python main.py doctor``'s own "telegram_control
    tables" BLOCKED check and its exact remediation command) rather
    than an unhandled traceback reaching the operator's console.
    """
    allowed_chat_ids = sorted(app.telegram_allowlist_policy.allowed_chat_ids)
    if allowed_chat_ids:
        print(f"Allowlist: {len(allowed_chat_ids)} chat id(s) authorized: {', '.join(allowed_chat_ids)}")
    else:
        print("Allowlist: EMPTY -- fails closed, every inbound chat is REJECTED_UNAUTHORIZED")

    try:
        state = app.telegram_inbound_state_repository.get()
    except RepositoryError as exc:
        print(
            "Polling state: UNAVAILABLE -- telegram_control tables are not migrated "
            f"(run 'python run_telegram_control_migrations.py'). Detail: {exc}"
        )
        print("Recent commands: UNAVAILABLE -- see above")
        return 1

    if state is None:
        print("Polling state: no offset recorded yet -- 'telegram poll' has never run")
    else:
        print(f"Polling state: last_update_id={state.last_update_id} (updated_at={state.updated_at})")

    try:
        recent = app.telegram_command_audit_repository.list_recent(limit=5)
    except RepositoryError as exc:
        print(
            "Recent commands: UNAVAILABLE -- telegram_control tables are not migrated "
            f"(run 'python run_telegram_control_migrations.py'). Detail: {exc}"
        )
        return 1

    if not recent:
        print("Recent commands: none recorded yet")
    else:
        print(f"Recent commands (most recent {len(recent)}):")
        for row in recent:
            detail_note = f" -- {row.detail}" if row.detail else ""
            print(
                f"  [{row.received_at}] chat_id={row.chat_id} command={row.command!r} "
                f"status={row.status}{detail_note}"
            )
    return 0


def _run_telegram_command(app, argv: list[str]) -> int:
    """``python main.py telegram <subcommand>`` (Phase E Task 6 CLI
    wiring -- \"telegram poll\" and \"telegram status\").

    Both subcommands reuse this graph's already-built
    ``telegram_inbound_control_plane``/``telegram_allowlist_policy``/
    ``telegram_inbound_state_repository``/
    ``telegram_command_audit_repository`` fields (Task 6 wiring) --
    none of Tasks 1-5's classes are redesigned or reimplemented here.
    No broker/live-execution path is introduced by either subcommand.
    """
    if not argv:
        print("Usage: python main.py telegram poll|status")
        return 1
    subcommand = argv[0]
    if subcommand == "poll":
        return _run_telegram_poll_command(app, argv[1:])
    if subcommand == "status":
        return _run_telegram_status_command(app, argv[1:])
    print(f"Unknown telegram subcommand: {subcommand!r} (expected 'poll' or 'status')")
    return 1


def _latest_snapshot_for_symbol(app, symbol: str) -> Optional[RankingSnapshot]:
    """Read-only lookup of the most recent scan's ranking snapshot for
    ``symbol`` (Activation 4 Session 1).

    Reuses ``app.snapshot_repository.list_latest()`` exactly as-is
    (LOCKED, Sprint 5/Activation 2.7) -- the rows for the most recent
    ``scan_time`` present in ``ranking_snapshots`` -- and filters them
    in this CLI layer for one symbol. No new query, no new ranking,
    and no new recommendation is computed here: this is purely a
    filter over data ``ManualScanService``/``RankingEngine`` already
    persisted the last time ``scan`` ran.
    """
    symbol = symbol.upper()
    for row in app.snapshot_repository.list_latest():
        if row.symbol.upper() == symbol:
            return row
    return None


def _fetch_current_price(app, symbol: str) -> Optional[float]:
    """Real, current price lookup for ``symbol`` via the shared
    ``app.market_price_tool`` (Activation 4 Session 1).

    Calls the existing, unmodified ``MarketPriceTool.execute()`` with
    only ``symbol`` in ``ToolContext.parameters`` -- deliberately no
    ``current_price``/``previous_price`` supplied, so that Tool's own
    Phase 19 real-data path (``StockService``/yfinance) performs the
    lookup itself. No new price-fetching logic is written here; this
    function only builds the ``ToolContext`` and reads back
    ``result.output["price"]``.

    Returns:
        The real current price, or ``None`` if the Tool could not
        resolve one -- never a fabricated/guessed value.
    """
    context = ToolContext(task=None, parameters={"symbol": symbol})
    result = app.market_price_tool.execute(context)
    price = result.output.get("price") if isinstance(result.output, dict) else None
    if price is None or isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    return float(price)


def _compute_allocation_quantity(cash: float, allocation: float, price: float, lot_size: int) -> int:
    """CLI-layer allocation helper (Activation 4 Session 1 roadmap:
    "actual cash -> allocation -> quantity -> IDX lot adjustment").

    Display/estimate arithmetic only -- not a second validation path.
    ``PaperTradingEngine.submit_order()`` remains the sole final
    validator (its own gate 6/gate 8 independently re-check lot size
    and cash against these same real numbers); this helper exists
    only to turn a caller-supplied ``--allocation`` fraction and a
    real current price into a concrete, lot-adjusted quantity to
    submit and to display as an estimate before submission.

    Args:
        cash: Real ``account.cash`` -- never ``0`` unless the account
            genuinely has zero cash (never a hardcoded placeholder).
        allocation: Fraction of cash to allocate (e.g. ``0.05`` for
            5%). Must be a positive number.
        price: Real current price for the symbol.
        lot_size: IDX lot size (``ExecutionPolicy.lot_size``).

    Returns:
        A non-negative multiple of ``lot_size`` (``0`` if the
        allocated capital cannot afford even one lot).
    """
    if cash <= 0 or allocation <= 0 or price <= 0 or lot_size <= 0:
        return 0
    target_capital = cash * allocation
    raw_quantity = math.floor(target_capital / price)
    lots = raw_quantity // lot_size
    return int(lots * lot_size)


def _print_recommendation(app, symbol: str, snapshot: Optional[RankingSnapshot]) -> None:
    """Display recommendation fields for ``symbol`` (Activation 4
    Session 1 roadmap 3.x "Output"): signal, confidence, reason, data
    timestamp, risk, suggested allocation, estimated cost, fee, stop,
    confirmation status.

    Every field is read from data that already exists in this
    codebase (the latest ``RankingSnapshot`` for ``symbol``, the
    canonical ``ExecutionPolicy``, and any open ``Position``'s
    ``stop_loss``/``take_profit``). Fields with no real source in the
    codebase (``risk``, ``suggested allocation`` as a system-computed
    number, ``estimated cost`` without a chosen allocation) are
    printed as ``N/A`` -- never invented (per audit STEP 1, section
    8).
    """
    from Business.execution_policy_config import load_execution_policy

    symbol = symbol.upper()
    print(f"Recommendation -- {symbol}")
    print()

    if snapshot is None:
        print("No scan data found for this symbol.")
        print("Run 'python main.py scan --market idx' first, then retry.")
        return

    if snapshot.status == "error":
        print("Signal          : DATA_ERROR")
        print(f"Reason          : {snapshot.error_message}")
        print(f"Data Timestamp  : {snapshot.scan_time}")
        return

    execution_policy = load_execution_policy()
    # Activation 9.2: this lookup used to check only the default IDR
    # 'paper' account, so a US symbol's open position (held in
    # 'us-usd') always displayed as "no position" here even when one
    # existed. Additive fallback only -- IDX's own lookup (checked
    # first, unchanged) is never skipped or reordered; this only adds
    # a second lookup when the first finds nothing.
    position = app.position_repository.get_open_position(DEFAULT_PAPER_ACCOUNT_ID, symbol)
    if position is None:
        position = app.position_repository.get_open_position(DEFAULT_US_ACCOUNT_ID, symbol)
    stop_loss = position.stop_loss if position is not None and position.stop_loss is not None else "N/A"
    take_profit = position.take_profit if position is not None and position.take_profit is not None else "N/A"

    print(f"Signal          : {snapshot.recommendation}")
    print(f"Confidence      : {snapshot.confidence}")
    print(f"Reason          : {snapshot.evidence_summary}")
    print(f"Data Timestamp  : {snapshot.scan_time}")
    print("Risk            : N/A (no risk engine for individual symbols exists in this codebase)")
    print("Suggested Alloc.: N/A (choose your own via 'paper buy SYMBOL --allocation X')")
    print("Estimated Cost  : N/A (supply --allocation to 'paper buy' to compute a real estimate)")
    print(
        f"Fee/Tax Rates   : buy_fee={execution_policy.buy_fee_rate} "
        f"sell_fee={execution_policy.sell_fee_rate} sell_tax={execution_policy.sell_tax_rate}"
    )
    print(f"Stop Loss       : {stop_loss}")
    print(f"Take Profit     : {take_profit}")
    print("Confirmation    : AWAITING APPROVAL (run 'python main.py paper buy/sell ...' to approve)")


def _run_recommendation_command(app, argv: list[str]) -> int:
    """``python main.py recommendation SYMBOL`` (Activation 4 Session 1).

    Read-only. Reads the latest scan snapshot for ``SYMBOL`` (via
    ``_latest_snapshot_for_symbol``) and displays it -- never
    executes an order, never mutates any state. This is the
    "recommendation" step in the mandated flow ``scan ->
    recommendation -> user review -> user approval -> paper order``.
    """
    if not argv:
        print("Usage: python main.py recommendation SYMBOL")
        return 1
    symbol = argv[0].upper()
    snapshot = _latest_snapshot_for_symbol(app, symbol)
    _print_recommendation(app, symbol, snapshot)
    return 0


def _parse_brief_risk_args(argv: list[str]) -> tuple[Optional["RiskInputs"], list[str], Optional[str]]:
    """Parse ``--stop-loss-pct``/``--take-profit-pct``/``--risk-pct``/
    ``--balance`` out of ``argv`` (Phase B).

    All four flags are optional together: if none are supplied,
    ``risk_inputs`` is ``None`` and the brief resolves to
    ``POLICY_BLOCKED`` when otherwise actionable, per
    ``DecisionBriefService``'s own "never invent risk parameters"
    contract. If any are supplied, all four must be present and
    numeric, or this returns an error message.

    Returns:
        ``(risk_inputs_or_None, remaining_argv, error_message_or_None)``.
    """
    flags = {
        "--stop-loss-pct": None,
        "--take-profit-pct": None,
        "--risk-pct": None,
        "--balance": None,
    }
    remaining: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in flags and i + 1 < len(argv):
            flags[token] = argv[i + 1]
            i += 2
            continue
        remaining.append(token)
        i += 1

    supplied = {k: v for k, v in flags.items() if v is not None}
    if not supplied:
        return None, remaining, None
    if len(supplied) != len(flags):
        missing = [k for k, v in flags.items() if v is None]
        return None, remaining, f"Supply all of --stop-loss-pct/--take-profit-pct/--risk-pct/--balance together, or none. Missing: {', '.join(missing)}"

    try:
        stop_loss_percent = float(flags["--stop-loss-pct"])
        take_profit_percent = float(flags["--take-profit-pct"])
        risk_per_trade_percent = float(flags["--risk-pct"])
        account_balance = float(flags["--balance"])
    except ValueError:
        return None, remaining, "All of --stop-loss-pct/--take-profit-pct/--risk-pct/--balance must be numbers."

    return (
        {
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "risk_per_trade_percent": risk_per_trade_percent,
            "account_balance": account_balance,
        },
        remaining,
        None,
    )


def _print_decision_brief(brief) -> None:
    """Display a ``DecisionBrief`` (Phase B). Read-only: never
    executes, never submits, never approves a trade -- displays
    exactly what ``DecisionBriefService`` persisted, nothing computed
    here.
    """
    print(f"Decision Brief -- {brief.symbol}")
    print()
    print(f"Status          : {brief.status}")
    print(f"Generated At    : {brief.generated_at}")
    if brief.source_snapshot_id is not None:
        print(f"Source Snapshot : {brief.source_snapshot_id}")
    if brief.reason:
        print(f"Reason          : {brief.reason}")

    if brief.status == "SUCCESS":
        print()
        print(f"Entry Price     : {brief.entry_price}")
        print(f"Stop Loss       : {brief.stop_loss_price}")
        print(f"Take Profit     : {brief.take_profit_price}")
        print(f"Risk Amount     : {brief.risk_amount}")
        print(f"Position Size   : {brief.position_size}")
        print(f"Risk/Reward     : {brief.risk_reward_ratio}")
        print()
        print("This is a plan, not an order. Run 'python main.py paper buy ...' to submit one.")


def _run_brief_symbol_command(app, argv: list[str]) -> int:
    """``python main.py brief SYMBOL [--stop-loss-pct X --take-profit-pct Y
    --risk-pct Z --balance W]`` (Phase B).

    Read-only from the caller's perspective except for the one
    append-only ``DecisionBrief`` row this writes when there is
    something new to generate -- never a paper order, never a
    ``Trade``/``Position``. Risk parameters are optional together;
    when omitted, an otherwise-actionable snapshot resolves to
    ``POLICY_BLOCKED`` rather than a guessed plan.

    Retrieval vs. generation (Phase B "fix restart retrieval"):
    with NO risk arguments, this first retrieves the latest
    persisted ``DecisionBrief`` for the symbol via
    ``DecisionBriefService.get_latest_brief`` and displays it exactly
    as stored -- it never regenerates or reprices an existing brief.
    Only when no brief has ever been persisted for the symbol does
    this fall back to the existing ``generate_brief`` behavior (which
    itself persists one new, explicit non-action-status row). Supplying
    risk arguments always generates a brand-new brief, unconditionally,
    exactly as before -- retrieval never applies to a priced request.
    """
    from Services.decision_brief_service import RiskInputs

    if not argv:
        print(
            "Usage: python main.py brief SYMBOL "
            "[--stop-loss-pct X --take-profit-pct Y --risk-pct Z --balance W]"
        )
        return 1

    symbol, rest = argv[0], argv[1:]
    risk_dict, _remaining, error = _parse_brief_risk_args(rest)
    if error:
        print(error)
        return 1

    if risk_dict is not None:
        latest_price = _fetch_current_price(app, symbol.upper())
        if latest_price is None:
            print(f"Could not resolve a real current price for '{symbol.upper()}' -- cannot price a plan.")
            return 1
        risk_inputs = RiskInputs(entry_price=latest_price, **risk_dict)
        brief = app.decision_brief_service.generate_brief(symbol, risk_inputs=risk_inputs)
        _print_decision_brief(brief)
        return 0

    brief = app.decision_brief_service.get_latest_brief(symbol)
    if brief is None:
        brief = app.decision_brief_service.generate_brief(symbol, risk_inputs=None)
    _print_decision_brief(brief)
    return 0


def _run_brief_watchlist_command(app, argv: list[str]) -> int:
    """``python main.py brief watchlist`` (Phase B).

    Generates a brief for every symbol currently on the watchlist
    (via the existing ``app.watchlist_repository.list_all()``, never
    a new watchlist query), reusing ``_run_brief_symbol_command``'s own
    per-symbol logic exactly once per ticker. No risk parameters are
    accepted here -- a batch run has no single per-symbol entry price
    to price a plan against without a real per-symbol quote flow, so
    every actionable symbol here resolves through the same
    ``POLICY_BLOCKED`` path as an unpriced single-symbol brief unless
    a future Activation adds batch pricing. This never submits any
    order for any symbol.
    """
    tickers = app.watchlist_repository.list_all()
    if not tickers:
        print("Watchlist is empty. Add tickers with 'python main.py watchlist add TICKER'.")
        return 0

    exit_code = 0
    for ticker in tickers:
        rc = _run_brief_symbol_command(app, [ticker])
        print()
        if rc != 0:
            exit_code = rc
    return exit_code


def _run_brief_command(app, argv: list[str]) -> int:
    """``python main.py brief <SYMBOL|watchlist> ...`` dispatch (Phase B)."""
    if not argv:
        print("Usage: python main.py brief <SYMBOL|watchlist> [...]")
        return 1
    if argv[0] == "watchlist":
        return _run_brief_watchlist_command(app, argv[1:])
    return _run_brief_symbol_command(app, argv)


def _print_risk_limits(limits) -> None:
    """Display a ``RiskLimits`` row (Phase C). Read-only."""
    if limits is None:
        print("No personal risk limits are configured yet. Set them with:")
        print(
            "  python main.py risk-limits set --capital X --max-risk-pct Y "
            "--max-daily-loss Z --max-trades N --cooldown C [--symbols A,B,C]"
        )
        return
    print("Personal Risk Limits")
    print()
    print(f"Reference Capital     : {limits.reference_capital}")
    print(f"Max Risk / Trade      : {limits.max_risk_per_trade_percent}%")
    print(f"Max Daily Loss        : {limits.max_daily_loss}")
    print(f"Max Trades / Day      : {limits.max_trades_per_day}")
    print(f"Loss-Streak Cooldown  : {limits.loss_streak_cooldown}")
    print(f"Allowed Symbols       : {limits.allowed_symbols or 'ALL'}")
    print(f"Updated At            : {limits.updated_at}")


def _parse_risk_limits_set_args(argv: list[str]) -> tuple[Optional[dict], Optional[str]]:
    """Parse ``risk-limits set`` flags (Phase C).

    All five required flags (``--capital``/``--max-risk-pct``/
    ``--max-daily-loss``/``--max-trades``/``--cooldown``) must be
    present and numeric; ``--symbols`` is optional. Mirrors
    ``_parse_brief_risk_args``'s own flag-parsing style.

    Returns:
        ``(parsed_dict_or_None, error_message_or_None)``.
    """
    flags = {
        "--capital": None,
        "--max-risk-pct": None,
        "--max-daily-loss": None,
        "--max-trades": None,
        "--cooldown": None,
        "--symbols": None,
    }
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in flags and i + 1 < len(argv):
            flags[token] = argv[i + 1]
            i += 2
            continue
        i += 1

    required = ["--capital", "--max-risk-pct", "--max-daily-loss", "--max-trades", "--cooldown"]
    missing = [k for k in required if flags[k] is None]
    if missing:
        return None, f"Missing required flag(s): {', '.join(missing)}."

    try:
        reference_capital = float(flags["--capital"])
        max_risk_per_trade_percent = float(flags["--max-risk-pct"])
        max_daily_loss = float(flags["--max-daily-loss"])
        max_trades_per_day = int(flags["--max-trades"])
        loss_streak_cooldown = int(flags["--cooldown"])
    except ValueError:
        return None, "--capital/--max-risk-pct/--max-daily-loss/--max-trades/--cooldown must be numbers."

    allowed_symbols = None
    if flags["--symbols"]:
        allowed_symbols = [s.strip().upper() for s in flags["--symbols"].split(",") if s.strip()]

    return (
        {
            "reference_capital": reference_capital,
            "max_risk_per_trade_percent": max_risk_per_trade_percent,
            "max_daily_loss": max_daily_loss,
            "max_trades_per_day": max_trades_per_day,
            "loss_streak_cooldown": loss_streak_cooldown,
            "allowed_symbols": allowed_symbols,
        },
        None,
    )


def _run_risk_limits_command(app, argv: list[str]) -> int:
    """``python main.py risk-limits <set|show> [...]`` (Phase C).

    Read-only except for ``set``, which upserts the single persisted
    ``RiskLimits`` row via ``app.risk_limits_repository`` -- never a
    paper order, ``Trade``, or ``Position``.
    """
    if not argv:
        print("Usage: python main.py risk-limits <set|show> [...]")
        return 1
    subcommand, rest = argv[0], argv[1:]

    if subcommand == "show":
        _print_risk_limits(app.risk_limits_repository.get_current())
        return 0

    if subcommand == "set":
        parsed, error = _parse_risk_limits_set_args(rest)
        if error:
            print(error)
            print(
                "Usage: python main.py risk-limits set --capital X --max-risk-pct Y "
                "--max-daily-loss Z --max-trades N --cooldown C [--symbols A,B,C]"
            )
            return 1
        updated_at = datetime.now(timezone.utc).isoformat()
        limits = app.risk_limits_repository.save(updated_at=updated_at, **parsed)
        _print_risk_limits(limits)
        return 0

    print(f"Unknown risk-limits subcommand: {subcommand!r} (expected 'set' or 'show')")
    return 1


def _print_journal_entry(entry) -> None:
    """Display a ``JournalEntry`` (Phase C). Read-only: never submits,
    never approves a trade -- displays exactly what ``JournalService``
    persisted.
    """
    print(f"Journal Entry #{entry.entry_id} -- {entry.symbol} (brief_id={entry.brief_id})")
    print()
    print(f"Decision        : {entry.decision}")
    print(f"Decided At      : {entry.decided_at}")
    print(f"Risk Policy     : {entry.risk_policy_status}")
    if entry.risk_policy_reason:
        print(f"Reason          : {entry.risk_policy_reason}")
    if entry.note:
        print(f"Note            : {entry.note}")
    if entry.planned_r is not None:
        print(f"Planned R       : {entry.planned_r}")
    if entry.outcome_status is not None:
        print()
        print(f"Outcome         : {entry.outcome_status}")
        print(f"Exit Price      : {entry.exit_price}")
        print(f"Realized R      : {entry.realized_r}")
        print(f"Closed At       : {entry.closed_at}")

    if entry.decision == "TAKE" and entry.risk_policy_status == "ACCEPTED":
        print()
        print("This is a journal record, not an order. It never created a paper order.")


def _run_journal_decision_command(app, decision: str, argv: list[str]) -> int:
    """``python main.py journal <take|skip|wait> BRIEF_ID [--note "..."]``
    (Phase C).
    """
    if not argv:
        print(f"Usage: python main.py journal {decision.lower()} BRIEF_ID [--note \"...\"]")
        return 1

    try:
        brief_id = int(argv[0])
    except ValueError:
        print(f"BRIEF_ID must be an integer, got {argv[0]!r}.")
        return 1

    note = None
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--note" and i + 1 < len(rest):
            note = rest[i + 1]
            i += 2
            continue
        i += 1

    try:
        entry = app.journal_service.record_decision(brief_id, decision, note=note)
    except ValueError as exc:
        print(str(exc))
        return 1

    _print_journal_entry(entry)
    return 0


def _run_journal_close_command(app, argv: list[str]) -> int:
    """``python main.py journal close ENTRY_ID --outcome STATUS
    [--exit-price P]`` (Phase C).

    Records optional manual execution/close information on an
    already-ACCEPTED TAKE journal entry. Never creates or touches a
    paper order, ``Trade``, or ``Position``.
    """
    if not argv:
        print("Usage: python main.py journal close ENTRY_ID --outcome STATUS [--exit-price P]")
        return 1

    try:
        entry_id = int(argv[0])
    except ValueError:
        print(f"ENTRY_ID must be an integer, got {argv[0]!r}.")
        return 1

    outcome_status = None
    exit_price = None
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--outcome" and i + 1 < len(rest):
            outcome_status = rest[i + 1]
            i += 2
            continue
        if rest[i] == "--exit-price" and i + 1 < len(rest):
            try:
                exit_price = float(rest[i + 1])
            except ValueError:
                print(f"--exit-price must be a number, got {rest[i + 1]!r}.")
                return 1
            i += 2
            continue
        i += 1

    if outcome_status is None:
        print("Missing required flag: --outcome (OPEN|CLOSED_WIN|CLOSED_LOSS|CLOSED_BREAKEVEN)")
        return 1

    try:
        entry = app.journal_service.record_outcome(entry_id, outcome_status=outcome_status, exit_price=exit_price)
    except ValueError as exc:
        print(str(exc))
        return 1

    _print_journal_entry(entry)
    return 0


def _run_journal_show_command(app, argv: list[str]) -> int:
    """``python main.py journal show ENTRY_ID`` (Phase C). Read-only."""
    if not argv:
        print("Usage: python main.py journal show ENTRY_ID")
        return 1
    try:
        entry_id = int(argv[0])
    except ValueError:
        print(f"ENTRY_ID must be an integer, got {argv[0]!r}.")
        return 1
    entry = app.journal_service.get_by_id(entry_id)
    if entry is None:
        print(f"No journal entry exists with entry_id={entry_id}.")
        return 1
    _print_journal_entry(entry)
    return 0


def _run_journal_list_command(app, argv: list[str]) -> int:
    """``python main.py journal list [SYMBOL]`` (Phase C). Read-only."""
    entries = app.journal_service.list_by_symbol(argv[0]) if argv else app.journal_service.list_all()
    if not entries:
        print("No journal entries recorded yet.")
        return 0
    for entry in entries:
        outcome = f" outcome={entry.outcome_status}" if entry.outcome_status else ""
        print(
            f"#{entry.entry_id} brief={entry.brief_id} {entry.symbol} "
            f"{entry.decision}/{entry.risk_policy_status}{outcome} @ {entry.decided_at}"
        )
    return 0


def _run_journal_command(app, argv: list[str]) -> int:
    """``python main.py journal <take|skip|wait|close|show|list> ...``
    dispatch (Phase C, "Decision Journal").

    Read-only from the caller's perspective except for the one
    append-only ``JournalEntry`` row ``take``/``skip``/``wait`` writes
    (plus the one, later, outcome-only update ``close`` performs) --
    never a paper order, never a ``Trade``/``Position``.
    """
    if not argv:
        print("Usage: python main.py journal <take|skip|wait|close|show|list> ...")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "take":
        return _run_journal_decision_command(app, "TAKE", rest)
    if subcommand == "skip":
        return _run_journal_decision_command(app, "SKIP", rest)
    if subcommand == "wait":
        return _run_journal_decision_command(app, "WAIT", rest)
    if subcommand == "close":
        return _run_journal_close_command(app, rest)
    if subcommand == "show":
        return _run_journal_show_command(app, rest)
    if subcommand == "list":
        return _run_journal_list_command(app, rest)
    print(f"Unknown journal subcommand: {subcommand!r} (expected 'take', 'skip', 'wait', 'close', 'show', or 'list')")
    return 1


def _print_observation_window(window) -> None:
    """Display an ``ObservationWindow`` (Phase H Task 1). Read-only:
    displays exactly what ``ObservationWindowService`` persisted --
    never computes or fabricates a metric.
    """
    print(f"Observation Window #{window.window_id} [{window.status}]")
    print()
    print(f"Start At   : {window.start_at}")
    print(f"End At     : {window.end_at}")
    print(f"Timezone   : {window.timezone}")
    if window.note:
        print(f"Note       : {window.note}")
    print(f"Created At : {window.created_at}")
    if window.closed_at:
        print(f"Closed At  : {window.closed_at}")


def _parse_observation_window_open_args(argv: list[str]) -> tuple[Optional[dict], Optional[str]]:
    """Parse ``observation-window open`` flags (Phase H Task 1).

    ``--start``/``--end``/``--timezone`` are required;
    ``--note`` is optional. Mirrors
    ``_parse_risk_limits_set_args``'s own flag-parsing style.

    Returns:
        ``(parsed_dict_or_None, error_message_or_None)``.
    """
    flags = {"--start": None, "--end": None, "--timezone": None, "--note": None}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in flags and i + 1 < len(argv):
            flags[token] = argv[i + 1]
            i += 2
            continue
        i += 1

    required = ["--start", "--end", "--timezone"]
    missing = [k for k in required if flags[k] is None]
    if missing:
        return None, f"Missing required flag(s): {', '.join(missing)}."

    return (
        {
            "start_at": flags["--start"],
            "end_at": flags["--end"],
            "timezone_name": flags["--timezone"],
            "note": flags["--note"],
        },
        None,
    )


def _run_observation_window_open_command(app, argv: list[str]) -> int:
    """``python main.py observation-window open --start START --end END
    --timezone TZ [--note "..."]`` (Phase H Task 1).

    The operator must select the window explicitly -- no automatic
    period selection, no inference of a "good" window from data.
    """
    parsed, error = _parse_observation_window_open_args(argv)
    if error:
        print(error)
        print(
            "Usage: python main.py observation-window open --start START --end END "
            "--timezone TZ [--note \"...\"]"
        )
        return 1

    try:
        window = app.observation_window_service.open(**parsed)
    except ValueError as exc:
        print(str(exc))
        return 1

    _print_observation_window(window)
    return 0


def _run_observation_window_show_command(app, argv: list[str]) -> int:
    """``python main.py observation-window show`` (Phase H Task 1).
    Read-only."""
    window = app.observation_window_service.get_current()
    if window is None:
        print("No observation window is currently ACTIVE.")
        return 0
    _print_observation_window(window)
    return 0


def _run_observation_window_close_command(app, argv: list[str]) -> int:
    """``python main.py observation-window close [WINDOW_ID]`` (Phase H
    Task 1). Closes the currently ACTIVE window if WINDOW_ID is
    omitted."""
    window_id = None
    if argv:
        try:
            window_id = int(argv[0])
        except ValueError:
            print(f"WINDOW_ID must be an integer, got {argv[0]!r}.")
            return 1

    try:
        window = app.observation_window_service.close(window_id)
    except ValueError as exc:
        print(str(exc))
        return 1

    _print_observation_window(window)
    return 0


def _run_observation_window_command(app, argv: list[str]) -> int:
    """``python main.py observation-window <open|show|close> ...``
    dispatch (Phase H Task 1, "Observation Window + Sustained-Use
    Review Record").

    Read-only except for ``open`` (one new ``ACTIVE`` row) and
    ``close`` (one in-place ``ACTIVE`` -> ``CLOSED`` transition on an
    existing row) -- never a paper order, never a ``Trade``/
    ``Position``, never a risk-limit change. Does not unlock live
    execution.
    """
    if not argv:
        print("Usage: python main.py observation-window <open|show|close> ...")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "open":
        return _run_observation_window_open_command(app, rest)
    if subcommand == "show":
        return _run_observation_window_show_command(app, rest)
    if subcommand == "close":
        return _run_observation_window_close_command(app, rest)
    print(f"Unknown observation-window subcommand: {subcommand!r} (expected 'open', 'show', or 'close')")
    return 1


def _print_trade_result(trade) -> None:
    """Display a filled ``Trade`` after a successful 'paper buy'/'paper
    sell' (Activation 4 Session 1). Purely a read-and-print of the
    ``Trade`` ``PaperTradingEngine.submit_order()`` already returned
    -- no new computation.
    """
    print("Order FILLED.")
    print(f"  trade_id   : {trade.trade_id}")
    print(f"  order_id   : {trade.order_id}")
    print(f"  symbol     : {trade.symbol}")
    print(f"  action     : {trade.action}")
    print(f"  quantity   : {trade.quantity}")
    print(f"  fill_price : {trade.fill_price}")
    print(f"  fee        : {trade.fee}")
    print(f"  tax        : {trade.tax}")
    print(f"  executed_at: {trade.executed_at}")


def _run_post_trade_snapshot_and_reconciliation(app, account_id: str) -> int:
    """Activation 7 FIX (blockers 2 and 3): after a real trade has
    already committed (``PaperTradingEngine.submit_order()`` already
    returned successfully), capture a real portfolio snapshot and
    reconcile the account -- both through this graph's already-real,
    already-LOCKED ``portfolio_snapshot_service``/
    ``reconciliation_engine``, never re-implemented here.

    This is the "production flow yang sudah ada" this fix wires into:
    the existing ``paper buy``/``paper sell`` CLI commands, at the
    one moment account state is guaranteed to have just changed for
    real. No scheduler, no cadence decision, no daemon is introduced
    -- this only runs when a trade is actually submitted through the
    CLI, exactly as often as that already happens.

    Trading is never affected by anything in this function: the
    ``Trade`` this call follows is already committed and already
    returned to the caller before this function is even invoked, and
    nothing here can undo, retry, or re-validate it.

    Blocker 2 (snapshot): ``PortfolioSnapshotService.take_snapshot()``
    reads real, already-persisted ``Account``/``Position`` state and
    a real current market price (via ``UnrealizedPnLEngine`` /
    ``MarketPriceTool``) -- it can genuinely fail (e.g. a real price
    lookup fails) rather than ever persist a fabricated number (see
    its own docstring). A failure here is logged, not raised further
    -- consistent with "never fabricate a snapshot": if a real one
    cannot be built, none is written, and that absence is visible in
    the log rather than silent.

    Blocker 3 (reconciliation): ``ReconciliationEngine.
    reconcile_account()`` is called with no ``starting_cash`` (this
    function invents no cash-history tracking that doesn't already
    exist -- see the engine's own documented "not_verifiable"
    behavior for the Trade<->Cash invariant without an anchor). If
    the result is INCONSISTENT, that is printed as a clear, labelled
    failure and this function returns a non-zero status -- visible to
    the operator, never swallowed -- while the trade itself remains
    fully committed regardless.

    Returns:
        ``0`` if the snapshot was captured and reconciliation reports
        CONSISTENT (or was not fully verifiable, which is not a
        failure -- see the engine's own semantics). Non-zero if
        reconciliation reports INCONSISTENT. A snapshot failure alone
        does not, by itself, change this return value -- it is
        logged and the reconciliation check still runs and still
        governs the return value.
    """
    try:
        app.portfolio_snapshot_service.take_snapshot(account_id)
    except Exception:
        logger.error(
            "Portfolio snapshot failed for account_id=%s after trade -- "
            "trade remains committed; no snapshot row was written.",
            account_id,
            exc_info=True,
        )

    result = app.reconciliation_engine.reconcile_account(account_id)
    if not result.consistent:
        print("RECONCILIATION FAILURE: account state is INCONSISTENT.")
        for violation in result.violations:
            print(f"  - {violation}")
        logger.error(
            "Reconciliation FAILED for account_id=%s: %s",
            account_id,
            result.violations,
        )
        return 1
    return 0


def _parse_symbol_and_flag(argv: list[str], flag: str) -> tuple[Optional[str], Optional[str]]:
    """Parse ``SYMBOL --FLAG VALUE`` in either order (Activation 4
    Session 1). Purely argv parsing -- mirrors the small inline
    ``--market``-parsing loop ``_run_scan_command`` already uses
    above, generalized to one positional + one named flag so
    ``_run_paper_buy_command``/``_run_paper_sell_command`` do not each
    duplicate it.
    """
    symbol: Optional[str] = None
    value: Optional[str] = None
    i = 0
    while i < len(argv):
        if argv[i] == flag and i + 1 < len(argv):
            value = argv[i + 1]
            i += 2
        elif not argv[i].startswith("--"):
            symbol = argv[i]
            i += 1
        else:
            i += 1
    return symbol, value


def _resolve_account_id_for_symbol(symbol: str) -> str:
    """Resolve which paper account a ``paper buy``/``paper sell`` order
    for ``symbol`` belongs to (Activation 7 Crypto Validation
    Profile).

    Uses the shared, LOCKED ``Core.market_config.is_crypto_symbol()``
    allowlist -- the same recognizer ``MarketAnalysisSkill`` already
    routes on -- so this CLI-layer resolution can never silently
    disagree with the rest of the codebase about what counts as
    "crypto". A recognized crypto symbol (``BTC-USD``/``ETH-USD``,
    case-insensitive) resolves to ``DEFAULT_CRYPTO_ACCOUNT_ID``
    (``"crypto-usd"``); everything else resolves to
    ``DEFAULT_PAPER_ACCOUNT_ID`` (``"paper"``, the unchanged default
    every pre-Activation-7 stock order already used). Read-only,
    no I/O, never raises.
    """
    if is_crypto_symbol(symbol):
        return DEFAULT_CRYPTO_ACCOUNT_ID
    return DEFAULT_PAPER_ACCOUNT_ID


def _normalized_forex_pair_or_none(symbol: str) -> Optional[str]:
    """Return ``symbol`` normalized to canonical ``"BASE/QUOTE"`` form if,
    and only if, it is one of the currently supported Forex pairs
    (Activation 11.22).

    Delegates entirely to the existing, LOCKED Forex pair-universe
    source of truth -- ``Business.forex_pip_policy._normalize_pair``
    (well-formedness + normalization) and ``...SUPPORTED_PIP_VALUE_PAIRS``
    (the actual supported-pair allowlist, currently exactly
    ``"EUR/USD"``/``"GBP/USD"``) -- the same pair universe
    ``Business.forex_order_preview.preview_forex_order`` already uses.
    No second pair list is introduced here. Never raises: a malformed
    or unsupported pair simply returns ``None`` so the CLI layer can
    print its own usage-style rejection message, matching how the
    ``"us"``/``"crypto"`` branches already handle an invalid symbol.
    """
    try:
        normalized = _normalize_pair(symbol)
    except ValidationError:
        return None
    if normalized not in SUPPORTED_PIP_VALUE_PAIRS:
        return None
    return normalized


def _parse_paper_order_args(
    argv: list[str], value_flag: str
) -> tuple[Optional[str], Optional[str], str, Optional[str], Optional[str]]:
    """Parse ``SYMBOL --VALUE_FLAG X [--market idx|us] [--executed-at TS]
    [--stop-loss PRICE]`` in any order (Activation 9.2; ``--executed-at``
    added in Activation 9.4 Step 2; ``--stop-loss`` added in
    Activation 11.23).

    Generalizes ``_parse_symbol_and_flag`` with three more optional
    named flags, ``--market``, ``--executed-at``, and ``--stop-loss``,
    so ``paper buy``/``paper sell`` can be told which account/market
    an order belongs to (the same explicit way ``scan --market
    idx|us`` already is), optionally a deterministic execution
    timestamp to use instead of the real wall clock, and optionally a
    stop-loss price to forward to ``PaperTradingEngine.submit_order()``
    -- CLI-layer parsing only, no defaulting/validation beyond
    returning the raw strings (or ``"idx"`` if ``--market`` was
    omitted, and ``None`` if ``--executed-at``/``--stop-loss`` were
    omitted, reproducing every pre-Activation-9.4 call exactly for the
    first two). Symbol-sniffing (guessing US vs IDX from ticker shape
    alone) is deliberately not used here: both markets use short
    all-letter tickers (e.g. IDX ``BBCA`` vs US ``AAPL``), so only an
    explicit flag can disambiguate them -- the same reason ``scan``
    already requires an explicit ``--market`` rather than inferring
    one.

    Args:
        argv: The command's argument list, minus the subcommand itself.
        value_flag: The named flag for this command's other value
            (``"--allocation"`` for buy, ``"--quantity"`` for sell).

    Returns:
        ``(symbol, value, market, executed_at, stop_loss)`` --
        ``symbol``/``value``/``executed_at``/``stop_loss`` are
        ``None`` if not found (mirrors ``_parse_symbol_and_flag``);
        ``market`` is always a string, lower-cased, defaulting to
        ``"idx"``. ``executed_at``/``stop_loss`` are returned exactly
        as supplied on the command line, unparsed and unvalidated --
        callers are responsible for parsing/validating them against
        the existing contracts (this generalizes the same pattern
        ``executed_at`` already uses).
    """
    symbol: Optional[str] = None
    value: Optional[str] = None
    market = "idx"
    executed_at: Optional[str] = None
    stop_loss_raw: Optional[str] = None
    i = 0
    while i < len(argv):
        if argv[i] == value_flag and i + 1 < len(argv):
            value = argv[i + 1]
            i += 2
        elif argv[i] == "--market" and i + 1 < len(argv):
            market = argv[i + 1].strip().lower()
            i += 2
        elif argv[i] == "--executed-at" and i + 1 < len(argv):
            executed_at = argv[i + 1]
            i += 2
        elif argv[i] == "--stop-loss" and i + 1 < len(argv):
            stop_loss_raw = argv[i + 1]
            i += 2
        elif not argv[i].startswith("--"):
            symbol = argv[i]
            i += 1
        else:
            i += 1
    return symbol, value, market, executed_at, stop_loss_raw


def _resolve_stop_loss(stop_loss_raw: Optional[str]) -> tuple[Optional[float], bool]:
    """Resolve the ``--stop-loss`` CLI value a ``paper buy``/``paper
    sell`` order should submit with (Activation 11.23).

    When ``stop_loss_raw`` is ``None`` (``--stop-loss`` was not
    supplied on the command line), returns ``(None, True)`` so
    ``submit_order()``'s existing ``stop_loss=None`` default is
    preserved byte-for-byte for every pre-Activation-11.23 call site.

    When ``stop_loss_raw`` is supplied, it is parsed as a float using
    the project's existing numeric-parsing convention (the same bare
    ``float(...)`` conversion ``--allocation``/``--quantity`` already
    use). On success, returns ``(value, True)``. On failure, returns
    ``(None, False)`` so the caller can fail the command cleanly
    before ``submit_order()`` is ever called -- this function performs
    no directional (BUY-below-entry / SELL-above-entry) validation;
    that remains solely the Forex engine's responsibility.

    Returns:
        ``(stop_loss, ok)`` -- ``ok`` is ``False`` only when
        ``stop_loss_raw`` was supplied but was not a valid number.
    """
    if stop_loss_raw is None:
        return None, True
    try:
        return float(stop_loss_raw), True
    except ValueError:
        return None, False


def _resolve_executed_at(executed_at_raw: Optional[str]) -> Optional[str]:
    """Resolve the ``executed_at`` timestamp a ``paper buy``/``paper
    sell`` order should submit with (Activation 9.4 Step 2).

    When ``executed_at_raw`` is ``None`` (``--executed-at`` was not
    supplied on the command line), this reproduces the exact
    pre-Activation-9.4 production default:
    ``datetime.now(timezone.utc).isoformat()``.

    When ``executed_at_raw`` is supplied, it is validated with the
    same ``datetime.fromisoformat`` parser
    ``PaperTradingEngine``/``Business.trade_holding_period_engine``
    already use to interpret ``executed_at`` (see that module's
    ``fromisoformat`` usage) -- no new datetime-parsing utility is
    introduced. On success, the raw supplied string is returned
    unchanged so it reaches ``PaperTradingEngine.submit_order()``
    byte-for-byte. On failure, ``None`` is returned so the caller can
    fail the command cleanly -- this function never falls back to
    ``datetime.now()`` for an invalid supplied value.
    """
    if executed_at_raw is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        datetime.fromisoformat(executed_at_raw)
    except ValueError:
        return None
    return executed_at_raw


def _run_paper_buy_command(app, argv: list[str]) -> int:
    """``python main.py paper buy SYMBOL --allocation X`` (Activation
    4 Session 1).

    Flow (LOCKED, roadmap-mandated): reads the actual account cash
    (never ``capital=0``), computes an IDX lot-adjusted quantity
    estimate from ``--allocation`` and a real current price, then
    submits through ``PaperTradingEngine.submit_order()`` -- the sole
    validator and sole writer. Running this command IS the explicit
    user approval (``user_approval=True`` is passed because the
    command itself was only just typed by the user after reviewing
    'recommendation' output) -- see roadmap section 7 / audit poin 7.
    """
    from Business.execution_policy_config import load_execution_policy

    symbol, allocation_raw, market, executed_at_raw, stop_loss_raw = _parse_paper_order_args(argv, "--allocation")
    if symbol is None or allocation_raw is None:
        print(
            "Usage: python main.py paper buy SYMBOL --allocation X [--market idx|us|crypto|forex] "
            "[--executed-at TIMESTAMP] [--stop-loss PRICE]"
        )
        return 1

    stop_loss, stop_loss_ok = _resolve_stop_loss(stop_loss_raw)
    if not stop_loss_ok:
        print(f"Invalid --stop-loss value: {stop_loss_raw!r} (must be a number)")
        return 1
    symbol = symbol.upper()
    if market not in ("idx", "us", "crypto", "forex"):
        print(f"Unsupported market: {market!r} (supported: 'idx', 'us', 'crypto', 'forex')")
        return 1

    try:
        allocation = float(allocation_raw)
    except ValueError:
        print(f"Invalid --allocation value: {allocation_raw!r} (must be a number, e.g. 0.05 for 5%)")
        return 1
    if allocation <= 0:
        print(f"Invalid --allocation value: {allocation} (must be > 0)")
        return 1

    # Activation 9.2: US paper orders route to the 'us-usd' account
    # (Core.bootstrap.ensure_default_us_account / 'init-us') instead
    # of the default IDR 'paper' account, and use a whole-share
    # (lot_size=1) estimate instead of the IDX 100-share lot --
    # matching PaperTradingEngine gate 6's own "us" bypass. IDX's own
    # branch (market == "idx", still the default) is byte-for-byte
    # what this command already did before this Activation.
    # Activation 10.1: a third, explicit ``market == "crypto"`` branch,
    # mirroring the existing "us" branch's shape exactly (its own
    # symbol-format validation, its own account routing) rather than
    # inventing a new pattern. Crypto's "symbol-format validation" is
    # the existing, shared ``Core.market_config.is_crypto_symbol()``
    # allowlist (``BTC-USD``/``ETH-USD``) -- the same recognizer
    # ``MarketAnalysisSkill`` already routes on -- so this CLI layer
    # can never disagree with the rest of the codebase about what
    # counts as a valid crypto symbol. Routes to the existing
    # ``DEFAULT_CRYPTO_ACCOUNT_ID`` ("crypto-usd") constant from
    # ``Core.bootstrap`` (already created by ``init-crypto`` /
    # ``ensure_default_crypto_account``) -- no new account id is
    # invented here.
    if market == "us":
        if not is_valid_us_symbol(symbol):
            print(f"'{symbol}' is not a recognized US ticker format (1-5 letters, optional share-class suffix).")
            return 1
        account_id = DEFAULT_US_ACCOUNT_ID
    elif market == "crypto":
        if not is_crypto_symbol(symbol):
            print(f"'{symbol}' is not a recognized crypto symbol (supported: BTC-USD, ETH-USD).")
            return 1
        account_id = DEFAULT_CRYPTO_ACCOUNT_ID
    elif market == "forex":
        # Activation 11.22: mirrors the "us"/"crypto" branches' own
        # shape exactly (its own symbol-format validation, its own
        # account routing). Symbol-format validation reuses the
        # existing, LOCKED Forex pair-universe source of truth
        # (Business.forex_pip_policy) -- no second pair list is
        # introduced. Routes to the existing DEFAULT_FOREX_ACCOUNT_ID
        # ("forex-usd") constant from Core.bootstrap (already created
        # by "init-forex" / ensure_default_forex_account) -- no new
        # account id is invented here.
        normalized_pair = _normalized_forex_pair_or_none(symbol)
        if normalized_pair is None:
            print(
                f"'{symbol}' is not a recognized Forex pair "
                f"(supported: {', '.join(SUPPORTED_PIP_VALUE_PAIRS)})."
            )
            return 1
        symbol = normalized_pair
        account_id = DEFAULT_FOREX_ACCOUNT_ID
    else:
        account_id = DEFAULT_PAPER_ACCOUNT_ID

    account = app.account_repository.get_by_id(account_id)
    if account is None:
        init_hint = (
            "init-us" if market == "us" else "init-crypto" if market == "crypto"
            else "init-forex" if market == "forex" else "init"
        )
        print(f"Account '{account_id}' not found. Run 'python main.py {init_hint}' first.")
        return 1

    snapshot = _latest_snapshot_for_symbol(app, symbol)
    if snapshot is None or snapshot.status == "error":
        print(
            f"No usable recommendation for {symbol}. Run 'python main.py scan --market {market}' "
            f"then 'python main.py recommendation {symbol}' before approving a trade."
        )
        return 1

    # AIOS_MARKET is read by every market-aware provider-symbol call
    # site this command triggers, not only by PaperTradingEngine's own
    # gate 6 (lot size) / gate 13 (market kill switch):
    # ``_fetch_current_price()`` (via ``resolve_provider_symbol()``)
    # and the post-trade ``_run_post_trade_snapshot_and_reconciliation()``
    # snapshot price lookup both resolve provider symbols under
    # whatever ``AIOS_MARKET`` is active at the moment they run.
    # Activation 9.5 STEP 2: this scope is widened to cover the entire
    # US paper-order workflow -- price fetch through submission through
    # post-trade snapshot -- so a US order can no longer have its price
    # fetched or its post-trade snapshot resolved under a stale/default
    # "idx" market context (which previously mis-resolved a bare US
    # ticker like "AAPL" to "AAPL.JK"). Set only for "us" (IDX's
    # existing default path never touches this env var), and always
    # restored via this single ``finally``, so this command still
    # leaves no process-wide side effect behind.
    # AIOS_MARKET is read by every market-aware provider-symbol call
    # site this command triggers, not only by PaperTradingEngine's own
    # gate 6 (lot size) / gate 13 (market kill switch):
    # ``_fetch_current_price()`` (via ``resolve_provider_symbol()``)
    # and the post-trade ``_run_post_trade_snapshot_and_reconciliation()``
    # snapshot price lookup both resolve provider symbols under
    # whatever ``AIOS_MARKET`` is active at the moment they run.
    # Activation 9.5 STEP 2: this scope is widened to cover the entire
    # US paper-order workflow -- price fetch through submission through
    # post-trade snapshot -- so a US order can no longer have its price
    # fetched or its post-trade snapshot resolved under a stale/default
    # "idx" market context (which previously mis-resolved a bare US
    # ticker like "AAPL" to "AAPL.JK"). Activation 10.1 extends this
    # same scoped-environment mechanism to "crypto" for exactly the
    # same reason: without it, ``_fetch_current_price()`` and the
    # post-trade snapshot's price lookup would resolve
    # ``resolve_provider_symbol("BTC-USD")`` under whatever market was
    # already active (defaulting to "idx"), mis-resolving it to
    # "BTC-USD.JK". Activation 11.22 extends this same scoped-
    # environment mechanism to "forex" for exactly the same reason.
    # Set only for "us"/"crypto"/"forex" (IDX's existing default path
    # never touches this env var), and always restored via this single
    # ``finally``, so this command still leaves no process-wide side
    # effect behind.
    previous_aios_market = os.environ.get("AIOS_MARKET")
    if market in ("us", "crypto", "forex"):
        os.environ["AIOS_MARKET"] = market
    try:
        price = _fetch_current_price(app, symbol)
        if price is None:
            print(f"Could not obtain a real current price for {symbol}. Order not submitted.")
            return 1

        execution_policy = load_execution_policy()
        # Crypto and US must not use the IDX 100-share lot convention
        # (PaperTradingEngine gate 6 already bypasses its own
        # lot-size check entirely for market == "crypto"/"us"; this
        # CLI-layer estimate must not reintroduce one). No new
        # quantity-precision/step-size abstraction is added -- this
        # reuses the exact same whole-unit ``_compute_allocation_quantity``
        # helper the "us" branch already uses. Forex (Activation
        # 11.24) is now included in this same bypass: gate 6 now has
        # its own Forex-specific "whole base-currency units" check
        # (Activation 11.1's LOCKED "quantity = base-currency units
        # directly" decision -- no standard/mini/micro broker-lot
        # conversion), so this CLI-layer estimate must stop rounding
        # Forex quantity to a multiple of the IDX lot size, or a
        # realistic allocation (e.g. 5% of cash into EUR/USD) would be
        # silently truncated down to the nearest 100 units for no
        # Forex-specific reason. ``lot_size=1`` here reuses the exact
        # same whole-unit rounding ``_compute_allocation_quantity``
        # already performs for "us"/"crypto" (``math.floor`` down to a
        # whole unit) -- consistent with gate 6's own "whole
        # base-currency units" rule, no fractional Forex quantity is
        # introduced.
        lot_size = 1 if market in ("us", "crypto", "forex") else execution_policy.lot_size
        quantity = _compute_allocation_quantity(account.cash, allocation, price, lot_size)
        if quantity <= 0:
            unit = (
                "share" if market == "us" else "unit" if market == "crypto"
                else "base-currency unit" if market == "forex" else f"IDX lot ({lot_size} shares)"
            )
            print(
                f"Allocation {allocation:.2%} of cash {account.cash} at price {price} does not "
                f"afford even one {unit}. Order not submitted."
            )
            return 1

        print(
            f"Estimated: BUY {quantity} shares of {symbol} @ {price} "
            f"(allocation {allocation:.2%} of actual cash {account.cash})"
        )
        print("Typing 'paper buy' is the explicit user approval -- submitting now.")

        executed_at = _resolve_executed_at(executed_at_raw)
        if executed_at is None:
            print(f"Invalid --executed-at value: {executed_at_raw!r} (must be an ISO-8601 timestamp)")
            return 1

        idempotency_key = f"cli-buy-{symbol}-{uuid.uuid4()}"
        try:
            trade = app.paper_trading_engine.submit_order(
                account_id=account_id,
                symbol=symbol,
                action=_PAPER_BUY,
                quantity=quantity,
                requested_price=price,
                executed_at=executed_at,
                signal_evidence=snapshot,
                user_approval=True,
                idempotency_key=idempotency_key,
                stop_loss=stop_loss,
            )
        except ValidationError as exc:
            print(f"Order rejected: {exc.message} (reason={exc.details.get('reason')})")
            return 1

        _print_trade_result(trade)
        return _run_post_trade_snapshot_and_reconciliation(app, account_id)
    finally:
        if market in ("us", "crypto", "forex"):
            if previous_aios_market is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = previous_aios_market


def _run_paper_sell_command(app, argv: list[str]) -> int:
    """``python main.py paper sell SYMBOL --quantity X`` (Activation 4
    Session 1).

    Quantity is caller-supplied directly (no allocation calculation
    on the SELL side -- the roadmap's allocation formula is BUY-only,
    "quantity dihitung dari actual cash"). Submits through
    ``PaperTradingEngine.submit_order()`` -- the sole validator
    (including the "available position untuk SELL" gate) and sole
    writer. Running this command IS the explicit user approval, same
    as 'paper buy'.
    """
    symbol, quantity_raw, market, executed_at_raw, stop_loss_raw = _parse_paper_order_args(argv, "--quantity")
    if symbol is None or quantity_raw is None:
        print(
            "Usage: python main.py paper sell SYMBOL --quantity X [--market idx|us|crypto|forex] "
            "[--executed-at TIMESTAMP] [--stop-loss PRICE]"
        )
        return 1

    stop_loss, stop_loss_ok = _resolve_stop_loss(stop_loss_raw)
    if not stop_loss_ok:
        print(f"Invalid --stop-loss value: {stop_loss_raw!r} (must be a number)")
        return 1
    symbol = symbol.upper()
    if market not in ("idx", "us", "crypto", "forex"):
        print(f"Unsupported market: {market!r} (supported: 'idx', 'us', 'crypto', 'forex')")
        return 1

    try:
        quantity = float(quantity_raw)
    except ValueError:
        print(f"Invalid --quantity value: {quantity_raw!r} (must be a number)")
        return 1
    if quantity <= 0:
        print(f"Invalid --quantity value: {quantity} (must be > 0)")
        return 1

    # Activation 9.2 / 10.1 / 11.22: see the matching comment in
    # _run_paper_buy_command.
    if market == "us":
        if not is_valid_us_symbol(symbol):
            print(f"'{symbol}' is not a recognized US ticker format (1-5 letters, optional share-class suffix).")
            return 1
        account_id = DEFAULT_US_ACCOUNT_ID
    elif market == "crypto":
        if not is_crypto_symbol(symbol):
            print(f"'{symbol}' is not a recognized crypto symbol (supported: BTC-USD, ETH-USD).")
            return 1
        account_id = DEFAULT_CRYPTO_ACCOUNT_ID
    elif market == "forex":
        normalized_pair = _normalized_forex_pair_or_none(symbol)
        if normalized_pair is None:
            print(
                f"'{symbol}' is not a recognized Forex pair "
                f"(supported: {', '.join(SUPPORTED_PIP_VALUE_PAIRS)})."
            )
            return 1
        symbol = normalized_pair
        account_id = DEFAULT_FOREX_ACCOUNT_ID
    else:
        account_id = DEFAULT_PAPER_ACCOUNT_ID

    account = app.account_repository.get_by_id(account_id)
    if account is None:
        init_hint = (
            "init-us" if market == "us" else "init-crypto" if market == "crypto"
            else "init-forex" if market == "forex" else "init"
        )
        print(f"Account '{account_id}' not found. Run 'python main.py {init_hint}' first.")
        return 1

    snapshot = _latest_snapshot_for_symbol(app, symbol)
    if snapshot is None or snapshot.status == "error":
        print(
            f"No usable recommendation for {symbol}. Run 'python main.py scan --market {market}' "
            f"then 'python main.py recommendation {symbol}' before approving a trade."
        )
        return 1

    # See the matching comment in _run_paper_buy_command: this scope
    # (Activation 9.5 STEP 2, extended to "crypto" by Activation 10.1
    # and to "forex" by Activation 11.22) is widened to cover price
    # fetch through submission through the post-trade snapshot, so
    # both ``_fetch_current_price()`` and
    # ``_run_post_trade_snapshot_and_reconciliation()`` resolve
    # provider symbols under the correct "us"/"crypto"/"forex" market
    # context, not just ``submit_order()`` itself.
    previous_aios_market = os.environ.get("AIOS_MARKET")
    if market in ("us", "crypto", "forex"):
        os.environ["AIOS_MARKET"] = market
    try:
        price = _fetch_current_price(app, symbol)
        if price is None:
            print(f"Could not obtain a real current price for {symbol}. Order not submitted.")
            return 1

        print(f"Estimated: SELL {quantity} shares of {symbol} @ {price}")
        print("Typing 'paper sell' is the explicit user approval -- submitting now.")

        executed_at = _resolve_executed_at(executed_at_raw)
        if executed_at is None:
            print(f"Invalid --executed-at value: {executed_at_raw!r} (must be an ISO-8601 timestamp)")
            return 1

        idempotency_key = f"cli-sell-{symbol}-{uuid.uuid4()}"
        try:
            trade = app.paper_trading_engine.submit_order(
                account_id=account_id,
                symbol=symbol,
                action=_PAPER_SELL,
                quantity=quantity,
                requested_price=price,
                executed_at=executed_at,
                signal_evidence=snapshot,
                user_approval=True,
                idempotency_key=idempotency_key,
                stop_loss=stop_loss,
            )
        except ValidationError as exc:
            print(f"Order rejected: {exc.message} (reason={exc.details.get('reason')})")
            return 1

        _print_trade_result(trade)
        return _run_post_trade_snapshot_and_reconciliation(app, account_id)
    finally:
        if market in ("us", "crypto", "forex"):
            if previous_aios_market is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = previous_aios_market


def _run_paper_command(app, argv: list[str]) -> int:
    """``python main.py paper <buy|sell> SYMBOL --allocation/--quantity X``
    (Activation 4 Session 1) -- dispatcher, mirrors
    ``_run_watchlist_command``'s subcommand pattern.
    """
    if not argv:
        print("Usage: python main.py paper <buy|sell> SYMBOL --allocation/--quantity X")
        return 1
    subcommand, rest = argv[0], argv[1:]
    if subcommand == "buy":
        return _run_paper_buy_command(app, rest)
    if subcommand == "sell":
        return _run_paper_sell_command(app, rest)
    print(f"Unknown paper subcommand: {subcommand!r} (expected 'buy' or 'sell')")
    return 1


def _print_portfolio_positions(app) -> None:
    """Display every position on the paper account (Activation 4
    Session 2).

    Reads ``app.position_repository.list_by_account()`` -- the exact,
    unmodified Sprint 4 repository (LOCKED) -- so this always shows
    real ``Position`` state, never a fabricated or cached one. For
    each ``OPEN`` position, also calls
    ``app.unrealized_pnl_engine.calculate(position)`` (Activation 4
    Session 2 wiring; the engine itself is LOCKED, Activation 3.7
    STEP 4) to show a real current market price and unrealized P/L.
    If the engine cannot obtain a real market price for a symbol, the
    unrealized fields are shown as ``N/A`` -- never invented (mirrors
    ``_print_recommendation``'s existing ``N/A`` convention).
    ``realized_pnl`` always comes straight from the ``Position`` row
    itself (settled by actual ``Trade``s), regardless of market data
    availability.
    """
    positions = app.position_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
    if not positions:
        print("No positions.")
        return

    print(f"Portfolio ({len(positions)} position(s)):")
    for position in positions:
        print(
            f"  {position.symbol}  qty={position.quantity}  "
            f"avg_price={position.average_price}  status={position.status}  "
            f"realized_pnl={position.realized_pnl}"
        )
        if position.status == "open":
            try:
                pnl_result = app.unrealized_pnl_engine.calculate(position)
            except ValidationError:
                print("      market_price=N/A  unrealized_pnl=N/A (no current market price available)")
                continue
            print(
                f"      market_price={pnl_result.market_price}  "
                f"unrealized_pnl={pnl_result.unrealized_pnl}  "
                f"as_of={pnl_result.market_timestamp}"
            )


def _run_portfolio_command(app, argv: list[str]) -> int:
    """``python main.py portfolio`` (Activation 4 Session 2).

    Read-only. No argument is parsed -- ``argv`` is accepted only to
    mirror every other one-shot command's dispatch signature.
    """
    _print_portfolio_positions(app)
    return 0


def _run_account_command(app, argv: list[str]) -> int:
    """``python main.py account`` (Activation 4 Session 2).

    Read-only. Prints the real ``Account`` row for the paper account
    via the existing, unmodified ``AccountRepository.get_by_id()`` --
    no balance is computed here, all figures are read verbatim.
    """
    account = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
    if account is None:
        print(f"Account '{DEFAULT_PAPER_ACCOUNT_ID}' not found. Run 'python main.py init' first.")
        return 1

    print(f"Account -- {account.account_id}")
    print(f"  name         : {account.account_name}")
    print(f"  mode         : {account.mode}")
    print(f"  currency     : {account.currency}")
    print(f"  asset_class  : {account.asset_class}")
    print(f"  cash         : {account.cash}")
    print(f"  equity       : {account.equity}")
    print(f"  buying_power : {account.buying_power}")
    print(f"  created_at   : {account.created_at}")
    print(f"  updated_at   : {account.updated_at}")
    return 0


def _run_orders_command(app, argv: list[str]) -> int:
    """``python main.py orders`` (Activation 4 Session 2).

    Read-only. Prints every ``Order`` on the paper account via the
    existing, unmodified ``OrderRepository.list_by_account()`` --
    includes each order's real ``status``/``filled_price``/
    ``filled_quantity``/``filled_at``, never re-derived here.
    """
    orders = app.order_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
    if not orders:
        print("No orders.")
        return 0

    print(f"Orders ({len(orders)}):")
    for order in orders:
        print(
            f"  order_id={order.order_id}  symbol={order.symbol}  action={order.action}  "
            f"quantity={order.quantity}  status={order.status}  reason={order.reason}"
        )
        print(
            f"      filled_price={order.filled_price}  filled_quantity={order.filled_quantity}  "
            f"filled_at={order.filled_at}"
        )
    return 0


def _run_trades_command(app, argv: list[str]) -> int:
    """``python main.py trades`` (Activation 4 Session 2).

    Read-only. Prints every ``Trade`` on the paper account via the
    existing, unmodified ``TradeRepository.list_by_account()`` --
    ``Trade`` is an append-only ledger (LOCKED, Sprint 4 STEP 4), so
    this is always the real, immutable execution history.
    """
    trades = app.trade_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
    if not trades:
        print("No trades.")
        return 0

    print(f"Trades ({len(trades)}):")
    for trade in trades:
        print(
            f"  trade_id={trade.trade_id}  order_id={trade.order_id}  symbol={trade.symbol}  "
            f"action={trade.action}  quantity={trade.quantity}  fill_price={trade.fill_price}"
        )
        print(
            f"      fee={trade.fee}  tax={trade.tax}  executed_at={trade.executed_at}"
        )
    return 0


def main() -> None:
    # Activation 1.5 LOCKED DECISION OVERRIDE (supersedes the Stage 9.4
    # contract): validation occurs at the command boundary, not at
    # application startup. The provider-credential check that used to run
    # once, globally, before this loop even started is now deferred to the
    # two REPL commands that actually reach the AI provider ("auto " and
    # plain chat input). "scan" never touches app.agent/app.provider_name
    # (source: ManualScanService's five collaborators are
    # WatchlistScanner/RankingEngine/RecommendationService/ReportService/
    # SnapshotRepository -- no provider anywhere in that chain), so it must
    # not be blocked by a missing GEMINI_API_KEY/OLLAMA_HOST.
    # build_application() itself stays unconditional and ungated here -- it
    # is already hermetic (Stage 9.0 lock: succeeds with no secrets/network/
    # optional package present) and is needed to construct ``app`` for
    # every command, including "scan".
    app = build_application()
    logger.info(
        f"Application ready -- agent='{app.agent_name}' "
        f"provider='{app.provider_name}'"
    )

    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.startswith("auto "):
            # Uses app.autonomous_agent -> the active provider: validate
            # only here, right before the command that needs it.
            validate_runtime_environment()
            parts = user_input.split()
            ticker = parts[1]
            iterations = int(parts[2]) if len(parts) > 2 else 1
            _run_autonomous(app, ticker, iterations)
            continue
        if user_input == "scan":
            # No provider dependency -- must run even when
            # GEMINI_API_KEY/OLLAMA_HOST is unset (Activation 1.5, Section 3).
            _run_manual_scan(app)
            continue
        # Falls through to app.agent.chat(), which uses the active provider.
        validate_runtime_environment()
        reply = app.agent.chat(user_input)
        print(reply)


def _extract_cli_market(argv: list[str]) -> str:
    """Return the CLI market flag, defaulting to the existing IDX behavior."""
    i = 0
    while i < len(argv):
        if argv[i] == "--market" and i + 1 < len(argv):
            return argv[i + 1].lower()
        i += 1
    return "idx"


def _configure_cli_market(argv: list[str]) -> int:
    """Configure process environment before ApplicationGraph construction.

    Activation 10.1: ``"crypto"`` is now an accepted top-level
    ``--market`` value alongside the existing ``"idx"``/``"us"``, so
    ``python main.py paper buy BTC-USD --market crypto`` no longer
    dies here -- at the single dispatch-level gate shared by both
    ``scan`` and ``paper`` -- before ever reaching
    ``_run_paper_buy_command``/``_run_paper_sell_command``'s own
    per-command handling. ``idx``/``us`` behavior (including the
    ``EXECUTION_LOT_SIZE`` override, which crypto does not need --
    ``PaperTradingEngine`` gate 6 already bypasses the lot-size check
    entirely for ``market == "crypto"``, and the paper-order commands
    compute their own crypto quantity directly) is unchanged.
    """
    market = _extract_cli_market(argv)
    if market not in ("idx", "us", "crypto", "forex"):
        print(f"Unsupported market: {market!r} (supported: 'idx', 'us', 'crypto', 'forex')")
        return 1
    os.environ["AIOS_MARKET"] = market
    if market == "us":
        os.environ["EXECUTION_LOT_SIZE"] = "1"
    else:
        os.environ.pop("EXECUTION_LOT_SIZE", None)
    return 0


if __name__ == "__main__":
    # Activation 1.2: "python main.py doctor" is a diagnostic command --
    # it must run even when the environment is NOT yet ready (that is
    # the whole point), so it is dispatched here, before main()'s
    # build_application() call, rather than from inside the REPL loop.
    # (Activation 1.5: main()'s provider check is no longer an
    # unconditional gate at all -- it now runs per command boundary,
    # inside the REPL loop, only for "auto "/chat -- see main()'s body.)
    # Any other argv (including none) falls through to the existing,
    # unchanged main() behavior.
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.exit(run_doctor_command())
    # Activation 1.3: "python main.py init" has the identical need --
    # it must be runnable on a brand new environment where the database
    # does not exist yet and no provider is configured, so it is
    # dispatched here too, before the same gate, for the same reason.
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        sys.exit(run_init())
    # Activation 9.3 STEP 3: "python main.py init-us" wires the existing,
    # unmodified Core.init_us_command.run_init_us() into canonical CLI
    # dispatch -- same pattern and same reasoning as "init" immediately
    # above (must be runnable standalone, before build_application()/any
    # provider check, and exits with run_init_us()'s own status code).
    # No db_config is passed here, so run_init_us() falls back to
    # DatabaseConfig.from_env() -- byte-for-byte the same canonical
    # config source "init" (run_init(), same fallback) already uses;
    # this never introduces a second DB path/config mechanism. Remains
    # explicit opt-in: "init" above is completely untouched and still
    # never creates the 'us-usd' account itself.
    if len(sys.argv) > 1 and sys.argv[1] == "init-us":
        sys.exit(run_init_us())
    # Activation 11.21: "python main.py init-forex" wires the existing,
    # unmodified Core.init_forex_command.run_init_forex() into canonical
    # CLI dispatch -- same pattern and same reasoning as "init-us"
    # immediately above (must be runnable standalone, before
    # build_application()/any provider check, and exits with
    # run_init_forex()'s own status code). No db_config is passed here,
    # so run_init_forex() falls back to DatabaseConfig.from_env() --
    # byte-for-byte the same canonical config source "init"/"init-us"
    # already use; this never introduces a second DB path/config
    # mechanism. Remains explicit opt-in: "init" above is completely
    # untouched and still never creates the 'forex-usd' account itself.
    # This step is account-bootstrap scope only -- it does not wire
    # "--market forex" into "scan"/"paper buy"/"paper sell", which
    # remain unchanged and still reject "forex" as an unsupported
    # market (see those commands' own market allowlists below).
    if len(sys.argv) > 1 and sys.argv[1] == "init-forex":
        sys.exit(run_init_forex())
    # Activation 7 FIX blocker 3: "python main.py backup" has the same
    # need -- it must be runnable without a fully-ready environment
    # (no provider required) and without build_application(), so it is
    # dispatched here too, before the same gate, for the same reason.
    # Manual only -- never invoked from any other command's dispatch
    # branch below.
    if len(sys.argv) > 1 and sys.argv[1] == "backup":
        sys.exit(_run_backup_command(sys.argv[2:]))
    # Section 2.8 CLI scanner: "watchlist add/list" and "scan --market idx"
    # are one-shot argv commands, dispatched here before the REPL loop --
    # same pattern as "doctor"/"init" above. Both need a real ``app``
    # (WatchlistRepository / ManualScanService), unlike "doctor"/"init",
    # so build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "watchlist":
        _app = build_application()
        sys.exit(_run_watchlist_command(_app, sys.argv[2:]))
    # Activation 12, Phase 3: "preference set/get/list" is a one-shot argv
    # command, dispatched here -- same pattern as "watchlist" immediately
    # above. Needs a real ``app`` (the already-built ``app.memory_store``),
    # so build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL. Reuses
    # the single ApplicationGraph-constructed MemoryStore -- no second
    # store, no persistence, no financial-state access.
    if len(sys.argv) > 1 and sys.argv[1] == "preference":
        _app = build_application()
        sys.exit(_run_preference_command(_app, sys.argv[2:]))
    # Activation 12 Memory (Strategy Notes): "strategy-note add/list" is
    # a one-shot argv command, dispatched here -- same pattern as
    # "preference" immediately above. Needs a real ``app`` (the
    # already-built ``app.memory_store``), so build_application() runs
    # first, then the process exits with the command's own status code
    # instead of falling into the REPL. Reuses the single
    # ApplicationGraph-constructed MemoryStore -- no second store, no
    # persistence, no financial-state access.
    if len(sys.argv) > 1 and sys.argv[1] == "strategy-note":
        _app = build_application()
        sys.exit(_run_strategy_note_command(_app, sys.argv[2:]))
    # Activation 12 Memory (Previous Decisions): "previous-decision
    # add/list" is a one-shot argv command, dispatched here -- same
    # pattern as "strategy-note" immediately above. Needs a real ``app``
    # (the already-built ``app.memory_store``), so build_application()
    # runs first, then the process exits with the command's own status
    # code instead of falling into the REPL. Reuses the single
    # ApplicationGraph-constructed MemoryStore -- no second store, no
    # persistence, no financial-state access.
    if len(sys.argv) > 1 and sys.argv[1] == "previous-decision":
        _app = build_application()
        sys.exit(_run_previous_decision_command(_app, sys.argv[2:]))
    # Activation 12 Memory (Lessons From Failed Trades): "lesson add/list"
    # is a one-shot argv command, dispatched here -- same pattern as
    # "previous-decision" immediately above. Needs a real ``app`` (the
    # already-built ``app.memory_store``), so build_application() runs
    # first, then the process exits with the command's own status code
    # instead of falling into the REPL. Reuses the single
    # ApplicationGraph-constructed MemoryStore -- no second store, no
    # persistence, no financial-state access. This is user-authored
    # passive memory only: no automatic failed-trade lesson generation.
    if len(sys.argv) > 1 and sys.argv[1] == "lesson":
        _app = build_application()
        sys.exit(_run_lesson_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        _argv = sys.argv[2:]
        rc = _configure_cli_market(_argv)
        if rc:
            sys.exit(rc)
        _app = build_application()
        sys.exit(_run_scan_command(_app, _argv))
    # Activation 4 Session 1: "recommendation SYMBOL" and "paper
    # buy/sell ..." are one-shot argv commands, dispatched here --
    # same pattern as "watchlist"/"scan" immediately above. Both need
    # a real ``app`` (SnapshotRepository / AccountRepository /
    # PositionRepository / PaperTradingEngine / MarketPriceTool), so
    # build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "recommendation":
        _app = build_application()
        sys.exit(_run_recommendation_command(_app, sys.argv[2:]))
    # Phase B ("Decision Copilot"): "brief" is a one-shot, read-mostly
    # argv command, dispatched here -- same pattern as "recommendation"
    # immediately above. Needs a real app (decision_brief_service via
    # snapshot_repository/watchlist_repository/market_price_tool), so
    # build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "brief":
        _app = build_application()
        sys.exit(_run_brief_command(_app, sys.argv[2:]))
    # Phase C ("Personal Risk Ledger + Decision Journal"): "risk-limits"
    # and "journal" are one-shot argv commands, dispatched here -- same
    # pattern as "brief" immediately above. Both need a real app
    # (risk_limits_repository / journal_service), so build_application()
    # runs first, then the process exits with the command's own status
    # code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "risk-limits":
        _app = build_application()
        sys.exit(_run_risk_limits_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "journal":
        _app = build_application()
        sys.exit(_run_journal_command(_app, sys.argv[2:]))
    # Phase H Task 1 ("Observation Window + Sustained-Use Review
    # Record"): "observation-window" is a one-shot argv command,
    # dispatched here -- same pattern as "journal"/"risk-limits"
    # immediately above. Needs a real app (observation_window_service),
    # so build_application() runs first, then the process exits with
    # the command's own status code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "observation-window":
        _app = build_application()
        sys.exit(_run_observation_window_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "paper":
        _argv = sys.argv[2:]
        rc = _configure_cli_market(_argv)
        if rc:
            sys.exit(rc)
        _app = build_application()
        sys.exit(_run_paper_command(_app, _argv))
    # Activation 4 Session 2: "portfolio"/"account"/"orders"/"trades"
    # are one-shot, read-only argv commands, dispatched here -- same
    # pattern as "recommendation"/"paper" immediately above. Each
    # needs a real ``app`` (PositionRepository+UnrealizedPnLEngine /
    # AccountRepository / OrderRepository / TradeRepository), so
    # build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL.
    if len(sys.argv) > 1 and sys.argv[1] == "portfolio":
        _app = build_application()
        sys.exit(_run_portfolio_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "account":
        _app = build_application()
        sys.exit(_run_account_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "orders":
        _app = build_application()
        sys.exit(_run_orders_command(_app, sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "trades":
        _app = build_application()
        sys.exit(_run_trades_command(_app, sys.argv[2:]))
    # Activation 6.4: "report daily" is a one-shot argv command,
    # dispatched here -- same pattern as "portfolio"/"account"/
    # "orders"/"trades" immediately above. Needs a real ``app``
    # (ManualScanService / PerformanceSummaryProductionService /
    # NotificationBuilder / NotificationManager, via
    # DailyReportOrchestrator), so build_application() runs first,
    # then the process exits with the command's own status code
    # instead of falling into the REPL. Also serves as this
    # pipeline's manual retry entry point -- running the same
    # command again re-runs the whole chain from a fresh scan.
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        _app = build_application()
        sys.exit(_run_report_command(_app, sys.argv[2:]))
    # Activation 12 Scheduler, atomic step 1: "scheduler tick" is a
    # one-shot argv command, dispatched here -- same pattern as
    # "report" immediately above. Needs a real ``app`` (the
    # already-built ``app.scheduler``, plus the ``manual_scan_service``/
    # ``performance_summary_production_service`` singletons the three
    # scheduled jobs reuse), so build_application() runs first, then
    # the process exits with the command's own status code instead of
    # falling into the REPL. Manual trigger only -- no background
    # scheduling, no daemon, no cron is introduced by this dispatch.
    if len(sys.argv) > 1 and sys.argv[1] == "scheduler":
        _app = build_application()
        sys.exit(_run_scheduler_command(_app, sys.argv[2:]))
    # Phase E Task 6 ("Wire the existing Telegram inbound control
    # plane"): "telegram poll"/"telegram status" are one-shot argv
    # commands, dispatched here -- same pattern as "scheduler"
    # immediately above. Needs a real ``app`` (the already-built
    # ``app.telegram_inbound_control_plane``/
    # ``app.telegram_allowlist_policy``/
    # ``app.telegram_inbound_state_repository``/
    # ``app.telegram_command_audit_repository``, all wired in Task 6),
    # so build_application() runs first, then the process exits with
    # the command's own status code instead of falling into the REPL.
    # Every existing command above is unchanged and unaffected by this
    # addition.
    if len(sys.argv) > 1 and sys.argv[1] == "telegram":
        _app = build_application()
        sys.exit(_run_telegram_command(_app, sys.argv[2:]))
    # Phase H Task 4 ("Operator Feedback + Final Review Record"):
    # "sustained-use-final feedback"/"sustained-use-final decide" are
    # one-shot argv commands, dispatched here -- same pattern as
    # "observation-window"/"telegram" immediately above. Needs a real
    # app (app.sustained_use_final_review_service), so
    # build_application() runs first, then the process exits with the
    # command's own status code instead of falling into the REPL.
    # Read-only viewing stays under the existing
    # "report sustained-use-final" dispatch above -- this adds only
    # the two explicit, human-driven write commands the Task 4
    # roadmap calls for. Neither ever mutates a trading, risk-limit,
    # or permission table.
    if len(sys.argv) > 1 and sys.argv[1] == "sustained-use-final":
        _app = build_application()
        sys.exit(_run_sustained_use_final_command(_app, sys.argv[2:]))
    main()