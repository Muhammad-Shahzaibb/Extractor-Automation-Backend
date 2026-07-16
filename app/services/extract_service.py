"""Parse uploaded .docx/.pdf bytes in a temp dir (deleted afterward) and build Excel."""

from __future__ import annotations

import re
import tempfile
import time
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
        # Preserve the original extension's intent where possible; default
        # to .docx only when we truly can't tell (e.g. no extension at all).
        cleaned += ".docx"
    if cleaned.startswith("~$"):
        return ""  # Word lock file
    return cleaned


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
                errors.append((original, "Invalid or temporary Word lock file"))
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
            # Avoid collisions
            if path.exists():
                path = tmp_path / f"{path.stem}_{files_total}{path.suffix}"
            path.write_bytes(data)

            try:
                record = parse_file(str(path))
                record["file"] = Path(original).name
                records.append(record)
                discovered.update(record.get("params", {}).keys())
            except Exception as exc:  # noqa: BLE001
                errors.append((Path(original).name, str(exc)))

    # Temp dir is gone — nothing kept on disk
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


def build_excel_bytes(
    db: Session,
    user_id: str,
    run_id: str,
    selected_columns: list[str],
) -> tuple[bytes, str, CachedRun]:
    cached = run_cache.get(run_id, user_id)
    unknown = [c for c in selected_columns if c not in cached.columns]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown columns: {unknown}",
        )
    if not selected_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one column",
        )

    try:
        wb = build_workbook(cached.records, selected_columns)
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
    unknown = [c for c in selected_columns if c not in cached.columns]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown columns: {unknown}",
        )

    rows = []
    for rec in cached.records:
        params = {}
        for col in selected_columns:
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
        "selected_columns": selected_columns,
        "total_rows": len(rows),
        "rows": rows,
    }