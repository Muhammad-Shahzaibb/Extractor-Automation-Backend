"""
docx_reader.py
--------------
Low-level helpers for pulling raw table content out of a .docx file.

Word merges cells in inconsistent ways across different specification
templates (some vendors merge Min/Target/Max spans differently row to
row). Reading through python-docx's high level `table.rows[i].cells`
API silently duplicates merged-cell text across every grid column it
spans, which corrupts column alignment. To avoid that, we walk the
raw XML <w:tr>/<w:tc> elements ourselves and read exactly one text
value per *actual* cell, in left-to-right order, ignoring how many
grid columns it happens to span. Values are later matched to
Min/Target/Max by position (1st remaining value = Min, 2nd = Target,
3rd = Max) which is robust to those merge-span quirks.
"""

import re
from docx import Document
from docx.oxml.ns import qn


def clean(text: str) -> str:
    """Normalize whitespace (incl. non-breaking spaces) in extracted text."""
    if text is None:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def raw_table_rows(table):
    """
    Return a table as a list of rows, each row a list of cell text strings,
    with exactly one entry per actual <w:tc> element (no merge duplication).
    """
    rows = []
    for tr in table._tbl.findall(qn("w:tr")):
        cells = []
        for tc in tr.findall(qn("w:tc")):
            text_nodes = tc.findall(".//" + qn("w:t"))
            cell_text = "".join(t.text or "" for t in text_nodes)
            cells.append(cell_text.strip())
        rows.append(cells)
    return rows


def load_document(path):
    """Open a .docx file and return (Document, list_of_tables_as_raw_rows)."""
    doc = Document(path)
    tables = [raw_table_rows(t) for t in doc.tables]
    return doc, tables


def find_table_index(tables, must_contain: str):
    """
    Return the index of the first table whose first cell of its first row
    contains the given substring (case-insensitive). Returns None if not found.
    """
    needle = must_contain.lower()
    for i, rows in enumerate(tables):
        if rows and rows[0] and needle in rows[0][0].lower():
            return i
    return None


def find_cell_with_label(tables, label: str):
    """
    Search every table/row/cell for a cell whose text starts with `label`
    (case-insensitive, ignoring a trailing ':' or '.'), and return the text
    of the *next* cell in that same row (the associated value).
    Returns "" if not found. Robust to which table/row/column position the
    label lives in, since different templates lay these out differently.
    """
    pattern = re.compile(re.escape(label.lower()) + r"\s*[:.]?\s*$")
    pattern_prefix = re.compile(r"^\s*" + re.escape(label.lower()) + r"\s*[:.]?", re.IGNORECASE)
    for rows in tables:
        for row in rows:
            for idx, cell_text in enumerate(row):
                low = cell_text.lower().strip()
                if pattern_prefix.match(low):
                    # value is either the remainder of this same cell (after the label)
                    # or, if this cell is just the label, the next cell in the row.
                    remainder = pattern_prefix.sub("", cell_text).strip()
                    if remainder:
                        return clean(remainder)
                    if idx + 1 < len(row):
                        return clean(row[idx + 1])
    return ""


def find_spec_no(tables) -> str:
    """
    Locate the 'Specification No.' field anywhere in the document's tables
    and return the value that follows it (handles '.', ':' or missing
    separator, and stray leading characters before the label).
    """
    for rows in tables:
        for row in rows:
            for cell_text in row:
                m = re.search(r"Specification\s*No\.?:?\s*(.+)", cell_text, re.IGNORECASE)
                if m:
                    val = clean(m.group(1))
                    if val:
                        return val
    return ""
