"""
excel_reader.py
---------------
Parses "Hard Roll Test Result" Excel notebooks (.xlsx).

Each workbook represents one production date; each **sheet** is one
product/order combination.  The fixed layout (confirmed from sample files):

  Row  6  – col F  : Rewinder number
  Row 10  – col A  : "Sales Order No"  | col C: value | col G: date | col J: shift
             col L  : "Grade/Quality/#of plies:" | col O: grade+quality+ply text
  Row 11  – col A  : "Item / Line"     | col C: value
  Row 12  – col A  : "Customer Name"   | col C: customer | col L: "Combination" | col O: combo
  Row 14  – col A  : "SPECS"  col B: "TAR"  → TAR values start col D, each param's col(s)
  Row 15  – col B  : "MIN"   → MIN values (same column positions as TAR)
  Row 16  – col B  : "MAX"   → MAX values
  Row 17  – main column headers (Time, Batch #, Roll, GSM, Thickness, …)
  Row 18  – sub-headers (MD, CD, 1PLY, 10PLY …)
  Rows 19+ – actual measurement data (until 'Mean' / 'mean' row)
  Last rows  – Mean, Std Dev, Count, min, max  (stats block)

Output record schema (per sheet):
    {
        "file":        "<filename>",
        "sheet":       "<sheet_name>",
        "sales_order": str,
        "date":        str,
        "shift":       str,
        "item_line":   str,
        "customer":    str,
        "grade_quality_ply": str,   # raw text from col O row 10
        "combination": str,
        "rewinder":    str,
        "specs": {
            "<ColumnName>": {"TAR": val, "MIN": val, "MAX": val, "sub": str_or_None}
        },
        "measurements": [          # one dict per data row
            {
                "time": str,
                "batch": str,
                "roll_width": val,
                "roll_dia": val,
                "joints": val,
                "<col_name>": val,   # dynamic per column
                …
            }
        ],
        "stats": {                  # from the Mean/StdDev/min/max rows
            "mean": {<col_name>: val, …},
            "std_dev": {<col_name>: val, …},
            "count": {<col_name>: val, …},
            "min":   {<col_name>: val, …},
            "max":   {<col_name>: val, …},
        },
        "row_id": "<uuid>",
    }
"""

from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from typing import Any

import openpyxl


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _v(ws, row: int, col: int):
    """Return a cell value, stripping whitespace; None stays None."""
    val = ws.cell(row=row, column=col).value
    if val is None:
        return None
    if isinstance(val, str):
        val = val.strip()
        return val if val else None
    return val


def _str(ws, row: int, col: int) -> str:
    v = _v(ws, row, col)
    return str(v) if v is not None else ""


def _clean_header(raw) -> str | None:
    """Normalise a column header string; return None for blanks."""
    if raw is None:
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    return text if text else None


