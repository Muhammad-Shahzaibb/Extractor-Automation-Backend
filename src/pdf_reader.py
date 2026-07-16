"""
pdf_reader.py
-------------
Low-level helpers for pulling raw table content out of a .pdf spec sheet
(a PDF export of the same Word template docx_reader.py handles), producing
the *same* "tables" shape docx_reader.load_document() does: a list of
tables, each a list of rows, each row a list of cell-text strings. This
lets classifier.py / extractor.py's parsing logic (find_table_index,
find_cell_with_label, find_spec_no, parse_physical_specs, etc.) work
completely unchanged regardless of whether the source was .docx or .pdf.

Why this needs its own extraction strategy (not just "read the PDF's
tables"):
  * pdfplumber's line-based table detector is generally reliable for the
    simple two-column blocks (Client/Quality/Grade, Material Code/Color/
    Ply), so those are used as-is.
  * The "1. Physical Specifications" table is a different story. Word
    renders visually-merged cells (e.g. a "Parameter" cell that contains
    a tab-separated "Grammage" ... "(10 Ply)", or a merged "Unit" column)
    with leftover invisible grid lines from the original template. When
    exported to PDF, those invisible lines are still real vector lines in
    the page content, so pdfplumber's grid detector "sees" them and splits
    what should be one logical cell into several -- inconsistently, row
    by row. Trusting that raw per-row grid would misalign Parameter/Unit/
    Min/Target/Max.

    Instead we take the column boundaries from the ONE row that's always
    a clean, unmerged 5-cell row -- the "Parameter | Unit | Min | Target |
    Max" header -- and re-bucket every data row's words into those 5
    fixed x-ranges. This sidesteps the phantom-split problem entirely and
    reconstructs exactly the columns we need, regardless of how a given
    row's cells happened to fragment.
  * The "Specification No. XXXX   Effective date: ..." line commonly has
    no table borders around it at all, so it doesn't show up in
    pdfplumber's table detection. It's recovered by scanning page text
    for that line and splitting it into cells on whitespace gaps.

Values are always emitted as [label, "", unit, min, tar, max] for spec
rows -- the same "one guaranteed filler cell before Unit" shape
extractor.py's _split_param_row() already expects from docx, so no
downstream parsing code needs to know which file format it came from.
"""

import re

import pdfplumber

# Horizontal gap (in points) between words that signals a new "cell" when
# reconstructing loose, border-less text lines (e.g. the Spec No. line).
WORD_GAP_PT = 18


def clean(text: str) -> str:
    """Normalize whitespace (incl. non-breaking spaces) in extracted text."""
    if text is None:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _cluster_rows(words, y_tol=3):
    """Group words into text-line rows by vertical position."""
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= y_tol:
                row.append(w)
                break
        else:
            rows.append([w])
    rows.sort(key=lambda r: r[0]["top"])
    return rows


def _words_to_cells(words):
    """Split one text line's words into cells wherever the horizontal gap
    between consecutive words is large -- mirrors how a genuine table row
    separates into distinct cells, for lines that have no real borders."""
    if not words:
        return []
    words = sorted(words, key=lambda w: w["x0"])
    cells = [[words[0]]]
    for w in words[1:]:
        if w["x0"] - cells[-1][-1]["x1"] > WORD_GAP_PT:
            cells.append([w])
        else:
            cells[-1].append(w)
    return [" ".join(x["text"] for x in c) for c in cells]


def _find_spec_no_row(page):
    """Locate the 'Specification No. ...  Effective date: ...' line
    anywhere on the page (it's typically outside any bordered table) and
    return it as a synthetic one-row "table" so find_spec_no() (shared
    with docx_reader) can pick it up unmodified."""
    words = page.extract_words(x_tolerance=1, y_tolerance=1)
    for row in _cluster_rows(words):
        line = " ".join(w["text"] for w in row)
        if re.search(r"specification\s*no", line, re.IGNORECASE):
            return [_words_to_cells(row)]
    return []


