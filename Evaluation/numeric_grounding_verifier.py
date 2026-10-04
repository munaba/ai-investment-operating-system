"""L4 Numeric Grounding Verifier -- extract numbers from LLM output and verify against source data.

Detects:
- Format Indonesia: 1.234,56 dan 15%
- Format English: 1,234.56 dan 15%
- Unverified numbers (no match in source within tolerance)

Target: recall >= 99% on synthetic test set.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

_THRESHOLDS = json.loads(
    (Path(__file__).resolve().parent / "thresholds.json").read_text(encoding="utf-8")
)
_L4 = _THRESHOLDS["L4_llm"]

#: THE SINGLE RULE (thresholds.json "L4_llm.grounding_rule").
#:
#:   A claim is GROUNDED iff, after rendering the source value in the unit
#:   the claim itself uses (percent -> x100) and rounding it to the
#:   precision the claim's own text declares, that rounded value EQUALS
#:   the claim's value. Nothing else is accepted.
#:
#:   - text declares no fractional part ("3170") -> compare rounded to 0 dp
#:   - text declares n decimals ("0,12", "3.1416", "15,3%") -> compare
#:     rounded to n dp IN DISPLAY SPACE
#:   - no source fact at all -> UNVERIFIED (counted as detected)
#:   - otherwise -> HALLUCINATION
#:
#: Rationale for dropping relative tolerance: 1% is meaningless without a
#: scale-free anchor and it is what let 3170 vs 3180 pass. Rationale for
#: rounding rather than a +/- band: "12,34%" asserts 12.3 +/- 0.05, so a
#: source of 0.1234 (-> 12.34%) IS that claim and 0.12 IS a legitimate
#: rounding of it -- a band of 0.0034 measured in desimal space would
#: have called that a hallucination. Rounding is unit-consistent; the
#: previous absolute band applied a percent-space tolerance to
#: fraction-space values and was 100x too wide (see 10,5% vs 0.1).
GROUNDING_RULE = "round_source_to_declared_precision_in_display_space"

#: Where a rejected claim is written down in the audit trail.
UNVERIFIED_LABEL = _L4["unverified_label"]


class NumericGroundingResult:
    def __init__(self):
        self.extracted_numbers: List[Tuple[str, Decimal]] = []
        self.verified: List[Tuple[str, Decimal, str]] = []  # (text, value, source_key)
        self.unverified: List[Tuple[str, Decimal]] = []  # (text, value)
        self.hallucinations: List[Tuple[str, Decimal]] = []  # alias for unverified
        #: (text, value, reason) for the audit trail, never invented.
        self.rejections: List[Tuple[str, Decimal, str]] = []
    
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


def declared_precision(raw_text: str) -> Optional[int]:
    """Decimal places the claim's own text declares.

    "3.1416" -> 4, "12,34%" -> 2, "3170" -> None (no fractional part),
    "1.234" -> None (Indonesian/English thousands group, not precision).
    "0,001" -> 3 (leading zero before separator means decimal, not thousands).
    """
    body = raw_text.strip().lstrip("-")
    # Strip trailing unit words / % / spaces ("3.2 trillion", "12,34%")
    body = re.sub(r"[^0-9.,]*$", "", body)
    last_dot = body.rfind(".")
    last_comma = body.rfind(",")
    if last_dot < 0 and last_comma < 0:
        return None
    if last_comma > last_dot:
        dec_pos, sep = last_comma, ","
    else:
        dec_pos, sep = last_dot, "."
    trailing = body[dec_pos + 1:]
    if len(trailing) == 3 and body.count(sep) == 1:
        prefix = body.split(sep, 1)[0].lstrip("0")
        if prefix != "":
            return None  # thousands group like "1,234" or "50,000"
        # prefix == "" means "0,001" or "0.001" -> decimal, not thousands
    if not trailing:
        return None
    return len(trailing)


def _abs_tolerance_for(raw_text: str) -> Optional[Decimal]:
    """Half-ULP band implied by the precision the claim's text declares."""
    places = declared_precision(raw_text)
    if places is None:
        return None
    return Decimal(str(DECLARED_PRECISION_ABSOLUTE_TOLERANCE)) * (
        Decimal(10) ** -places
    )


#: Magnitude words a claim may attach to a number. The extracted value is
#: scaled, so the same quantization rule then decides grounded vs
#: hallucination. Indonesian and English spellings share a factor.
MAGNITUDE_WORDS: Dict[str, int] = {
    "ribu": 10 ** 3,
    "thousand": 10 ** 3,
    "thousands": 10 ** 3,
    "juta": 10 ** 6,
    "million": 10 ** 6,
    "millions": 10 ** 6,
    "miliar": 10 ** 9,
    "billion": 10 ** 9,
    "billions": 10 ** 9,
    "triliun": 10 ** 12,
    "trillion": 10 ** 12,
    "trillions": 10 ** 12,
}


