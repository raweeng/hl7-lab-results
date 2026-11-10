"""Flag abnormal and critical lab results.

Order of precedence:
1. Critical limits (HH / LL) from CRITICAL_LIMITS, if the test has them.
2. The abnormal flag sent by the lab analyser in OBX-8 (H, L, A, ...).
3. A flag worked out here by comparing the value with the OBX-7 reference range.

The critical limits below are illustrative only, for demonstration.
They are not clinical guidance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# LOINC code -> (critical low, critical high). Illustrative values only.
CRITICAL_LIMITS: dict[str, tuple[float | None, float | None]] = {
    "2823-3": (2.8, 6.2),    # Potassium, mmol/L
    "2951-2": (120.0, 160.0),  # Sodium, mmol/L
    "2345-7": (2.5, 25.0),   # Glucose, mmol/L
    "718-7": (70.0, None),   # Haemoglobin, g/L
    "777-3": (20.0, 1000.0),  # Platelets, x10^9/L
}

LABELS = {
    "N": "Normal",
    "H": "High",
    "L": "Low",
    "HH": "Critical high",
    "LL": "Critical low",
    "A": "Abnormal",
    "AA": "Critical abnormal",
}


@dataclass(frozen=True)
class Flag:
    code: str     # N, H, L, HH, LL, A, AA
    source: str   # "critical-limit", "sender" or "reference-range"

    @property
    def label(self) -> str:
        return LABELS.get(self.code, self.code)

    @property
    def is_abnormal(self) -> bool:
        return self.code != "N"

    @property
    def is_critical(self) -> bool:
        return self.code in ("HH", "LL", "AA")


_RANGE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$")
_LESS = re.compile(r"^\s*<=?\s*(-?\d+(?:\.\d+)?)\s*$")
_MORE = re.compile(r"^\s*>=?\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_range(text: str) -> tuple[float | None, float | None] | None:
    """'3.5-5.2' -> (3.5, 5.2); '<5.0' -> (None, 5.0); '>60' -> (60, None)."""
    if not text:
        return None
    if m := _RANGE.match(text):
        return float(m.group(1)), float(m.group(2))
    if m := _LESS.match(text):
        return None, float(m.group(1))
    if m := _MORE.match(text):
        return float(m.group(1)), None
    return None


def _compare(value: float, low: float | None, high: float | None, below: str, above: str) -> str | None:
    if low is not None and value < low:
        return below
    if high is not None and value > high:
        return above
    return None


def evaluate(code: str, value: str, reference_range: str, sender_flag: str) -> Flag:
    try:
        number: float | None = float(value)
    except ValueError:
        number = None

    if number is not None and code in CRITICAL_LIMITS:
        low, high = CRITICAL_LIMITS[code]
        if critical := _compare(number, low, high, "LL", "HH"):
            return Flag(critical, "critical-limit")

    sender_flag = sender_flag.strip().upper()
    if sender_flag and sender_flag != "N":
        return Flag(sender_flag, "sender")

    if number is not None and (rng := parse_range(reference_range)):
        if out := _compare(number, rng[0], rng[1], "L", "H"):
            return Flag(out, "reference-range")

    return Flag("N", "sender" if sender_flag == "N" else "reference-range")
