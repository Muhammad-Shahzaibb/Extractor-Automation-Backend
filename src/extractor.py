"""
extractor.py
------------
Orchestrates reading a folder of .docx specification sheets into a list
of plain-dict "records" ready for the Excel builder, plus the dynamic,
ordered list of physical-spec columns actually found across all of them.

Public API:
    parse_file(path)              -> record dict for one document
    parse_folder(folder_path)     -> (records, ordered_columns, errors)
"""

import os
import glob

from .docx_reader import load_document, find_table_index, find_cell_with_label, find_spec_no, clean
from .classifier import classify_label, order_columns, SINGLE_VALUE_COLUMNS
from .value_utils import to_number_or_text, leading_number

IDENTITY_FIELDS = [
    ("Client", ["Client"]),
    ("Quality", ["Quality"]),
    ("Grade", ["Grade"]),
    ("MatCode", ["Material Code", "Mat. Code", "Mat Code"]),
    ("Color", ["Color", "Colour"]),
    ("Ply", ["Ply"]),
]


def _split_param_row(row):
    """
    Split a physical-spec table row into (label, unit, [values...]),
    tolerant of the single blank filler cell some templates use to
    visually widen the 'Parameter' column without a true cell merge.

    Only ONE leading blank cell (if present) is treated as filler and
    skipped -- the cell after it is always treated as the Unit, even if
    that Unit is itself blank (some rows genuinely have no unit, e.g. a
    softness row reported as a bare number). Skipping *every* leading
    blank cell would incorrectly swallow a legitimately blank Unit and
    misalign the Min/Target/Max values that follow it.
    """
    if not row:
        return "", "", []
    label = row[0]
    rest = row[1:]
    idx = 0
    if idx < len(rest) and rest[idx].strip() == "":
        idx += 1  # skip exactly one filler cell, if present
    if idx >= len(rest):
        return label, "", []
    unit = rest[idx]
    values = [v for v in rest[idx + 1:]]
    return label, unit, values


def _values_to_min_tar_max(values):
    """Map a positional list of 1-3 raw value strings to (min, tar, max)."""
    if len(values) >= 3:
        return values[0], values[1], values[2]
    if len(values) == 2:
        return values[0], values[1], ""  # assume (Min, Target); no Max given
    if len(values) == 1:
        return "", values[0], ""  # a single reported value -> Target only
    return "", "", ""


def parse_physical_specs(tables):
    """
    Locate the Physical Specifications table and return a dict of
    canonical_key -> {'Min':..., 'Tar':..., 'Max':...} for one document.
    Rows with an empty label (blank spacer rows) are skipped. If the same
    canonical key is encountered twice in one document (e.g. the same
    property reported in two different units), the first occurrence wins.
    """
    idx = find_table_index(tables, "physical specification")
    if idx is None:
        return {}

    rows = tables[idx]
    # Skip the title row and the "Parameter/Unit/Min/Target/Max" header row.
    data_rows = rows[1:]
    if data_rows and any("parameter" in c.lower() for c in data_rows[0]):
        data_rows = data_rows[1:]

    params = {}
    prev_key = None
    for row in data_rows:
        label, unit, values = _split_param_row(row)
        if clean(label) == "":
            continue
        key = classify_label(label, prev_key)
        if key is None:
            continue
        prev_key = key

        if key in params:
            continue  # keep first occurrence only

        mn, tar, mx = _values_to_min_tar_max(values)
        params[key] = {"Min": clean(mn), "Tar": clean(tar), "Max": clean(mx), "Unit": clean(unit)}

    return params
    

def parse_file(path):
    """Parse a single .docx spec sheet into a record dict."""
    doc, tables = load_document(path)

    record = {"file": os.path.basename(path), "SpecNo": find_spec_no(tables)}
    for field_name, candidate_labels in IDENTITY_FIELDS:
        value = ""
        for label in candidate_labels:
            value = find_cell_with_label(tables, label)
            if value:
                break
        record[field_name] = value

    record["params"] = parse_physical_specs(tables)
    return record


def parse_folder(folder_path, pattern="*.docx"):
    """
    Parse every .docx file directly inside folder_path.

    Returns:
        records: list of record dicts (one per successfully parsed file)
        ordered_columns: list of canonical parameter-column names, in a
            sensible display order, covering every parameter found in ANY
            of the parsed files
        errors: list of (filename, error_message) for files that failed
    """
    files = sorted(glob.glob(os.path.join(folder_path, pattern)))
    # Also catch files nested one level deep (e.g. a zip extracted with a
    # single wrapping folder), without recursing arbitrarily deep.
    files += sorted(glob.glob(os.path.join(folder_path, "*", pattern)))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]  # skip Word lock files

    records = []
    errors = []
    discovered_keys = set()

    for path in files:
        try:
            record = parse_file(path)
            records.append(record)
            discovered_keys.update(record["params"].keys())
        except Exception as exc:  # noqa: BLE001 - we want to keep going and report
            errors.append((os.path.basename(path), str(exc)))

    ordered_columns = order_columns(discovered_keys)
    return records, ordered_columns, errors


def clean_param_value(key, sub, raw):
    """
    Convert a raw Min/Tar/Max text value for a given column into its final
    Excel value. Single-value columns (e.g. Core Inner Diameter) only keep
    a numeric value in the Target slot; Min/Max are always left blank.
    """
    if key in SINGLE_VALUE_COLUMNS:
        if sub == "Tar":
            return leading_number(raw)
        return ""  # Min / Max intentionally blank for single-value columns
    return to_number_or_text(raw)
