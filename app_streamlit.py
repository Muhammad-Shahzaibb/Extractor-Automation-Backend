"""
Paper Specification Extractor -- Streamlit app
================================================
Reads every .docx specification sheet in the Data/ folder, discovers all
unique physical-spec parameters across them (dynamically -- no hardcoded
column list), lets the user pick which parameters to keep via checkboxes,
and generates a combined Excel file (one row per document) into Output/.

Run with:
    streamlit run app.py
"""

import base64
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.extractor import parse_folder
from src.excel_builder import build_workbook, save_workbook, workbook_to_bytes

DATA_DIR = BASE_DIR / "Data"
OUTPUT_DIR = BASE_DIR / "Output"
LOGO_PATH = BASE_DIR / "assets" / "qbs_logo.svg"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# QBS Co official palette (from qbsco.net / brand logo)
QBS_BLUE = "#0B4DBB"
QBS_GREEN = "#0ACD24"
QBS_NAVY = "#0A1628"
QBS_TEXT = "#101828"
QBS_MUTED = "#6B7280"

st.set_page_config(
    page_title="Paper Spec Extractor | QBS Co",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
        .qbs-header {{
            background: linear-gradient(135deg, {QBS_NAVY} 0%, #1e3a5f 100%);
            border-radius: 10px;
            padding: 1.1rem 1.5rem;
            margin-bottom: 1.25rem;
            border-bottom: 3px solid {QBS_GREEN};
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.25rem;
            flex-wrap: wrap;
        }}
        .qbs-header img {{
            height: 44px;
            width: auto;
            flex-shrink: 0;
            filter: brightness(0) invert(1);
        }}
        .qbs-header-body {{
            flex: 1;
            min-width: 220px;
        }}
        .qbs-header-text h1 {{
            color: #ffffff;
            font-size: 1.55rem;
            font-weight: 700;
            margin: 0 0 0.3rem 0;
            line-height: 1.2;
        }}
        .qbs-header-text p {{
            color: rgba(255, 255, 255, 0.82);
            margin: 0;
            font-size: 0.92rem;
        }}
        .qbs-tagline {{
            color: {QBS_GREEN};
            font-weight: 600;
            font-size: 0.82rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin: 0;
        }}
        .qbs-footer {{
            margin-top: 2.5rem;
            padding: 0.85rem 1rem;
            border-top: 1px solid #e5e7eb;
            color: {QBS_MUTED};
            font-size: 0.82rem;
            text-align: center;
        }}
        .qbs-footer a {{
            color: {QBS_BLUE};
            text-decoration: none;
            font-weight: 600;
        }}
        [data-testid="stSidebar"] > div:first-child {{
            border-right: 3px solid {QBS_GREEN};
        }}
        [data-testid="stSidebar"] .stMarkdown h1,
        [data-testid="stSidebar"] .stMarkdown h2,
        [data-testid="stSidebar"] .stMarkdown h3 {{
            color: {QBS_BLUE};
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

_logo_html = ""
if LOGO_PATH.exists():
    logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    _logo_html = (
        f'<img src="data:image/svg+xml;base64,{logo_b64}" alt="QBS Co" />'
    )

st.markdown(
    f"""
    <div class="qbs-header">
        {_logo_html}
        <div class="qbs-header-body qbs-header-text">
            <h1>Paper Specification Extractor</h1>
            <p>Combine Word specification sheets into a single Excel workbook — one row per document.</p>
        </div>
        <p class="qbs-tagline">Let's get better!</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if "records" not in st.session_state:
    st.session_state.records = None
    st.session_state.columns = []
    st.session_state.errors = []

# ---------------------------------------------------------------------------
# Sidebar: source folder + optional upload + scan trigger
# ---------------------------------------------------------------------------
with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=110)
    st.caption("**QBS Co Pvt Ltd**")
    st.caption("Enterprise digital solutions")
    st.divider()
    st.header("1. Source documents")
    data_dir_input = st.text_input("Data folder path", value=str(DATA_DIR))

    uploaded = st.file_uploader(
        "...or drop .docx files here to add them to the Data folder",
        type=["docx"],
        accept_multiple_files=True,
    )
    if uploaded:
        for f in uploaded:
            (Path(data_dir_input) / f.name).write_bytes(f.getbuffer())
        st.success(f"Saved {len(uploaded)} file(s) to {data_dir_input}")

    scan_clicked = st.button("🔍 Scan Data folder", use_container_width=True, type="primary")

    st.divider()
    st.caption("Presented by **QBS Co Pvt Ltd**")
    st.caption("[qbsco.net](https://qbsco.net)")

if scan_clicked:
    with st.spinner("Reading .docx files..."):
        records, columns, errors = parse_folder(data_dir_input)
    st.session_state.records = records
    st.session_state.columns = columns
    st.session_state.errors = errors

records = st.session_state.records

if records is None:
    st.info("👈 Set the Data folder path (or drop files) and click **Scan Data folder** to begin.")
    st.stop()

if not records:
    st.warning("No .docx files were found — or none could be parsed — in that folder.")
    st.stop()

st.success(
    f"Parsed **{len(records)}** document(s). "
    f"Found **{len(st.session_state.columns)}** unique physical-spec parameters across them."
)

if st.session_state.errors:
    with st.expander(f"⚠️ {len(st.session_state.errors)} file(s) failed to parse — click to view"):
        for fname, msg in st.session_state.errors:
            st.write(f"**{fname}**: {msg}")

# ---------------------------------------------------------------------------
# Column selection
# ---------------------------------------------------------------------------
st.header("2. Choose which physical-spec columns to include")
st.caption(
    "Every parameter found in at least one document is listed below, checked by default. "
    "Untick anything you don't want in the final Excel. A file that doesn't have a checked "
    "parameter will simply have blank cells for it."
)

columns = st.session_state.columns

col_a, col_b = st.columns([1, 5])
with col_a:
    if st.button("Select all"):
        for key in columns:
            st.session_state[f"chk_{key}"] = True
    if st.button("Clear all"):
        for key in columns:
            st.session_state[f"chk_{key}"] = False

COLS_PER_ROW = 4
checkbox_state = {}
for row_start in range(0, len(columns), COLS_PER_ROW):
    row_keys = columns[row_start: row_start + COLS_PER_ROW]
    grid = st.columns(COLS_PER_ROW)
    for cell, key in zip(grid, row_keys):
        checkbox_state[key] = cell.checkbox(key, value=True, key=f"chk_{key}")

selected_columns = [c for c in columns if checkbox_state.get(c)]

# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
st.divider()
st.header("3. Preview")

preview_cols = selected_columns[:6]
preview_rows = []
for r in records[:10]:
    row = {"File": r["file"], "Spec No.": r["SpecNo"], "Client": r["Client"]}
    for c in preview_cols:
        p = r["params"].get(c)
        row[c] = p["Tar"] if p else ""
    preview_rows.append(row)

st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)
st.caption(
    f"Showing the first {min(10, len(records))} of {len(records)} rows, and up to 6 of "
    f"{len(selected_columns)} selected columns (Target values only) as a quick sanity check."
)

# ---------------------------------------------------------------------------
# Generate & download
# ---------------------------------------------------------------------------
st.divider()
st.header("4. Generate Excel")

output_filename = st.text_input("Output file name", value="Specifications_Combined.xlsx")

if st.button("⚙️ Generate Excel", type="primary"):
    if not selected_columns:
        st.error("Select at least one physical-spec column first.")
    else:
        with st.spinner("Building workbook..."):
            wb = build_workbook(records, selected_columns)
            output_path = OUTPUT_DIR / output_filename
            save_workbook(wb, str(output_path))
            file_bytes = workbook_to_bytes(wb)
        st.success(f"Saved to `{output_path}`")
        st.download_button(
            "⬇️ Download Excel",
            data=file_bytes,
            file_name=output_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

st.markdown(
    f"""
    <div class="qbs-footer">
        Presented by <strong>QBS Co Pvt Ltd</strong> &nbsp;·&nbsp;
        <a href="https://qbsco.net" target="_blank">qbsco.net</a>
        &nbsp;·&nbsp; Let's get better!
    </div>
    """,
    unsafe_allow_html=True,
)