def _column_bounds_from_header(header_row):
    """header_row is a pdfplumber Row whose .cells are true 1:1 span
    cells (Parameter/Unit/Min/Target/Max) -- their x-ranges become the
    canonical column boundaries used to re-bucket every data row."""
    return [(c[0], c[2]) for c in header_row.cells if c is not None]


def _bucket_row_into_columns(page, row, col_bounds):
    """Re-derive a data row's 5 logical cell values (Parameter, Unit,
    Min, Target, Max) from raw words in that row's y-band, assigning
    each word to whichever fixed column x-range its midpoint falls in --
    ignoring however pdfplumber's grid happened to fragment that row."""
    x0 = min(b[0] for b in col_bounds)
    x1 = max(b[1] for b in col_bounds)
    present = [c for c in row.cells if c is not None]
    top = min(c[1] for c in present)
    bottom = max(c[3] for c in present)
    words = page.crop((x0, top, x1, bottom)).extract_words(x_tolerance=1, y_tolerance=1)

    buckets = [[] for _ in col_bounds]
    for w in words:
        mid = (w["x0"] + w["x1"]) / 2
        for i, (bx0, bx1) in enumerate(col_bounds):
            if bx0 <= mid < bx1 or (i == len(col_bounds) - 1 and mid >= bx0):
                buckets[i].append(w)
                break

    cells_text = []
    for b in buckets:
        b.sort(key=lambda w: w["x0"])
        cells_text.append(" ".join(w["text"] for w in b))
    return cells_text


def _rebuild_physical_specs_table(page, table):
    """Return the Physical Specifications table's rows in the same
    flexible [label, filler, unit, *values] shape docx_reader effectively
    produces, using column-boundary bucketing to defeat phantom merge
    splits (see module docstring)."""
    rows_out = [["1. Physical Specifications"]]

    # `.rows` rebuilds a fresh list of Row objects on every access -- read
    # it exactly once so the header index found below stays valid.
    all_rows = table.rows

    header_idx = None
    for i, r in enumerate(all_rows):
        texts = [(page.crop(c).extract_text() or "") if c else "" for c in r.cells]
        if any("parameter" in t.lower() for t in texts):
            header_idx = i
            break

    if header_idx is None:
        # Couldn't find a clean header row to anchor on -- fall back to
        # the raw grid rather than emitting nothing. Downstream parsing
        # is tolerant of odd row shapes, just less precise on merges.
        for row in table.extract():
            rows_out.append([clean(c) if c is not None else "" for c in row])
        return rows_out

    col_bounds = _column_bounds_from_header(all_rows[header_idx])
    if len(col_bounds) != 5:
        for row in table.extract():
            rows_out.append([clean(c) if c is not None else "" for c in row])
        return rows_out

    rows_out.append(["Parameter", "Unit", "Min", "Target", "Max"])

    for r in all_rows[header_idx + 1:]:
        if not any(c is not None for c in r.cells):
            continue
        label, unit, mn, tar, mx = _bucket_row_into_columns(page, r, col_bounds)
        if clean(label) == "":
            continue
        rows_out.append([clean(label), "", clean(unit), clean(mn), clean(tar), clean(mx)])

    return rows_out


def load_document(path):
    """
    Open a .pdf file and return (None, list_of_tables_as_raw_rows), the
    same contract docx_reader.load_document() has (the first element,
    the python-docx Document, has no PDF equivalent and is unused by
    callers, so None is returned in its place).
    """
    tables_out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            spec_row = _find_spec_no_row(page)
            if spec_row:
                tables_out.append(spec_row)

            for table in page.find_tables():
                rows = table.extract()
                first_cell = clean(rows[0][0]) if rows and rows[0] else ""
                if "physical specification" in first_cell.lower():
                    tables_out.append(_rebuild_physical_specs_table(page, table))
                else:
                    tables_out.append(
                        [[clean(c) if c is not None else "" for c in row] for row in rows]
                    )
    return None, tables_out