def _to_num(val):
    """Convert to int or float when possible, leave as string otherwise."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val == int(val):
            return int(val)
        return val
    s = str(val).strip()
    # skip formula error strings
    if s.startswith("#") or not s:
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Column-map builder
# ---------------------------------------------------------------------------

# These columns are in fixed positions and are NOT "spec" columns.
_IDENTITY_COLS = {1, 2, 3, 4, 5}  # Time, Batch #, Roll-width, Roll-dia, Joints

# Map header text → canonical name
_HEADER_MAP: dict[str, str] = {
    "gsm": "GSM",
    "thickness": "Thickness (micron/ply)",
    "tensile strength": "Tensile Strength (MD)",      # MD is the 1st sub-col
    "wet tensile": "Wet Tensile (MD)",                # MD is the 1st sub-col
    "(cd/md) %": "CD/MD Ratio (%)",
    "stretch": "Stretch MD (%)",
    "br %ge": "Brightness (%GE)",
    "a value": "a* value",
    "b value": "b* value",
    "softness": "Softness (HF)",
    "smell": "Smell",
    "actual gsm": "Actual GSM",
    "actual thickness": "Actual Thickness",
    "ri": "RI (Batch_Weight_Size)",
    "remarks": "Remarks",
}


def _canonical(raw_header: str) -> str:
    """Map a raw header to a canonical column name."""
    lo = raw_header.lower().strip()
    for fragment, canon in _HEADER_MAP.items():
        if fragment in lo:
            return canon
    # fallback – title-case the raw text
    return re.sub(r"\s+", " ", raw_header).strip().title()


# ---------------------------------------------------------------------------
# Sheet parser
# ---------------------------------------------------------------------------

# Fixed data-column positions (confirmed from sample files)
# Col 4  = Dia/Roll diameter
# Col 6  = GSM
# Col 8  = Thickness 10-ply
# Col 9  = Tensile MD
# Col 10 = Tensile CD
# Col 11 = CD/MD %
# Col 12 = Stretch MD
# Col 13 = Stretch CD
# Col 14 = Wet Tensile MD
# Col 15 = Brightness
# Col 16 = a value
# Col 17 = b value
# Col 18 = Softness
# Col 19 = Smell
# Col 20 = Actual GSM
# Col 23 = Actual Thickness
# Col 26 = RI
# Col 27 = Remarks

# SPEC columns (where TAR/MIN/MAX live in rows 14-16)
_SPEC_COL_MAP: dict[int, str] = {
    4:  "Roll Diameter (cm)",
    6:  "GSM",
    8:  "Thickness 10-Ply (micron)",
    9:  "Tensile Strength MD (gm/15mm/ply)",
    10: "Tensile Strength CD (gm/15mm/ply)",
    11: "CD/MD Ratio (%)",
    12: "Stretch MD (%)",
    14: "Wet Tensile MD (gm/15mm/ply)",
    15: "Brightness (%GE)",
}

# Measurement data column map (col → name, used to build each data row)
_DATA_COL_MAP: dict[int, str] = {
    3:  "Roll Width (cm)",
    4:  "Roll Dia (cm)",
    6:  "GSM",
    7:  "Thickness 1-Ply (micron)",
    8:  "Thickness 10-Ply (micron)",
    9:  "Tensile Strength MD",
    10: "Tensile Strength CD",
    11: "CD/MD Ratio (%)",
    12: "Stretch MD (%)",
    13: "Stretch CD (%)",
    14: "Wet Tensile MD",
    15: "Brightness (%GE)",
    16: "a* value",
    17: "b* value",
    18: "Softness (HF)",
    19: "Smell",
    20: "Actual GSM",
    23: "Actual Thickness",
    26: "RI (Batch_Weight_Size)",
    27: "Remarks",
}

# Stats rows are labelled in col E (col 5)
_STATS_LABELS = {"mean", "std dev", "count", "min", "max"}


def _compute_stats(measurements: list[dict]) -> dict[str, dict]:
    """Calculate mean, min, max, count, and std_dev across measurement rows."""
    stats: dict[str, dict] = {
        "mean": {}, "std_dev": {}, "count": {}, "min": {}, "max": {}
    }
    if not measurements:
        return stats

    col_values: dict[str, list[float]] = {}
    for m in measurements:
        for k, v in m.items():
            if k in ("time", "batch", "Remarks", "Smell"):
                continue
            if isinstance(v, (int, float)):
                col_values.setdefault(k, []).append(float(v))

    for col, vals in col_values.items():
        if not vals:
            continue
        n = len(vals)
        mean_v = sum(vals) / n
        stats["count"][col] = n
        stats["min"][col] = round(min(vals), 2)
        stats["max"][col] = round(max(vals), 2)
        stats["mean"][col] = round(mean_v, 2)
        if n > 1:
            variance = sum((x - mean_v) ** 2 for x in vals) / (n - 1)
            stats["std_dev"][col] = round(math.sqrt(variance), 2)
        else:
            stats["std_dev"][col] = 0.0

    return stats


def _parse_flat_sheet(ws, filename: str) -> dict[str, Any]:
    """
    Parse a sheet formatted as a flat tabular export (Row 1 headers, Row 2 sub-headers,
    Row 3+ data rows with metadata repeated in columns 1-9).
    """
    # Extract rewinder from filename if present (e.g. 20260909W1 -> RW1)
    m = re.search(r"(?:RW|W)[-_ ]*(\d+)", filename, re.IGNORECASE)
    rewinder = f"RW{m.group(1)}" if m else ""

    # Metadata from the first data row (row 3)
    sales_order = _str(ws, 3, 1)
    item_line   = _str(ws, 3, 2)
    customer    = _str(ws, 3, 3)
    date_raw    = _v(ws, 3, 4)
    shift       = _str(ws, 3, 5)
    grade_ply   = _str(ws, 3, 6)
    combination = _str(ws, 3, 7)

    # Date normalization
    if hasattr(date_raw, "strftime"):
        date_str = date_raw.strftime("%Y-%m-%d")
    else:
        date_s = str(date_raw).strip() if date_raw else ""
        dm = re.match(r"(\d{2})[./-](\d{2})[./-](\d{4})", date_s)
        if dm:
            date_str = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
        else:
            date_str = date_s

    # In flat sheets, data columns are shifted right by 9 columns
    flat_data_col_map = {col + 9: name for col, name in _DATA_COL_MAP.items()}

    measurements: list[dict] = []
    for row_idx in range(3, ws.max_row + 1):
        # Time is col 10, batch is col 11
        time_val = _v(ws, row_idx, 10)
        batch_val = _v(ws, row_idx, 11)

        # If time, batch, and col 1 are all None, row is empty
        if time_val is None and batch_val is None and _v(ws, row_idx, 1) is None:
            continue

        if hasattr(time_val, "strftime"):
            time_str = time_val.strftime("%H:%M")
        else:
            time_str = str(time_val).strip() if time_val else ""

        mrow: dict[str, Any] = {
            "time":  time_str,
            "batch": str(batch_val).strip() if batch_val is not None else "",
        }
        for col, name in flat_data_col_map.items():
            val = _to_num(_v(ws, row_idx, col))
            if val is not None:
                mrow[name] = val

        if len(mrow) > 2:
            measurements.append(mrow)

    stats = _compute_stats(measurements)

    return {
        "file":             filename,
        "sheet":            ws.title,
        "sales_order":      sales_order,
        "date":             date_str,
        "shift":            shift,
        "item_line":        item_line,
        "customer":         customer,
        "grade_quality_ply": grade_ply,
        "combination":      combination,
        "rewinder":         rewinder,
        "shift_details":    [],
        "specs":            {},
        "measurements":     measurements,
        "stats":            stats,
        "row_id":           str(uuid.uuid4()),
    }


def _parse_standard_sheet(ws, filename: str) -> dict[str, Any]:
    """Parse a standard sheet layout (header block in rows 6-12, specs in 14-16, data in 19+)."""
    # ---- header / identity info ----
    rewinder    = _str(ws, 6, 6)
    sales_order = _str(ws, 10, 3)
    date_raw    = _v(ws, 10, 7)
    shift       = _str(ws, 10, 10)
    grade_ply   = _str(ws, 10, 15)
    item_line   = _str(ws, 11, 3)
    customer    = _str(ws, 12, 3)
    combination = _str(ws, 12, 15)

    # ---- shift personnel table (rows 11-12, cols 19/20/22/24) ---------------
    # Row 10 cols 19/20/22/24 are labels: Shift / INSPECTOR / RW OPERATOR / SHIFT INCHARGE
    # Row 11 = Shift A personnel, Row 12 = Shift C personnel (either or both may be present)
    shift_details: list[dict] = []
    for row_idx in (11, 12):
        shift_label  = _str(ws, row_idx, 19).rstrip(": ").strip()  # normalise "A :" → "A"
        inspector    = _str(ws, row_idx, 20)
        operator     = _str(ws, row_idx, 22)
        incharge     = _str(ws, row_idx, 24)
        if shift_label:  # only add if shift letter is present
            shift_details.append({
                "shift":    shift_label,
                "inspector": inspector,
                "operator":  operator,
                "incharge":  incharge,
            })

    # normalise date
    if hasattr(date_raw, "strftime"):
        date_str = date_raw.strftime("%Y-%m-%d")
    else:
        date_str = str(date_raw).strip() if date_raw else ""

    # ---- SPECS block (rows 14-16) ----
    specs: dict[str, dict] = {}
    for col, name in _SPEC_COL_MAP.items():
        tar = _to_num(_v(ws, 14, col))
        mn  = _to_num(_v(ws, 15, col))
        mx  = _to_num(_v(ws, 16, col))
        if any(v is not None for v in (tar, mn, mx)):
            specs[name] = {"TAR": tar, "MIN": mn, "MAX": mx}

    # ---- find data rows and stats rows ----
    # Data starts at row 19; stats block starts where col-E contains
    # a stats label ("Mean", "Std Dev" …)
    measurements: list[dict] = []
    stats: dict[str, dict] = {
        "mean": {}, "std_dev": {}, "count": {}, "min": {}, "max": {}
    }

    for row_idx in range(19, ws.max_row + 1):
        # Check label in col E (col 5) for stats rows
        label_e = _v(ws, row_idx, 5)
        if label_e is not None and str(label_e).strip().lower() in _STATS_LABELS:
            stat_key = str(label_e).strip().lower().replace(" ", "_")
            stat_key = stat_key.replace("std_dev", "std_dev")
            row_vals: dict[str, Any] = {}
            for col, name in _DATA_COL_MAP.items():
                val = _to_num(_v(ws, row_idx, col))
                if val is not None:
                    row_vals[name] = val
            if stat_key in stats:
                stats[stat_key] = row_vals
            continue

        # Regular data row: col A must have a time-like value OR col B a batch #
        time_val  = _v(ws, row_idx, 1)
        batch_val = _v(ws, row_idx, 2)
        if time_val is None and batch_val is None:
            continue

        # Skip rows where col A value is the "SPECS" label (rows 14-16 guard)
        if isinstance(time_val, str) and time_val.upper() in ("SPECS", "TIME"):
            continue

        # Format time
        if hasattr(time_val, "strftime"):
            time_str = time_val.strftime("%H:%M")
        else:
            time_str = str(time_val).strip() if time_val else ""

        mrow: dict[str, Any] = {
            "time":  time_str,
            "batch": str(batch_val).strip() if batch_val is not None else "",
        }
        for col, name in _DATA_COL_MAP.items():
            val = _to_num(_v(ws, row_idx, col))
            if val is not None:
                mrow[name] = val

        # Only add if there's at least one real measurement value beyond time/batch
        if len(mrow) > 2:
            measurements.append(mrow)

    # Fallback: if stats block was absent in sheet, calculate stats from measurements
    if not stats["mean"] and measurements:
        stats = _compute_stats(measurements)

    return {
        "file":             filename,
        "sheet":            ws.title,
        "sales_order":      sales_order,
        "date":             date_str,
        "shift":            shift,
        "item_line":        item_line,
        "customer":         customer,
        "grade_quality_ply": grade_ply,
        "combination":      combination,
        "rewinder":         rewinder,
        "shift_details":    shift_details,
        "specs":            specs,
        "measurements":     measurements,
        "stats":            stats,
        "row_id":           str(uuid.uuid4()),
    }


def _parse_sheet(ws, filename: str) -> dict[str, Any]:
    """Parse a single worksheet into a record dict, auto-detecting layout format."""
    # Check if Row 1 has tabular headers like 'Sales Order No'
    r1_val = _v(ws, 1, 1)
    if r1_val and "sales order" in str(r1_val).lower():
        return _parse_flat_sheet(ws, filename)
    return _parse_standard_sheet(ws, filename)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_excel_file(path: str) -> list[dict[str, Any]]:
    """
    Parse all sheets of an Excel workbook.

    Returns a list of record dicts, one per sheet (skips lock files and
    sheets where no meaningful data was found).

    Raises ValueError if the file cannot be opened or has no valid sheets.
    """
    p = Path(path)
    if p.name.startswith("~$"):
        raise ValueError("Temporary lock file – skipped")

    wb = openpyxl.load_workbook(p, data_only=True, read_only=False)
    records = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        try:
            rec = _parse_sheet(ws, p.name)
            # Only keep sheets that have at least some specs or measurements
            if rec["specs"] or rec["measurements"]:
                records.append(rec)
        except Exception as exc:  # noqa: BLE001
            # Log via caller; don't crash the whole file
            raise ValueError(f"Sheet '{sheet_name}': {exc}") from exc

    if not records:
        raise ValueError("No usable sheets found in workbook")

    return records


def get_excel_display_columns() -> list[str]:
    """
    Return the ordered list of canonical measurement column names
    that the Excel output will include.
    """
    return list(_DATA_COL_MAP.values())
