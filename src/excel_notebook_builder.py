"""
excel_notebook_builder.py
--------------------------
Builds the consolidated output Excel workbook from parsed Hard Roll Test
Result records (one per sheet of one or more input notebooks).

Output layout (one sheet = "All Results"):

  Identity columns (frozen):
    File | Sheet | Sales Order | Date | Shift | Customer | Grade/Quality/Ply |
    Combination | Rewinder | Item/Line

  SPECS block  (two-row header: param name spanning TAR/MIN/MAX):
    Roll Diameter (cm)  → TAR | MIN | MAX
    GSM                 → TAR | MIN | MAX
    … (all spec cols found across all records)

  Stats block  (two-row header: stat-type spanning all measurement cols):
    Mean  → GSM | Thickness 1-Ply | Tensile MD | … 
    Min   → …
    Max   → …
    StdDev→ …

  Measurement count (single column: # of measurement rows per sheet)

All values are numeric where possible.  The sheet is auto-filtered and
freeze-panes lock the identity columns.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---- style constants -------------------------------------------------------

_THIN = Side(style="thin", color="BBBBBB")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

# header fills
_FILL_IDENTITY = PatternFill("solid", fgColor="2F5496")   # dark blue – identity
_FILL_SPECS    = PatternFill("solid", fgColor="375623")   # dark green – specs
_FILL_STATS    = PatternFill("solid", fgColor="7B3F00")   # dark brown – stats (mean/min/max)
_FILL_COUNT    = PatternFill("solid", fgColor="4B4376")   # dark purple – count

# sub-header fills (slightly lighter variants)
_FILL_IDENTITY_SUB = PatternFill("solid", fgColor="4472C4")
_FILL_SPECS_SUB    = PatternFill("solid", fgColor="70AD47")
_FILL_STATS_SUB    = PatternFill("solid", fgColor="C55A11")
_FILL_COUNT_SUB    = PatternFill("solid", fgColor="7030A0")

# data fills
_FILL_DATA_ODD  = PatternFill("solid", fgColor="F2F7FF")
_FILL_DATA_EVEN = PatternFill("solid", fgColor="FFFFFF")

_FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
_FONT_DATA   = Font(name="Calibri", size=10)

_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_LEFT   = Alignment(horizontal="left",   vertical="center", wrap_text=False)
_ALIGN_RIGHT  = Alignment(horizontal="right",  vertical="center")

# ---- identity column definitions -------------------------------------------

_IDENTITY_COLS: list[tuple[str, str, int]] = [
    # (field_key,          header_label,              width)
    ("file",              "File",                     22),
    ("sheet",             "Sheet",                    20),
    ("sales_order",       "Sales Order",              14),
    ("date",              "Date",                     12),
    ("shift",             "Shift",                     8),
    ("customer",          "Customer",                 16),
    ("grade_quality_ply", "Grade / Quality / Ply",    22),
    ("combination",       "Combination",              16),
    ("rewinder",          "Rewinder",                  9),
    ("item_line",         "Item / Line",              12),
]

# Canonical order for SPECS (TAR/MIN/MAX) block
_SPEC_ORDER = [
    "Roll Diameter (cm)",
    "GSM",
    "Thickness 10-Ply (micron)",
    "Tensile Strength MD (gm/15mm/ply)",
    "Tensile Strength CD (gm/15mm/ply)",
    "CD/MD Ratio (%)",
    "Stretch MD (%)",
    "Wet Tensile MD (gm/15mm/ply)",
    "Brightness (%GE)",
]

# Canonical order for STATS (Mean/Min/Max/StdDev) block
_STATS_MEASUREMENT_ORDER = [
    "GSM",
    "Thickness 1-Ply (micron)",
    "Thickness 10-Ply (micron)",
    "Tensile Strength MD",
    "Tensile Strength CD",
    "CD/MD Ratio (%)",
    "Stretch MD (%)",
    "Stretch CD (%)",
    "Wet Tensile MD",
    "Brightness (%GE)",
    "a* value",
    "b* value",
    "Softness (HF)",
    "Actual GSM",
    "Actual Thickness",
]

_STAT_TYPES = [
    ("mean",    "Mean"),
    ("min",     "Min"),
    ("max",     "Max"),
    ("std_dev", "Std Dev"),
    ("count",   "Count"),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _apply_style(cell, fill, font=_FONT_HEADER, align=_ALIGN_CENTER, border=_BORDER):
    cell.fill   = fill
    cell.font   = font
    cell.alignment = align
    cell.border = border


def _collect_spec_columns(records: list[dict]) -> list[str]:
    """Return ordered list of spec column names found across all records."""
    found: set[str] = set()
    for rec in records:
        found.update(rec.get("specs", {}).keys())
    ordered = [c for c in _SPEC_ORDER if c in found]
    extras  = [c for c in found if c not in _SPEC_ORDER]
    return ordered + sorted(extras)


def _collect_stat_columns(records: list[dict]) -> list[str]:
    """Return ordered list of measurement stat column names found."""
    found: set[str] = set()
    for rec in records:
        for stat_type in ("mean", "min", "max", "std_dev", "count"):
            found.update(rec.get("stats", {}).get(stat_type, {}).keys())
    ordered = [c for c in _STATS_MEASUREMENT_ORDER if c in found]
    extras  = [c for c in found if c not in _STATS_MEASUREMENT_ORDER]
    return ordered + sorted(extras)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_excel_notebook_workbook(records: list[dict]) -> openpyxl.Workbook:
    """
    Build and return an openpyxl Workbook from parsed Excel-notebook records.

    Each record represents one sheet from an input notebook.
    The output has a single "Combined Results" sheet with:
      - Identity columns
      - SPECS block  (TAR / MIN / MAX per parameter)
      - STATS block  (Mean / Min / Max / StdDev / Count per measurement col)
      - Measurement count column
    """
    spec_cols = _collect_spec_columns(records)
    stat_cols = _collect_stat_columns(records)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Combined Results"

    # ---- build column layout ------------------------------------------------
    # We use a two-row header.
    # Row 1: group labels (merged across sub-columns)
    # Row 2: sub-column names

    col = 1  # 1-indexed

    # --- Identity group ---
    id_start = col
    for field_key, label, width in _IDENTITY_COLS:
        ws.cell(row=1, column=col, value=label)
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        ws.column_dimensions[get_column_letter(col)].width = width
        col += 1
    id_end = col - 1

    # --- SPECS group ---
    spec_start = col
    spec_col_positions: dict[str, int] = {}  # spec_name → start_col (TAR, MIN, MAX)
    for spec_name in spec_cols:
        spec_col_positions[spec_name] = col
        ws.cell(row=1, column=col, value=spec_name)
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + 2)
        ws.cell(row=2, column=col,     value="TAR")
        ws.cell(row=2, column=col + 1, value="MIN")
        ws.cell(row=2, column=col + 2, value="MAX")
        for c in range(col, col + 3):
            ws.column_dimensions[get_column_letter(c)].width = 10
        col += 3
    spec_end = col - 1

    # --- STATS group ---
    # For each stat type (Mean, Min, Max, StdDev, Count), one sub-col per stat_col
    stat_group_start = col
    stat_type_positions: dict[str, int] = {}  # stat_key → start_col
    for stat_key, stat_label in _STAT_TYPES:
        stat_type_positions[stat_key] = col
        ws.cell(row=1, column=col, value=stat_label)
        ws.merge_cells(start_row=1, start_column=col, end_row=1,
                       end_column=col + len(stat_cols) - 1)
        for i, sc in enumerate(stat_cols):
            sub_col = col + i
            # Use short label
            short = sc.split("(")[0].strip()
            ws.cell(row=2, column=sub_col, value=short)
            ws.column_dimensions[get_column_letter(sub_col)].width = 12
        col += len(stat_cols)
    stat_group_end = col - 1

    # --- Measurement count ---
    count_col = col
    ws.cell(row=1, column=col, value="# Measurements")
    ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
    ws.column_dimensions[get_column_letter(col)].width = 14
    col += 1

    total_cols = col - 1

    # ---- style header rows --------------------------------------------------
    for c in range(id_start, id_end + 1):
        for r in (1, 2):
            _apply_style(ws.cell(row=r, column=c), _FILL_IDENTITY if r == 1 else _FILL_IDENTITY_SUB)

    if spec_cols:
        for c in range(spec_start, spec_end + 1):
            _apply_style(ws.cell(row=1, column=c), _FILL_SPECS)
        # sub-header row for specs
        for spec_name in spec_cols:
            bc = spec_col_positions[spec_name]
            for c in range(bc, bc + 3):
                _apply_style(ws.cell(row=2, column=c), _FILL_SPECS_SUB)

    if stat_cols:
        for stat_key, _ in _STAT_TYPES:
            bc = stat_type_positions[stat_key]
            _apply_style(ws.cell(row=1, column=bc), _FILL_STATS)
            for i in range(len(stat_cols)):
                _apply_style(ws.cell(row=2, column=bc + i), _FILL_STATS_SUB)

    _apply_style(ws.cell(row=1, column=count_col), _FILL_COUNT)
    _apply_style(ws.cell(row=2, column=count_col), _FILL_COUNT_SUB)

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20

    # ---- data rows ----------------------------------------------------------
    for row_num, rec in enumerate(records, start=3):
        fill = _FILL_DATA_ODD if (row_num % 2 == 1) else _FILL_DATA_EVEN

        # identity
        for i, (field_key, _, _) in enumerate(_IDENTITY_COLS):
            c = id_start + i
            cell = ws.cell(row=row_num, column=c, value=rec.get(field_key, ""))
            cell.font   = _FONT_DATA
            cell.fill   = fill
            cell.border = _BORDER
            cell.alignment = _ALIGN_LEFT if i < 3 else _ALIGN_CENTER

        # specs
        for spec_name in spec_cols:
            bc = spec_col_positions[spec_name]
            s  = rec.get("specs", {}).get(spec_name, {})
            ws.cell(row=row_num, column=bc,     value=s.get("TAR"))
            ws.cell(row=row_num, column=bc + 1, value=s.get("MIN"))
            ws.cell(row=row_num, column=bc + 2, value=s.get("MAX"))
            for c in range(bc, bc + 3):
                cell = ws.cell(row=row_num, column=c)
                cell.font = _FONT_DATA; cell.fill = fill
                cell.border = _BORDER; cell.alignment = _ALIGN_CENTER

        # stats
        for stat_key, _ in _STAT_TYPES:
            bc = stat_type_positions[stat_key]
            stat_data = rec.get("stats", {}).get(stat_key, {})
            for i, sc in enumerate(stat_cols):
                cell = ws.cell(row=row_num, column=bc + i, value=stat_data.get(sc))
                cell.font = _FONT_DATA; cell.fill = fill
                cell.border = _BORDER; cell.alignment = _ALIGN_RIGHT
                if cell.value is not None and isinstance(cell.value, float):
                    cell.number_format = "0.00"

        # measurement count
        cell = ws.cell(row=row_num, column=count_col,
                       value=len(rec.get("measurements", [])))
        cell.font = _FONT_DATA; cell.fill = fill
        cell.border = _BORDER; cell.alignment = _ALIGN_CENTER

    # ---- freeze panes & auto-filter -----------------------------------------
    # Freeze rows 1-2 (header) only; columns A onwards scroll freely without locking
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = ws.cell(row=2, column=1).coordinate + ":" + \
                         ws.cell(row=2, column=total_cols).coordinate

    return wb


def workbook_to_bytes(wb: openpyxl.Workbook) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
