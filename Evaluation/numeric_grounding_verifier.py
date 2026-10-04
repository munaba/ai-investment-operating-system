"""L4 Numeric Grounding Verifier -- extract numbers from LLM output and verify against source data.

Detects:
- Format Indonesia: 1.234,56 dan 15%
- Format English: 1,234.56 dan 15%
- Unverified numbers (no match in source within tolerance)

Target: recall >= 99% on synthetic test set.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple, Optional


class NumericGroundingResult:
    def __init__(self):
        self.extracted_numbers: List[Tuple[str, Decimal]] = []
        self.verified: List[Tuple[str, Decimal, str]] = []  # (text, value, source_key)
        self.unverified: List[Tuple[str, Decimal]] = []  # (text, value)
        self.hallucinations: List[Tuple[str, Decimal]] = []  # alias for unverified
    
    @property
    def all_verified(self) -> bool:
        # Zero extracted numbers is vacuously verified (no claim made).
        return len(self.unverified) == 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "extracted_count": len(self.extracted_numbers),
            "verified_count": len(self.verified),
            "unverified_count": len(self.unverified),
            "all_verified": self.all_verified,
            "unverified_numbers": [(text, float(val)) for text, val in self.unverified],
        }


def extract_numbers(text: str) -> List[Tuple[str, Decimal]]:
    """Extract numbers from text (Indonesian and English formats).
    
    Returns:
        List of (original_text, normalized_decimal) tuples.
    """
    results: List[Tuple[str, Decimal]] = []
    
    # Pattern: optional minus, digits with any separators (must end in digit
    # or %, so trailing separators like "3.106,6," are not swallowed).
    pattern = r'-?\d(?:[\d.,]*\d)?%?'
    
    for match in re.finditer(pattern, text):
        raw = match.group(0)
        normalized = _normalize_number(raw)
        if normalized is not None:
            results.append((raw, normalized))
    
    return results


def _normalize_number(text: str) -> Optional[Decimal]:
    """Convert Indonesian/English number string to Decimal.
    
    Examples:
        "1.234,56" -> Decimal("1234.56")
        "1,234.56" -> Decimal("1234.56")
        "15%" -> Decimal("0.15")
        "-1.234,56" -> Decimal("-1234.56")
    """
    text = text.strip()
    is_percent = text.endswith('%')
    if is_percent:
        text = text[:-1].strip()
    
    # Count periods and commas
    period_count = text.count('.')
    comma_count = text.count(',')
    
    # Detect format
    if period_count == 0 and comma_count == 0:
        # Plain integer
        normalized = text
    elif period_count > 0 and comma_count == 0:
        # Could be English decimal (1.23) or Indonesian thousands (1.234)
        # Heuristic: if period is followed by 3 digits at end, it's thousands separator
        if re.search(r'\.\d{3}$', text):
            # Indonesian thousands: 1.234 -> 1234
            normalized = text.replace('.', '')
        else:
            # English decimal: 1.23
            normalized = text
    elif comma_count > 0 and period_count == 0:
        # Could be Indonesian decimal (1,23) or English thousands (1,234)
        if re.search(r',\d{3}$', text):
            # English thousands: 1,234 -> 1234
            normalized = text.replace(',', '')
        else:
            # Indonesian decimal: 1,23 -> 1.23
            normalized = text.replace(',', '.')
    else:
        # Both present: determine which is decimal separator
        # Last separator is decimal, others are thousands
        last_period_pos = text.rfind('.')
        last_comma_pos = text.rfind(',')
        
        if last_comma_pos > last_period_pos:
            # Indonesian: 1.234,56 -> 1234.56
            normalized = text.replace('.', '').replace(',', '.')
        else:
            # English: 1,234.56 -> 1234.56
            normalized = text.replace(',', '')
    
    try:
        dec = Decimal(normalized)
        if is_percent:
            dec = dec / 100
        return dec
    except (InvalidOperation, ValueError):
        return None


def verify_against_source(
    text: str,
    source_data: Dict[str, Any],
    tolerance: float = 0.01,
) -> NumericGroundingResult:
    """Verify numbers in text against source data.
    
    Args:
        text: LLM output text to verify.
        source_data: Dict of source facts (flat or nested).
        tolerance: Relative tolerance for matching (default 1%).
    
    Returns:
        NumericGroundingResult with verified/unverified numbers.
    """
    result = NumericGroundingResult()
    extracted = extract_numbers(text)
    result.extracted_numbers = extracted
    
    # Flatten source data to list of (key, value) pairs
    source_numbers = _flatten_source(source_data)
    
    for raw_text, value in extracted:
        matched = False
        for source_key, source_val in source_numbers:
            if _numbers_match(value, source_val, tolerance):
                result.verified.append((raw_text, value, source_key))
                matched = True
                break
        
        if not matched:
            result.unverified.append((raw_text, value))
            result.hallucinations.append((raw_text, value))
    
    return result


def _flatten_source(data: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Decimal]]:
    """Flatten nested dict to list of (key_path, Decimal) pairs."""
    results: List[Tuple[str, Decimal]] = []
    
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        
        if isinstance(value, dict):
            results.extend(_flatten_source(value, full_key))
        elif isinstance(value, (int, float, Decimal)):
            try:
                results.append((full_key, Decimal(str(value))))
            except (InvalidOperation, ValueError):
                continue
        elif isinstance(value, str):
            # Try to parse string as number
            normalized = _normalize_number(value)
            if normalized is not None:
                results.append((full_key, normalized))
    
    return results


def _numbers_match(a: Decimal, b: Decimal, tolerance: float) -> bool:
    """Check if two numbers match within relative tolerance.
    
    Args:
        a, b: Numbers to compare.
        tolerance: Relative tolerance (e.g., 0.01 = 1%).
    
    Returns:
        True if |a - b| / |b| <= tolerance (or both are zero).
    """
    if a == b:
        return True
    
    if b == 0:
        return abs(a) <= tolerance
    
    rel_diff = abs((a - b) / b)
    return rel_diff <= Decimal(str(tolerance))


def compute_metrics(
    tp: int,
    fn: int,
    fp: int,
    tn: int,
) -> Dict[str, float]:
    """Compute recall and FPR from confusion matrix.
    
    Args:
        tp: True positives (hallucinations detected).
        fn: False negatives (hallucinations missed).
        fp: False positives (correct numbers marked unverified).
        tn: True negatives (correct numbers accepted).
    
    Returns:
        Dict with 'recall' and 'fpr' keys.
    
    Example:
        tp=98, fn=2, fp=1, tn=999
        recall = 98/(98+2) = 0.98
        fpr = 1/(1+999) = 0.001
    """
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return {"recall": recall, "fpr": fpr}


# ponytail: no narrate_explanation hook integration yet.
# Hook integration requires Services/ audit.
