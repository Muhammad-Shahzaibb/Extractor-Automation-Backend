"""Simple extract flow: upload → columns → download Excel (no file storage)."""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas import (
    ExcelRequest,
    ParseErrorOut,
    ParseResponse,
    PreviewRequest,
    PreviewResponse,
    RecordOut,
)
from app.services import extract_service

router = APIRouter(
    prefix="/api/v1/extract",
    tags=["extract"],
)


@router.post("/parse", response_model=ParseResponse)
async def parse_documents(
    files: list[UploadFile] = File(..., description=".docx specification sheets"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ParseResponse:
    """Upload docs, parse in memory/temp, return unique columns for Excel selection."""
    settings = get_settings()
    cached = await extract_service.parse_uploads(
        db, user.id, files, max_bytes=settings.max_upload_bytes
    )
    return ParseResponse(
        run_id=cached.run_id,
        files_total=cached.files_total,
        files_ok=cached.files_ok,
        files_failed=cached.files_failed,
        columns=cached.columns,
        errors=[ParseErrorOut(file=f, message=m) for f, m in cached.errors],
        records=[RecordOut.model_validate(r) for r in cached.records],
    )


@router.post("/preview", response_model=PreviewResponse)
def preview_excel(
    body: PreviewRequest,
    user: User = Depends(get_current_user),
) -> PreviewResponse:
    """
    Preview table for the currently selected columns.
    Call again whenever the user changes column selection (does not clear the run).
    """
    data = extract_service.build_preview(user.id, body.run_id, body.selected_columns)
    return PreviewResponse.model_validate(data)


@router.post("/excel")
def download_excel(
    body: ExcelRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Build Excel from a prior parse and stream it (nothing saved to disk)."""
    data, default_name, _ = extract_service.build_excel_bytes(
        db, user.id, body.run_id, body.selected_columns
    )
    filename = body.filename or default_name
    if not filename.lower().endswith(".xlsx"):
        filename += ".xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
