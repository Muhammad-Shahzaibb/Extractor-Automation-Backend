"""
excel_notebook_service.py
--------------------------
Service layer for the Excel Notebook extraction flow.

Flow:
  1. POST /api/v1/notebooks/parse  – upload .xlsx files → get run_id + preview data
  2. POST /api/v1/notebooks/preview – peek at records without consuming the run
  3. POST /api/v1/notebooks/rows/remove – drop unwanted sheet-records
  4. POST /api/v1/notebooks/download  – stream the consolidated output .xlsx
"""

from __future__ import annotations

import re
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.excel_reader import parse_excel_file
from src.excel_notebook_builder import build_excel_notebook_workbook, workbook_to_bytes

from app.models.run import ExtractionRun
from app.services.run_cache import CachedRun, run_cache

# Reuse the same run_cache singleton (namespaced by run_id uuid – no collision)

SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\s]+")
ALLOWED_EXT = ".xlsx"


def _safe_filename(name: str) -> str:
    base = Path(name or "upload.xlsx").name.strip()
    cleaned = SAFE_NAME.sub("_", base).strip(" ._") or "upload.xlsx"
    if cleaned.startswith("~$"):
        return ""
    if not cleaned.lower().endswith(ALLOWED_EXT):
        cleaned += ALLOWED_EXT
    return cleaned


async def parse_notebook_uploads(
    db: Session,
    user_id: str,
    files: list[UploadFile],
    *,
    max_bytes: int,
) -> CachedRun:
    """
    Upload .xlsx notebook files → parse all sheets → store in run_cache.

    Returns a CachedRun where:
      • records  : list of sheet-record dicts (one per valid sheet)
      • columns  : list of canonical stat/measurement column names
      • errors   : list of (filename_or_sheet, message) tuples
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload at least one .xlsx notebook file",
        )

    started = time.perf_counter()
    records: list[dict] = []
    errors: list[tuple[str, str]] = []
    files_total = 0

    with tempfile.TemporaryDirectory(prefix="binaof_nb_") as tmp:
        tmp_path = Path(tmp)

        for upload in files:
            original = upload.filename or "upload.xlsx"
            safe = _safe_filename(original)
            if not safe:
                errors.append((original, "Invalid or temporary file – skipped"))
                continue

            data = await upload.read()
            files_total += 1

            if len(data) > max_bytes:
                errors.append((original, "File exceeds size limit"))
                continue

            if not original.lower().endswith(ALLOWED_EXT):
                errors.append((original, "Only .xlsx files are allowed"))
                continue

            path = tmp_path / safe
            if path.exists():
                path = tmp_path / f"{path.stem}_{files_total}{path.suffix}"
            path.write_bytes(data)

            try:
                sheet_records = parse_excel_file(str(path))
                for rec in sheet_records:
                    rec["row_id"] = str(uuid.uuid4())
                    records.append(rec)
            except Exception as exc:  # noqa: BLE001
                errors.append((Path(original).name, str(exc)))

    files_ok = len(records)  # one record per sheet
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
            error_message="No sheets could be parsed from the uploaded notebooks",
        )
        db.add(run_row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "No sheets could be parsed from the uploaded notebooks",
                "errors": [{"file": f, "message": m} for f, m in errors],
            },
        )

    # columns = sorted unique list of spec + stat col names for UI display
    spec_names: set[str] = set()
    stat_names: set[str] = set()
    for rec in records:
        spec_names.update(rec.get("specs", {}).keys())
        for st in ("mean", "min", "max", "std_dev", "count"):
            stat_names.update(rec.get("stats", {}).get(st, {}).keys())

    columns = sorted(spec_names) + sorted(stat_names)

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


def remove_notebook_rows(user_id: str, run_id: str, row_ids: list[str]) -> dict:
    """Remove sheet-records by row_id from the cached run."""
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
    run_cache.put(cached)

    return {
        "run_id": run_id,
        "removed_count": removed,
        "remaining_count": len(remaining),
        "remaining_row_ids": [r.get("row_id", "") for r in remaining],
    }


def build_notebook_preview(user_id: str, run_id: str) -> dict:
    """
    Return a lightweight preview of the cached run's records.
    Does NOT consume the run.
    """
    cached = run_cache.get(run_id, user_id)
    rows = []
    for rec in cached.records:
        rows.append(
            {
                "row_id":           rec.get("row_id", ""),
                "file":             rec.get("file", ""),
                "sheet":            rec.get("sheet", ""),
                "sales_order":      rec.get("sales_order", ""),
                "date":             rec.get("date", ""),
                "shift":            rec.get("shift", ""),
                "customer":         rec.get("customer", ""),
                "grade_quality_ply": rec.get("grade_quality_ply", ""),
                "combination":      rec.get("combination", ""),
                "rewinder":         rec.get("rewinder", ""),
                "item_line":        rec.get("item_line", ""),
                "measurement_count": len(rec.get("measurements", [])),
                "specs":            rec.get("specs", {}),
                "stats_mean":       rec.get("stats", {}).get("mean", {}),
            }
        )
    return {
        "run_id":     run_id,
        "total_rows": len(rows),
        "rows":       rows,
    }


def build_notebook_excel_bytes(
    db: Session,
    user_id: str,
    run_id: str,
) -> tuple[bytes, str, CachedRun]:
    """Build the consolidated output Excel and stream bytes."""
    cached = run_cache.get(run_id, user_id)
    if not cached.records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No records left to export – parse again",
        )

    try:
        wb = build_excel_notebook_workbook(cached.records)
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

    # Mark done
    run_cache.pop(run_id, user_id)
    from datetime import datetime, timezone
    row = db.query(ExtractionRun).filter(ExtractionRun.id == run_id).first()
    if row:
        row.status = "completed"
        row.excel_generated = True
        row.completed_at = datetime.now(timezone.utc)
        db.commit()

    default_name = "HardRoll_Combined.xlsx"
    return data, default_name, cached
