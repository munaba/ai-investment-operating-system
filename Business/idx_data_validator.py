"""L1 Data Quality Validator for IDX OHLCV data.

Explicit rejection of invalid data - never silent correction.
Validates: rentang nilai, gap kalender bursa, duplikat, data basi.

Integration points:
- Called after StockDataRepository.get_history() returns data
- Uses IDXMarketCalendar for trading day gap detection
- Returns ValidationResult with explicit rejection reasons
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, FrozenSet


@dataclass(frozen=True)
class ValidationRejection:
    """Single rejection reason with context."""
    rule_id: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of L1 validation - either passes or has explicit rejections."""
    passed: bool
    rejections: List[ValidationRejection] = field(default_factory=list)
    
    def __bool__(self) -> bool:
        return self.passed


class IDXDataValidator:
    """L1 validator for IDX OHLCV data quality.
    
    Rules (all explicit reject, never silent correct):
    - V001: OHLC values must be positive (no negative prices)
    - V002: Volume must be non-negative
    - V003: High >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close
    - V004: No duplicate (date, symbol) pairs in payload
    - V005: No gaps vs trading calendar (missing trading days)
    - V006: Data not stale (within acceptable age window)
    
    Usage:
        validator = IDXDataValidator(calendar)
        result = validator.validate_ohlcv(records, symbol, max_age_days=5)
        if not result:
            for r in result.rejections:
                print(f"REJECTED: {r.rule_id} - {r.message}")
    """
    
    #: Maximum acceptable ROE value (1000% = 10.0 as decimal)
    MAX_ROE: float = 10.0
    #: Maximum acceptable PER value  
    MAX_PER: float = 1000.0
    #: Default max age for data freshness (days)
    DEFAULT_MAX_AGE_DAYS: int = 5
    
    def __init__(
        self,
        calendar: Optional[Any] = None,
        max_age_days: Optional[int] = None,
    ) -> None:
        """Initialize validator with optional calendar for gap detection.
        
        Args:
            calendar: IDXMarketCalendar instance for trading day checks.
            max_age_days: Maximum acceptable data age in days.
        """
        self._calendar = calendar
        self._max_age_days = max_age_days or self.DEFAULT_MAX_AGE_DAYS
    
    def validate_ohlcv(
        self,
        records: List[Dict[str, Any]],
        symbol: str,
        max_age_days: Optional[int] = None,
    ) -> ValidationResult:
        """Validate OHLCV records against all L1 rules.
        
        Args:
            records: List of OHLCV dicts with keys: Date, Open, High, Low, Close, Volume
            symbol: Ticker symbol for error messages
            max_age_days: Override max acceptable age
            
        Returns:
            ValidationResult with passed=True or explicit rejections
        """
        rejections: List[ValidationRejection] = []
        
        if not records:
            rejections.append(ValidationRejection(
                rule_id="V000",
                message=f"Empty data payload for symbol '{symbol}'",
                details={"symbol": symbol, "record_count": 0},
            ))
            return ValidationResult(passed=False, rejections=rejections)
        
        # V001, V002, V003: Per-record validation
        for i, rec in enumerate(records):
            idx = i + 1
            rec_rejections = self._validate_single_record(rec, symbol, idx)
            rejections.extend(rec_rejections)
        
        # V004: Duplicate detection
        dup_rejections = self._check_duplicates(records, symbol)
        rejections.extend(dup_rejections)
        
        # V005: Gap detection (requires calendar)
        if self._calendar is not None:
            gap_rejections = self._check_calendar_gaps(records, symbol)
            rejections.extend(gap_rejections)
        
        # V006: Stale data check
        age_days = max_age_days or self._max_age_days
        stale_rejections = self._check_staleness(records, symbol, age_days)
        rejections.extend(stale_rejections)
        
        passed = len(rejections) == 0
        return ValidationResult(passed=passed, rejections=rejections)
    
    def validate_fundamentals(
        self,
        per: Optional[float],
        roe: Optional[float],
        dividend_yield: Optional[float],
        symbol: str,
    ) -> ValidationResult:
        """Validate fundamental metrics (PER, ROE, dividend yield).
        
        Args:
            per: Price-to-Earnings Ratio
            roe: Return on Equity (as decimal, e.g., 0.15 = 15%)
            dividend_yield: Dividend yield (as decimal)
            symbol: Ticker symbol for error messages
            
        Returns:
            ValidationResult for fundamental data
        """
        rejections: List[ValidationRejection] = []
        
        # ROE bounds check
        if roe is not None:
            if roe < -1.0:  # More than -100% loss
                rejections.append(ValidationRejection(
                    rule_id="V010",
                    message=f"ROE {roe:.4f} (< -100%) is implausibly low for '{symbol}'",
                    details={"symbol": symbol, "roe": roe, "min": -1.0},
                ))
            elif roe > self.MAX_ROE:
                rejections.append(ValidationRejection(
                    rule_id="V011",
                    message=f"ROE {roe:.4f} (> {self.MAX_ROE*100:.0f}%) is implausibly high for '{symbol}'",
                    details={"symbol": symbol, "roe": roe, "max": self.MAX_ROE},
                ))
        
        # PER bounds check (allow negative for loss-making companies)
        if per is not None and per > self.MAX_PER:
            rejections.append(ValidationRejection(
                rule_id="V012",
                message=f"PER {per:.2f} exceeds maximum threshold {self.MAX_PER} for '{symbol}'",
                details={"symbol": symbol, "per": per, "max": self.MAX_PER},
            ))
        
        # Dividend yield bounds check
        if dividend_yield is not None:
            if dividend_yield < 0:
                rejections.append(ValidationRejection(
                    rule_id="V013",
                    message=f"Dividend yield {dividend_yield:.4f} is negative for '{symbol}'",
                    details={"symbol": symbol, "dividend_yield": dividend_yield},
                ))
            elif dividend_yield > 1.0:  # > 100%
                rejections.append(ValidationRejection(
                    rule_id="V014",
                    message=f"Dividend yield {dividend_yield:.4f} (> 100%) is implausible for '{symbol}'",
                    details={"symbol": symbol, "dividend_yield": dividend_yield, "max": 1.0},
                ))
        
        passed = len(rejections) == 0
        return ValidationResult(passed=passed, rejections=rejections)
    
    def _validate_single_record(
        self,
        rec: Dict[str, Any],
        symbol: str,
        idx: int,
    ) -> List[ValidationRejection]:
        """Validate a single OHLCV record (V001, V002, V003)."""
        rejections: List[ValidationRejection] = []
        
        open_val = rec.get("Open")
        high_val = rec.get("High")
        low_val = rec.get("Low")
        close_val = rec.get("Close")
        volume_val = rec.get("Volume")
        rec_date = rec.get("Date", "unknown")
        
        # V001: Positive OHLC prices
        for name, val in [("Open", open_val), ("High", high_val), 
                          ("Low", low_val), ("Close", close_val)]:
            if val is not None and val < 0:
                rejections.append(ValidationRejection(
                    rule_id="V001",
                    message=f"Negative {name} price {val} at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "field": name, "value": val, "date": str(rec_date)},
                ))
        
        # V002: Non-negative volume
        if volume_val is not None and volume_val < 0:
            rejections.append(ValidationRejection(
                rule_id="V002",
                message=f"Negative volume {volume_val} at record {idx} for '{symbol}'",
                details={"symbol": symbol, "record_idx": idx, "volume": volume_val, "date": str(rec_date)},
            ))
        
        # V003: High/Low consistency
        if all(v is not None for v in [high_val, low_val]):
            if high_val < low_val:
                rejections.append(ValidationRejection(
                    rule_id="V003",
                    message=f"High ({high_val}) < Low ({low_val}) at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "high": high_val, "low": low_val, "date": str(rec_date)},
                ))
        
        # V003: High >= Open, Close
        if high_val is not None:
            if open_val is not None and high_val < open_val:
                rejections.append(ValidationRejection(
                    rule_id="V003",
                    message=f"High ({high_val}) < Open ({open_val}) at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "high": high_val, "open": open_val, "date": str(rec_date)},
                ))
            if close_val is not None and high_val < close_val:
                rejections.append(ValidationRejection(
                    rule_id="V003",
                    message=f"High ({high_val}) < Close ({close_val}) at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "high": high_val, "close": close_val, "date": str(rec_date)},
                ))
        
        # V003: Low <= Open, Close
        if low_val is not None:
            if open_val is not None and low_val > open_val:
                rejections.append(ValidationRejection(
                    rule_id="V003",
                    message=f"Low ({low_val}) > Open ({open_val}) at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "low": low_val, "open": open_val, "date": str(rec_date)},
                ))
            if close_val is not None and low_val > close_val:
                rejections.append(ValidationRejection(
                    rule_id="V003",
                    message=f"Low ({low_val}) > Close ({close_val}) at record {idx} for '{symbol}'",
                    details={"symbol": symbol, "record_idx": idx, "low": low_val, "close": close_val, "date": str(rec_date)},
                ))
        
        return rejections
    
    def _check_duplicates(
        self,
        records: List[Dict[str, Any]],
        symbol: str,
    ) -> List[ValidationRejection]:
        """V004: Check for duplicate (date, symbol) pairs."""
        rejections: List[ValidationRejection] = []
        seen_dates: Dict[Any, int] = {}
        
        for i, rec in enumerate(records):
            rec_date = rec.get("Date")
            if rec_date is None:
                continue
            
            # Normalize date to string for comparison
            date_key = str(rec_date)
            
            if date_key in seen_dates:
                prev_idx = seen_dates[date_key]
                rejections.append(ValidationRejection(
                    rule_id="V004",
                    message=f"Duplicate date {date_key} for '{symbol}' at records {prev_idx} and {i+1}",
                    details={"symbol": symbol, "date": date_key, "first_idx": prev_idx, "second_idx": i+1},
                ))
            else:
                seen_dates[date_key] = i + 1
        
        return rejections
    
    def _check_calendar_gaps(
        self,
        records: List[Dict[str, Any]],
        symbol: str,
    ) -> List[ValidationRejection]:
        """V005: Check for gaps vs trading calendar."""
        rejections: List[ValidationRejection] = []
        
        if not records or self._calendar is None:
            return rejections
        
        # Extract and sort dates
        dates: List[date] = []
        for rec in records:
            rec_date = rec.get("Date")
            if rec_date is None:
                continue
            # Handle various date formats
            if isinstance(rec_date, date):
                dates.append(rec_date)
            elif isinstance(rec_date, datetime):
                dates.append(rec_date.date())
            elif isinstance(rec_date, str):
                try:
                    # Try ISO format first
                    dates.append(date.fromisoformat(rec_date[:10]))
                except ValueError:
                    continue
        
        if len(dates) < 2:
            return rejections
        
        dates.sort()
        
        # Check each gap between consecutive dates
        gaps_found: List[Dict[str, Any]] = []
        for i in range(len(dates) - 1):
            current = dates[i]
            next_date = dates[i + 1]
            
            # Count trading days between
            expected_days = 0
            check_date = current + timedelta(days=1)
            while check_date < next_date:
                if self._calendar.is_trading_day(check_date):
                    expected_days += 1
                check_date += timedelta(days=1)
            
            if expected_days > 0:
                gaps_found.append({
                    "from": str(current),
                    "to": str(next_date),
                    "missing_trading_days": expected_days,
                })
        
        if gaps_found:
            total_missing = sum(g["missing_trading_days"] for g in gaps_found)
            rejections.append(ValidationRejection(
                rule_id="V005",
                message=f"Found {len(gaps_found)} gap(s) totaling {total_missing} missing trading days for '{symbol}'",
                details={"symbol": symbol, "gap_count": len(gaps_found), "total_missing_days": total_missing, "gaps": gaps_found[:5]},
            ))
        
        return rejections
    
    def _check_staleness(
        self,
        records: List[Dict[str, Any]],
        symbol: str,
        max_age_days: int,
    ) -> List[ValidationRejection]:
        """V006: Check if data is stale (too old)."""
        rejections: List[ValidationRejection] = []
        
        if not records:
            return rejections
        
        # Find the most recent date in records
        latest_date: Optional[date] = None
        for rec in records:
            rec_date = rec.get("Date")
            if rec_date is None:
                continue
            
            parsed: Optional[date] = None
            if isinstance(rec_date, date):
                parsed = rec_date
            elif isinstance(rec_date, datetime):
                parsed = rec_date.date()
            elif isinstance(rec_date, str):
                try:
                    parsed = date.fromisoformat(rec_date[:10])
                except ValueError:
                    continue
            
            if parsed is not None:
                if latest_date is None or parsed > latest_date:
                    latest_date = parsed
        
        if latest_date is None:
            return rejections
        
        # Check age
        today = date.today()
        age_days = (today - latest_date).days
        
        if age_days > max_age_days:
            rejections.append(ValidationRejection(
                rule_id="V006",
                message=f"Data for '{symbol}' is {age_days} days old (max: {max_age_days})",
                details={"symbol": symbol, "latest_date": str(latest_date), "age_days": age_days, "max_age_days": max_age_days},
            ))
        
        return rejections
