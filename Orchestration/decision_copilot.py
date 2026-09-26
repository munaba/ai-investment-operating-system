"""
Phase I Gate 1 — DecisionCopilotSkill (Read-Only).
Phase I Gate 2 — adds analyze_evidence_profile (read-only evidence profiling).

A skill extending BaseSkill that analyzes historical patterns from the
JournalRepository and evidence composition from PerformanceRepository.
Designed strictly under fail-closed permissions:
it performs no LLM/provider calls, makes no trade plan, issues no orders,
and contains no live execution/broker paths.

It explicitly does NOT construct or mutate any Capability enum, respecting
the lockdown on Orchestration/capability.py.
"""

import json
from typing import Any, List, Set, Dict, Optional
from collections import defaultdict
from datetime import datetime, timezone

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult
from Repository.persistence.journal_repository import JournalRepository
from Repository.persistence.performance_repository import PerformanceRepository
from Database.models import JournalEntry, RankingSnapshot


def _parse_utc_aware(raw: Any) -> datetime:
    """Parse an ISO-8601 value into a **tz-aware UTC** datetime.

    Database timestamps (``scan_time``, ``decided_at``) are UTC-aware ISO
    strings carrying an explicit offset. A bound supplied without one (e.g.
    ``"2026-09-01"`` or ``"2026-09-01 00:00:00"``) parses to a *naive*
    datetime, and comparing naive against aware always raises ``TypeError``.

    Naive input is therefore interpreted as UTC, which is exactly what every
    writer in this codebase already does
    (``datetime.now(timezone.utc).isoformat()``).

    Raises ``ValueError``/``TypeError`` on unparseable input; every caller
    already converts those into an explicit ``DATA_ERROR``.
    """
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class DecisionCopilotSkill(BaseSkill):
    """
    Read-only decision support skill analyzing historical journal patterns.
    """

    def __init__(
        self,
        journal_repository: JournalRepository,
        performance_repository: Optional[PerformanceRepository] = None,
    ) -> None:
        self._repo = journal_repository
        self._perf_repo = performance_repository

    @property
    def name(self) -> str:
        return "decision_copilot"

    @property
    def description(self) -> str:
        return "Read-only analysis of historical journal patterns for an account over a date range."

    def execute(self, context: Any) -> SkillResult:
        """
        Extract parameters from the context and delegate to analyze_historical_patterns.
        """
        try:
            params = getattr(context, "parameters", {})
            if not isinstance(params, dict):
                return SkillResult(success=False, error="INSUFFICIENT_DATA")
            
            account_id = params.get("account_id")
            since = params.get("since")
            until = params.get("until")

            return self.analyze_historical_patterns(account_id, since, until)
        except Exception:
            return SkillResult(success=False, error="INSUFFICIENT_DATA")

    def analyze_historical_patterns(
        self, account_id: Any, since: Any, until: Any
    ) -> SkillResult:
        """
        Analyze historical journal patterns within a specific date range.

        Note on filter_semantics:
        The underlying JournalRepository exposes no account_id, since, or until 
        parameters in its read methods. This method performs an in-memory filter 
        over the results of `list_all()`.
        """
        if not isinstance(account_id, str) or not account_id.strip():
            return SkillResult(success=False, error="INSUFFICIENT_DATA")

        try:
            since_dt = _parse_utc_aware(since)
            until_dt = _parse_utc_aware(until)
            if since_dt > until_dt:
                return SkillResult(success=False, error="DATA_ERROR")
        except (ValueError, TypeError):
            return SkillResult(success=False, error="DATA_ERROR")

        try:
            all_entries = self._repo.list_all()
        except Exception:
            return SkillResult(success=False, error="DATA_ERROR")

        # In-memory filter.
        # Note: JournalEntry currently has no account_id field in its model
        # (per Database/models.py L697-750), so filtering by account_id is 
        # technically vacuous for JournalEntry itself. We still enforce the 
        # date range on decided_at.
        filtered_entries: List[JournalEntry] = []
        for entry in all_entries:
            try:
                decided_dt = _parse_utc_aware(entry.decided_at)
                if since_dt <= decided_dt <= until_dt:
                    filtered_entries.append(entry)
            except (ValueError, TypeError, AttributeError):
                continue

        if not filtered_entries:
            return SkillResult(success=False, error="INSUFFICIENT_DATA")

        decision_counts: Dict[str, int] = defaultdict(int)
        symbols: Set[str] = set()

        for entry in filtered_entries:
            decision = getattr(entry, "decision", "UNKNOWN")
            decision_counts[decision] += 1
            if hasattr(entry, "symbol") and entry.symbol:
                symbols.add(entry.symbol)

        distinct_decisions = sorted(list(decision_counts.keys()))

        output = {
            "account_id": account_id.strip(),
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "entry_count": len(filtered_entries),
            "symbol_count": len(symbols),
            "decision_counts": dict(decision_counts),
            "distinct_decisions": distinct_decisions,
            "filter_semantics": "in-memory filter over JournalRepository.list_all() by decided_at range only; account_id is validated and echoed but NOT used to filter rows \u2014 JournalEntry has no account_id column, and this system is single-account by design (AGENTS.md)",
            "read_only": True,
        }

        metadata = {
            "capability": "analyze_historical_patterns",
            "read_only": True,
            "account_id": account_id.strip(),
        }

        return SkillResult(success=True, output=output, metadata=metadata)

    def analyze_evidence_profile(
        self, since: Any = None, until: Any = None
    ) -> SkillResult:
        """
        Profile evidence composition behind past ranking snapshots.

        Descriptive aggregation of already-computed RankingEngine outputs;
        no re-ranking, no re-scoring, no current recommendation.
        No account_id parameter — single-account by design.
        """
        if self._perf_repo is None:
            return SkillResult(success=False, error="INSUFFICIENT_DATA")

        since_dt: Optional[datetime] = None
        until_dt: Optional[datetime] = None

        if since is not None:
            try:
                since_dt = _parse_utc_aware(since)
            except (ValueError, TypeError):
                return SkillResult(success=False, error="DATA_ERROR")

        if until is not None:
            try:
                until_dt = _parse_utc_aware(until)
            except (ValueError, TypeError):
                return SkillResult(success=False, error="DATA_ERROR")

        if since_dt is not None and until_dt is not None and since_dt > until_dt:
            return SkillResult(success=False, error="DATA_ERROR")

        try:
            all_snapshots: List[RankingSnapshot] = self._perf_repo.get_all_snapshots()
        except Exception:
            return SkillResult(success=False, error="DATA_ERROR")

        # In-memory filter by scan_time range
        filtered: List[RankingSnapshot] = []
        for snap in all_snapshots:
            try:
                scan_dt = _parse_utc_aware(snap.scan_time)
            except (ValueError, TypeError, AttributeError):
                continue
            if since_dt is not None and scan_dt < since_dt:
                continue
            if until_dt is not None and scan_dt > until_dt:
                continue
            filtered.append(snap)

        if not filtered:
            return SkillResult(success=False, error="INSUFFICIENT_DATA")

        # Descriptive aggregation
        scan_times: Set[str] = set()
        symbols: Set[str] = set()
        status_counts: Dict[str, int] = defaultdict(int)
        recommendation_counts: Dict[str, int] = defaultdict(int)
        confidence_counts: Dict[str, int] = defaultdict(int)
        factor_totals: Dict[str, float] = defaultdict(float)
        error_row_count = 0
        unparsed_breakdown_count = 0

        scan_time_min: Optional[datetime] = None
        scan_time_max: Optional[datetime] = None

        for snap in filtered:
            scan_times.add(str(snap.scan_time))
            if hasattr(snap, "symbol") and snap.symbol:
                symbols.add(str(snap.symbol))

            status = getattr(snap, "status", "success") or "success"
            status_counts[status] += 1

            if status != "success":
                error_row_count += 1
            else:
                # Only count recommendation/confidence for success rows
                # to avoid a None bucket from error rows
                rec = getattr(snap, "recommendation", None)
                if rec is not None:
                    recommendation_counts[str(rec)] += 1
                conf = getattr(snap, "confidence", None)
                if conf is not None:
                    confidence_counts[str(conf)] += 1

            # scan_time min/max
            try:
                dt = _parse_utc_aware(snap.scan_time)
                if scan_time_min is None or dt < scan_time_min:
                    scan_time_min = dt
                if scan_time_max is None or dt > scan_time_max:
                    scan_time_max = dt
            except (ValueError, TypeError):
                pass

            # factor contributions from score_breakdown_json
            raw = getattr(snap, "score_breakdown_json", None)
            if raw is not None:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if k.endswith("_contribution") and isinstance(v, (int, float)):
                                factor_totals[k] += v
                except (json.JSONDecodeError, TypeError, ValueError):
                    unparsed_breakdown_count += 1

        output = {
            "since": since_dt.isoformat() if since_dt is not None else None,
            "until": until_dt.isoformat() if until_dt is not None else None,
            "scan_count": len(scan_times),
            "snapshot_count": len(filtered),
            "symbol_count": len(symbols),
            "symbols": sorted(list(symbols)),
            "scan_time_min": scan_time_min.isoformat() if scan_time_min is not None else None,
            "scan_time_max": scan_time_max.isoformat() if scan_time_max is not None else None,
            "status_counts": dict(status_counts),
            "recommendation_counts": dict(recommendation_counts),
            "confidence_counts": dict(confidence_counts),
            "factor_contribution_totals": dict(factor_totals),
            "error_row_count": error_row_count,
            "unparsed_breakdown_count": unparsed_breakdown_count,
            "read_only": True,
            "profile_semantics": "descriptive aggregation of already-computed RankingEngine outputs; no re-ranking, no re-scoring, no current recommendation",
        }

        metadata = {
            "capability": "analyze_evidence_profile",
            "read_only": True,
        }

        return SkillResult(success=True, output=output, metadata=metadata)
