"""
Phase I Gate 1 — DecisionCopilotSkill (Read-Only).

A new skill extending BaseSkill that analyzes historical patterns from the
JournalRepository. Designed strictly under fail-closed permissions:
it performs no LLM/provider calls, makes no trade plan, issues no orders,
and contains no live execution/broker paths.

It explicitly does NOT construct or mutate any Capability enum, respecting
the lockdown on Orchestration/capability.py.
"""

from typing import Any, List, Set, Dict, Optional
from collections import defaultdict
from datetime import datetime

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult
from Repository.persistence.journal_repository import JournalRepository
from Database.models import JournalEntry


class DecisionCopilotSkill(BaseSkill):
    """
    Read-only decision support skill analyzing historical journal patterns.
    """

    def __init__(self, journal_repository: JournalRepository) -> None:
        self._repo = journal_repository

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
            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
            until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
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
                decided_dt = datetime.fromisoformat(entry.decided_at.replace("Z", "+00:00"))
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
            "filter_semantics": "in-memory filter over JournalRepository.list_all(); repository exposes no account_id/since/until parameters",
            "read_only": True,
        }

        metadata = {
            "capability": "analyze_historical_patterns",
            "read_only": True,
            "account_id": account_id.strip(),
        }

        return SkillResult(success=True, output=output, metadata=metadata)
