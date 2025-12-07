# models/utils.py
from datetime import datetime
from typing import Optional
import re


_FRACTION_RE = re.compile(r"^(?P<prefix>.+?\.)(?P<frac>\d+)(?P<suffix>(?:[+-].*)?)$")


def _normalize_iso_fraction(value: str) -> str:
    """
    Pad/trim fractional seconds to 6 digits so datetime.fromisoformat
    can parse strings like 2025-12-07T20:44:03.91949+05:00.
    """
    match = _FRACTION_RE.match(value)
    if not match:
        return value
    prefix, frac, suffix = match.group("prefix", "frac", "suffix")
    normalized = (frac + "000000")[:6]  # right-pad to 6 digits, trim extras
    return f"{prefix}{normalized}{suffix}"


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    # normalize Z to UTC offset
    normalized = value.rstrip("Z")
    if value.endswith("Z"):
        normalized = value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    try:
        fixed_fraction = _normalize_iso_fraction(normalized)
        return datetime.fromisoformat(fixed_fraction)
    except Exception as e:
        # Fall back to None instead of raising to avoid crashing the flow
        print(f"[parse_date] Failed to parse '{value}': {e}")
        return None
