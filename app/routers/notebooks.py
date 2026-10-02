"""
notebooks.py – Router for Excel Notebook (Hard Roll Test Result) extraction.

Endpoints:
  POST /api/v1/notebooks/parse         → upload .xlsx files, parse all sheets
  GET  /api/v1/notebooks/preview/{id} → lightweight preview of a cached run
  POST /api/v1/notebooks/rows/remove  → remove sheet-records from cached run
  POST /api/v1/notebooks/download     → stream consolidated output .xlsx
"""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas import (
    NotebookDownloadRequest,
    NotebookParseErrorOut,
    NotebookParseResponse,
    NotebookPreviewResponse,
    NotebookPreviewRow,
    NotebookRemoveRowsRequest,
    NotebookRemoveRowsResponse,
    NotebookSpecValues,
)
from app.services import excel_notebook_service

router = APIRouter(
    prefix="/api/v1/notebooks",
    tags=["notebooks"],
)


def _row_to_schema(row: dict) -> NotebookPreviewRow:
    """Convert a raw service preview row dict to the Pydantic schema."""
    specs = {
        k: NotebookSpecValues(
            TAR=v.get("TAR"),
            MIN=v.get("MIN"),
            MAX=v.get("MAX"),
        )
        for k, v in row.get("specs", {}).items()
    }
    return NotebookPreviewRow(
        row_id=row.get("row_id", ""),
        file=row.get("file", ""),
        sheet=row.get("sheet", ""),
        sales_order=row.get("sales_order", ""),
        date=row.get("date", ""),
        shift=row.get("shift", ""),
        customer=row.get("customer", ""),
        grade_quality_ply=row.get("grade_quality_ply", ""),
        combination=row.get("combination", ""),
        rewinder=row.get("rewinder", ""),
        item_line=row.get("item_line", ""),
        measurement_count=row.get("measurement_count", 0),
        specs=specs,
        stats_mean=row.get("stats_mean", {}),
    )


@router.post("/parse", response_model=NotebookParseResponse, summary="Parse Excel notebooks")
async def parse_notebooks(
    files: list[UploadFile] = File(
        ..., description=".xlsx Hard Roll Test Result workbooks (one or more)"
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotebookParseResponse:
    """
    Upload one or more **.xlsx** Hard Roll Test Result workbooks.

    Each sheet in each workbook becomes one output row.  Returns:
    - `run_id`  – use in all subsequent calls
    - `rows`    – one entry per parsed sheet (preview data)
    - `errors`  – files / sheets that could not be parsed
    """
    settings = get_settings()
    cached = await excel_notebook_service.parse_notebook_uploads(
        db, user.id, files, max_bytes=settings.max_upload_bytes
    )
    preview = excel_notebook_service.build_notebook_preview(user.id, cached.run_id)
    return NotebookParseResponse(
        run_id=cached.run_id,
        files_total=cached.files_total,
        files_ok=cached.files_ok,
        files_failed=cached.files_failed,
        errors=[NotebookParseErrorOut(file=f, message=m) for f, m in cached.errors],
        rows=[_row_to_schema(r) for r in preview["rows"]],
    )


@router.get(
    "/preview/{run_id}",
    response_model=NotebookPreviewResponse,
    summary="Preview a notebook run",
)
def preview_notebook(
    run_id: str,
    user: User = Depends(get_current_user),
) -> NotebookPreviewResponse:
    """
    Return the current state of a parsed notebook run without consuming it.
    Useful for re-fetching after row removals.
    """
    preview = excel_notebook_service.build_notebook_preview(user.id, run_id)
    return NotebookPreviewResponse(
        run_id=run_id,
        total_rows=preview["total_rows"],
        rows=[_row_to_schema(r) for r in preview["rows"]],
    )


@router.post(
    "/rows/remove",
    response_model=NotebookRemoveRowsResponse,
    summary="Remove sheet-records from a run",
)
def remove_notebook_rows(
    body: NotebookRemoveRowsRequest,
    user: User = Depends(get_current_user),
) -> NotebookRemoveRowsResponse:
    """
    Remove one or more sheet-records (by `row_id`) from the cached run.
    The download will only include remaining rows.
    """
    result = excel_notebook_service.remove_notebook_rows(
        user.id, body.run_id, body.row_ids
    )
    return NotebookRemoveRowsResponse(**result)


@router.post("/download", summary="Download consolidated Excel")
def download_notebook_excel(
    body: NotebookDownloadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """
    Build and stream the consolidated **.xlsx** output from the parsed run.

    **This call consumes the run** – upload and parse again for a fresh export.
    """
    data, default_name, _ = excel_notebook_service.build_notebook_excel_bytes(
        db, user.id, body.run_id
    )
    filename = body.filename or default_name
    if not filename.lower().endswith(".xlsx"):
        filename += ".xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
