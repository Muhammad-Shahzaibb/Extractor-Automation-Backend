"""Parse uploaded .docx/.pdf bytes in a temp dir (deleted afterward) and build Excel."""

from __future__ import annotations

import re
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.classifier import order_columns
from src.excel_builder import build_workbook, workbook_to_bytes
from src.extractor import parse_file

from app.models.run import ExtractionRun
from app.services.run_cache import CachedRun, run_cache

SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]+")
ALLOWED_EXTENSIONS = (".docx", ".pdf")


def _safe_filename(name: str) -> str:
    base = Path(name or "upload.docx").name.strip()
    cleaned = SAFE_NAME.sub("_", base).strip(" ._") or "upload.docx"
    lower = cleaned.lower()
    if not lower.endswith(ALLOWED_EXTENSIONS):
        cleaned += ".docx"
    if cleaned.startswith("~$"):
        return ""
    return cleaned


def _refresh_columns(records: list[dict]) -> list[str]:
    discovered: set[str] = set()
    for rec in records:
        discovered.update(rec.get("params", {}).keys())
    return order_columns(discovered)


async def parse_uploads(
    db: Session,
    user_id: str,
    files: list[UploadFile],
    *,
    max_bytes: int,
) -> CachedRun:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload at least one .docx or .pdf file",
        )

    started = time.perf_counter()
    records: list[dict] = []
    errors: list[tuple[str, str]] = []
    files_total = 0
    discovered: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="binaof_") as tmp:
        tmp_path = Path(tmp)
        for upload in files:
            original = upload.filename or "upload.docx"
            safe = _safe_filename(original)
            if not safe:
                errors.append((original, "Invalid or temporary file"))
                continue

            data = await upload.read()
            files_total += 1
            if len(data) > max_bytes:
                errors.append((original, "File exceeds size limit"))
                continue
            if not original.lower().endswith(ALLOWED_EXTENSIONS) and not safe.lower().endswith(
                ALLOWED_EXTENSIONS
            ):
                errors.append((original, "Only .docx and .pdf files are allowed"))
                continue

            path = tmp_path / safe
            if path.exists():
                path = tmp_path / f"{path.stem}_{files_total}{path.suffix}"
            path.write_bytes(data)

            try:
                record = parse_file(str(path))
                record["file"] = Path(original).name
                record["row_id"] = str(uuid.uuid4())
                records.append(record)
                discovered.update(record.get("params", {}).keys())
            except Exception as exc:  # noqa: BLE001
                errors.append((Path(original).name, str(exc)))

    files_ok = len(records)
    files_failed = len(errors)
    elapsed = round(time.perf_counter() - started, 3)

    if files_ok == 0:
        run_row = ExtractionRun(
            user_id=user_id,
            status="failed",
            files_total=files_total,
            files_ok=0,
            files_failed=files_failed,
            excel_generated=False,
            processing_seconds=elapsed,
            error_message="No documents could be parsed",
        )
        db.add(run_row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "No documents could be parsed",
                "errors": [{"file": f, "message": m} for f, m in errors],
            },
        )

    columns = order_columns(discovered)
    run_id = run_cache.new_id()
    cached = CachedRun(
        run_id=run_id,
        user_id=user_id,
        records=records,
        columns=columns,
        errors=errors,
        files_total=files_total,
        files_ok=files_ok,
        files_failed=files_failed,
    )
    run_cache.put(cached)

    run_row = ExtractionRun(
        id=run_id,
        user_id=user_id,
        status="pending_excel",
        files_total=files_total,
        files_ok=files_ok,
        files_failed=files_failed,
        excel_generated=False,
        processing_seconds=elapsed,
    )
    db.add(run_row)
    db.commit()
    return cached


def remove_rows(user_id: str, run_id: str, row_ids: list[str]) -> dict:
    """Drop selected rows from the cached run so preview/excel both exclude them."""
    cached = run_cache.get(run_id, user_id)
    wanted = {rid for rid in row_ids if rid}
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one row_id to remove",
        )

    before = len(cached.records)
    remaining = [r for r in cached.records if r.get("row_id") not in wanted]
    removed = before - len(remaining)
    if removed == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the given row_ids were found in this run",
        )

    cached.records = remaining
    cached.files_ok = len(remaining)
    cached.columns = _refresh_columns(remaining)
    run_cache.put(cached)

    return {
        "run_id": run_id,
        "removed_count": removed,
        "remaining_count": len(remaining),
        "remaining_row_ids": [r.get("row_id", "") for r in remaining],
        "columns": cached.columns,
    }


def build_excel_bytes(
    db: Session,
    user_id: str,
    run_id: str,
    selected_columns: list[str],
) -> tuple[bytes, str, CachedRun]:
    cached = run_cache.get(run_id, user_id)
    if not cached.records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No rows left to export — parse again",
        )
    if not selected_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one column",
        )
    # Only export columns that still exist on remaining rows
    export_columns = [c for c in selected_columns if c in cached.columns]
    if not export_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the selected columns remain after row removal",
        )

    try:
        wb = build_workbook(cached.records, export_columns)
        data = workbook_to_bytes(wb)
    except Exception as exc:  # noqa: BLE001
        row = db.query(ExtractionRun).filter(ExtractionRun.id == run_id).first()
        if row:
            row.status = "failed"
            row.error_message = str(exc)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Excel generation failed: {exc}",
        ) from exc

    run_cache.pop(run_id, user_id)
    row = db.query(ExtractionRun).filter(ExtractionRun.id == run_id).first()
    if row:
        row.status = "completed"
        row.excel_generated = True
        from datetime import datetime, timezone

        row.completed_at = datetime.now(timezone.utc)
        db.commit()

    return data, "Specifications_Combined.xlsx", cached


def build_preview(
    user_id: str,
    run_id: str,
    selected_columns: list[str],
) -> dict:
    """Return table rows for selected columns without consuming the cached run."""
    cached = run_cache.get(run_id, user_id)
    if not selected_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one column",
        )

    # Keep FE-selected columns that still exist; ignore ones only on removed rows
    preview_columns = [c for c in selected_columns if c in cached.columns]
    if not preview_columns and cached.records:
        preview_columns = list(cached.columns)

    rows = []
    for rec in cached.records:
        params = {}
        for col in preview_columns:
            p = rec.get("params", {}).get(col)
            if p:
                params[col] = {
                    "Min": p.get("Min", ""),
                    "Tar": p.get("Tar", ""),
                    "Max": p.get("Max", ""),
                    "Unit": p.get("Unit", ""),
                }
            else:
                params[col] = {"Min": "", "Tar": "", "Max": "", "Unit": ""}
        rows.append(
            {
                "row_id": rec.get("row_id", ""),
                "file": rec.get("file", ""),
                "SpecNo": rec.get("SpecNo", ""),
                "Client": rec.get("Client", ""),
                "Quality": rec.get("Quality", ""),
                "Grade": rec.get("Grade", ""),
                "MatCode": rec.get("MatCode", ""),
                "Color": rec.get("Color", ""),
                "Ply": rec.get("Ply", ""),
                "params": params,
            }
        )

    return {
        "run_id": run_id,
        "selected_columns": preview_columns,
        "total_rows": len(rows),
        "rows": rows,
    }
