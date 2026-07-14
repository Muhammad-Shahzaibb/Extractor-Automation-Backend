"""
value_utils.py
--------------
Small helpers for turning the raw text found in spec-sheet cells into
Excel-friendly values, without ever inventing data that isn't there.
"""

import re


def to_number_or_text(raw: str):
    """
    Convert a cell's raw text to a number when it cleanly represents one;
    otherwise leave it as the original text (e.g. "As per order" for a
    Roll size target). Returns "" for empty input.
    """
    if raw is None or raw == "":
        return ""
    try:
        f = float(raw)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return raw


def leading_number(raw: str):
    """
    Extract only the leading numeric token from text such as
    '7.6 or (15.2 if agreed)' -> 7.6. Falls back to '' if the text does
    not start with a number at all.
    """
    if not raw:
        return ""
    m = re.match(r"\s*(-?[\d.]+)", raw)
    if not m:
        return ""
    try:
        f = float(m.group(1))
        return int(f) if f.is_integer() else f
    except ValueError:
        return ""