def _magnitude_after(text: str, end: int) -> int:
    """Magnitude factor for a word immediately following a number, else 1."""
    rest = re.match(r"\s*([A-Za-z]+)", text[end:])
    if rest is None:
        return 1
    return MAGNITUDE_WORDS.get(rest.group(1).lower(), 1)


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
            factor = _magnitude_after(text, match.end())
            if factor != 1:
                # Keep the magnitude word in raw text so declared_precision
                # and _numbers_match see the same unit the claim declared.
                word = re.match(r"\s*([A-Za-z]+)", text[match.end():])
                if word:
                    raw = f"{raw} {word.group(1)}"
            normalized *= factor
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
        # A 3-digit group after the period is a thousands separator only
        # when a non-zero prefix precedes it ("1.234" -> 1234). "0.001"
        # has only zeros before the period, so it is the decimal 0.001.
        has_prefix = text.split('.', 1)[0].lstrip('0') != ''
        if re.search(r'\.\d{3}$', text) and has_prefix:
            # Indonesian thousands: 1.234 -> 1234
            normalized = text.replace('.', '')
        else:
            # English decimal: 1.23
            normalized = text
    elif comma_count > 0 and period_count == 0:
        # Could be Indonesian decimal (1,23) or English thousands (1,234)
        # A 3-digit group after the comma is a thousands separator only
        # when a non-zero prefix precedes it ("50,000" -> 50000,
        # "1,234" -> 1234). "0,001" has only zeros before the comma, so
        # it is the Indonesian decimal 0.001, never thousands of zero.
        has_prefix = text.split(',', 1)[0].lstrip('0') != ''
        if re.search(r',\d{3}$', text) and has_prefix:
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
) -> NumericGroundingResult:
    """Verify numbers in text against source data.
    
    Args:
        text: LLM output text to verify.
        source_data: Dict of source facts (flat or nested).
    
    Returns:
        NumericGroundingResult with verified/unverified numbers. A claim
        with no matching source fact is unverified, never silently
        accepted; an empty ``source_data`` verifies nothing.
    """
    result = NumericGroundingResult()
    extracted = extract_numbers(text)
    result.extracted_numbers = extracted
    
    # Flatten source data to list of (key, value) pairs
    source_numbers = _flatten_source(source_data)
    
    for raw_text, value in extracted:
        matched = False
        for source_key, source_val in source_numbers:
            ok = _numbers_match(value, source_val, raw_text)
            if ok:
                result.verified.append((raw_text, value, source_key))
                matched = True
                break
        
        if not matched:
            result.unverified.append((raw_text, value))
            result.hallucinations.append((raw_text, value))
            reason = (
                "tidak terverifikasi: tidak ada sumber angka"
                if not source_numbers else
                f"tidak terverifikasi ({UNVERIFIED_LABEL})"
            )
            result.rejections.append((raw_text, value, reason))
    
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


def _numbers_match(claim_value: Decimal, source_val: Decimal, raw_text: str) -> bool:
    """Check if numbers match using the grounding rule.
    
    A claim is grounded iff rounding the source to the precision the
    claim's own text declares yields the claim's value.
    
    Percent claims are compared in percent space (source × 100).
    """
    if claim_value == source_val:
        return True
    
    is_percent = raw_text.strip().endswith('%')
    # Work in display space for percent claims
    display_source = source_val * 100 if is_percent else source_val
    display_claim = claim_value * 100 if is_percent else claim_value
    
    places = declared_precision(raw_text)
    if places is None:
        places = 0
    
    # Magnitude factor declared in the raw text itself ("3.2 trillion"):
    # the declared decimal place stands in magnitude space, so the ULP in
    # base units is 10^-places * factor.
    mag = 1
    unit = re.search(r"([A-Za-z]+)\s*$", raw_text)
    if unit:
        mag = MAGNITUDE_WORDS.get(unit.group(1).lower(), 1)
    
    # Round source to the exact decimal places declared by the text
    try:
        quant_exp = (Decimal(10) ** -places) * mag
        rounded_source = display_source.quantize(quant_exp)
        return rounded_source == display_claim
    except (InvalidOperation, ValueError):
        return False


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


def _binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Exact sum via math.comb."""
    return sum(
        math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
        for i in range(k, n + 1)
    )


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    """Clopper-Pearson exact two-sided (1-alpha) confidence interval.

    k successes out of n trials. Solved by bisection on the monotone
    binomial tail — no scipy dependency.

    Lower: largest p with P(X >= k | p) <= alpha/2 (tail decreasing).
    Upper: largest p with P(X >= k+1 | p) < 1 - alpha/2 (tail increasing).
    """
    if n <= 0:
        return (0.0, 1.0)
    if k <= 0:
        lower = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if _binomial_tail(k, n, mid) > alpha / 2.0:
                hi = mid
            else:
                lo = mid
        lower = (lo + hi) / 2.0
    if k >= n:
        upper = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if _binomial_tail(k + 1, n, mid) < 1.0 - alpha / 2.0:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2.0
    return (lower, upper)


# ponytail: no narrate_explanation hook integration yet.
# Hook integration requires Services/ audit.
