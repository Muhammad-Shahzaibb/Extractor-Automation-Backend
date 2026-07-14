"""
classifier.py
-------------
Turns the messy, inconsistently-worded "Parameter" labels found in the
Physical Specifications table of each spec sheet into a single canonical
column name, so that the same physical property always lands in the same
Excel column no matter how a particular document happened to word it.

Design:
  * Known synonyms are unified by rule (e.g. "Softness", "Softness (HF)"
    and "TSA Softness (HF)" all become "Softness"; "Whiteness" stays
    "Whiteness"; MD/CD tensile variants are split into their own columns).
  * A row whose label is just a continuation marker like "(CD)" or "(MD)"
    (Word documents sometimes split "Tensile strength (MD)" / "(CD)" across
    two table rows) is resolved using the previous row's classification.
  * Anything that does not match a known pattern is NOT dropped -- it is
    kept as its own dynamically-named column (title-cased, whitespace
    collapsed), so genuinely new parameters in future documents still show
    up in the output instead of being silently discarded.

This keeps the tool "dynamic": the set of columns in the final Excel is
determined by whatever is actually found across the documents in Data/,
not by a hardcoded list -- but where we already know common synonyms
should be merged, we merge them for a clean, consistent header.
"""

import re
from typing import Optional

# Preferred left-to-right display order for well-known parameters.
# Anything discovered that ISN'T in this list is appended after these,
# in the order it was first encountered.
PREFERRED_ORDER = [
    "Grammage",
    "Thickness",
    "MD Elongation",
    "Tensile Strength (MD)",
    "Tensile Strength (CD)",
    "Wet Tensile Strength (MD)",
    "Wet Tensile Strength (CD)",
    "Moisture",
    "PH",
    "Brightness",
    "Whiteness",
    "Softness",
    "Absorbency",
    "Dirt Spot Count",
    "Roll Size",
    "Roll Diameter",
    "Core Inner Diameter",
]

# Columns where only a single representative value is expected/kept in
# "Target" (Min/Max intentionally left blank), because the source data is
# typically a single spec value rather than a genuine Min/Target/Max range
# (e.g. "Core inner diameter: 7.6 or (15.2 if agreed)").
SINGLE_VALUE_COLUMNS = {"Core Inner Diameter"}


def _title_case_label(label: str) -> str:
    """Fallback canonicalization for an unrecognized parameter label."""
    text = re.sub(r"\s+", " ", label).strip()
    text = text.strip(" :.-")
    return text.title() if text else "Unknown Parameter"


def classify_label(label: str, prev_key: Optional[str]):
    """
    Map a raw 'Parameter' cell value to a canonical column key.

    `prev_key` is the canonical key assigned to the previous data row in
    the same table, used to resolve continuation rows like a lone "(CD)".
    """
    l = label.lower().strip()

    if not l:
        return None  # blank spacer row -- caller should skip

    if "grammage" in l:
        return "Grammage"
    if "thickness" in l:
        return "Thickness"
    if "elongation" in l:
        return "MD Elongation"

    if "wet tensile" in l:
        return "Wet Tensile Strength (CD)" if "cd" in l else "Wet Tensile Strength (MD)"
    if "tensile" in l:
        return "Tensile Strength (CD)" if "cd" in l else "Tensile Strength (MD)"

    # continuation rows: a row whose entire label is just "(CD)" or "(MD)"
    if l in ("(cd)", "cd"):
        if prev_key in ("Tensile Strength (MD)", "Tensile Strength (CD)"):
            return "Tensile Strength (CD)"
        if prev_key in ("Wet Tensile Strength (MD)", "Wet Tensile Strength (CD)"):
            return "Wet Tensile Strength (CD)"
        return "Tensile Strength (CD)"
    if l in ("(md)", "md"):
        if prev_key in ("Tensile Strength (MD)", "Tensile Strength (CD)"):
            return "Tensile Strength (MD)"
        if prev_key in ("Wet Tensile Strength (MD)", "Wet Tensile Strength (CD)"):
            return "Wet Tensile Strength (MD)"
        return "Tensile Strength (MD)"

    if "moisture" in l:
        return "Moisture"
    if l == "ph":
        return "PH"
    if "whit" in l:  # Whiteness
        return "Whiteness"
    if "soft" in l:  # Softness / Softness (HF) / TSA Softness (HF)
        return "Softness"
    if "bright" in l:
        return "Brightness"
    if "absorbency" in l:
        return "Absorbency"
    if "dirt" in l:
        return "Dirt Spot Count"
    if "roll size" in l:
        return "Roll Size"
    if "roll diameter" in l:
        return "Roll Diameter"
    if "core inner" in l:
        return "Core Inner Diameter"

    # Unknown parameter -- keep it, don't discard, so new spec types are
    # still captured. This is what makes column discovery dynamic.
    return _title_case_label(label)


def order_columns(discovered_keys):
    """
    Given the set of canonical keys actually found across all parsed
    documents, return them in a sensible display order: known parameters
    first (in PREFERRED_ORDER), followed by any newly-discovered ones in
    the order they were first seen.
    """
    ordered = [k for k in PREFERRED_ORDER if k in discovered_keys]
    extras = [k for k in discovered_keys if k not in PREFERRED_ORDER]
    return ordered + extras
