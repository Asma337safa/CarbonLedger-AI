"""Importation de dépenses (CSV / Excel) en quatre étapes.

Les points d'API JSON sont appelés par l'assistant d'importation
(``static/js/import.js``) : import du fichier, aperçu, correspondance des
colonnes, vérification puis confirmation.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import ALLOWED_UPLOAD_EXTENSIONS, settings
from ..db import get_db
from ..deps import flash, get_scoped, require_api_context, require_context, require_write
from ..enums import EXPENSE_CATEGORIES
from ..errors import AppError, NotFoundError
from ..models import ImportBatch
from ..security import new_token
from ..services import audit
from ..services.import_service import (
    APP_FIELDS,
    create_expenses_from_report,
    parse_file,
    rows_to_csv,
    suggest_mapping,
    validate_batch,
)
from ..web import page_context, render

router = APIRouter()
api_router = APIRouter(prefix="/api/imports")


def _json_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


# ---------------------------------------------------------------------------
# Page de l'assistant
# ---------------------------------------------------------------------------
@router.get("/imports")
def import_page(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    batches = (
        db.execute(
            select(ImportBatch)
            .where(ImportBatch.organization_id == context.organization.id)
            .order_by(ImportBatch.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    return render(
        request,
        "imports/wizard.html",
        page_context(
            request,
            db,
            context,
            "expenses",
            {
                "app_fields": APP_FIELDS,
                # Contrat lu par static/js/import.js : libellés/aides affichés à l'étape 3.
                "app_fields_json": json.dumps(
                    {key: {"label": value[0], "required": value[1], "help": value[2]} for key, value in APP_FIELDS.items()},
                    ensure_ascii=False,
                ),
                "batches": batches,
                "max_upload_mb": settings.max_upload_mb,
                "extensions": ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS)),
            },
        ),
    )


# ---------------------------------------------------------------------------
# Étape 1-2 : import du fichier et aperçu
# ---------------------------------------------------------------------------
@api_router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: OrmSession = Depends(get_db),
):
    context = require_api_context(request, db)
    require_write(context)
    filename = (file.filename or "import.csv").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        return _json_error(f"Extension non autorisée ({suffix or 'aucune'}). Formats acceptés : CSV, XLSX, XLSM.")
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        return _json_error(f"Fichier trop volumineux ({len(content) / 1024 / 1024:.1f} Mo). Maximum : {settings.max_upload_mb} Mo.")
    if not content:
        return _json_error("Le fichier est vide.")

    stored_name = f"{new_token(12)}{suffix}"
    stored_path = settings.uploads_dir / stored_name
    stored_path.write_bytes(content)

    batch = ImportBatch(
        organization_id=context.organization.id,
        user_id=context.user.id,
        filename=filename[:255],
        stored_path=str(stored_path),
        status="en_attente",
    )
    db.add(batch)
    db.commit()

    try:
        parsed = parse_file(stored_path, filename)
    except AppError as exc:
        batch.status = "echec"
        db.commit()
        stored_path.unlink(missing_ok=True)
        return _json_error(exc.message)
    except Exception as exc:  # pragma: no cover - défensif
        batch.status = "echec"
        db.commit()
        stored_path.unlink(missing_ok=True)
        return _json_error(f"Fichier illisible : {type(exc).__name__}.")

    mapping = suggest_mapping(parsed.columns)
    batch.status = "previsualise"
    batch.mapping = {"mapping": mapping}
    batch.summary = {"total_rows": parsed.total_rows, "columns": parsed.columns}
    audit.log(
        db,
        action="import_uploaded",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="import_batch",
        entity_id=batch.id,
        details={"fichier": filename, "lignes": parsed.total_rows},
        request=request,
    )
    db.commit()

    preview_rows = []
    for row in parsed.rows[:20]:
        preview_rows.append({key: (value if not hasattr(value, "isoformat") else value.isoformat()) for key, value in row.items()})

    return {
        "ok": True,
        "batch_id": batch.id,
        "filename": filename,
        "columns": parsed.columns,
        "total_rows": parsed.total_rows,
        "warnings": parsed.warnings,
        "suggested_mapping": mapping,
        "preview": preview_rows,
        "app_fields": {key: {"label": value[0], "required": value[1], "help": value[2]} for key, value in APP_FIELDS.items()},
    }


# ---------------------------------------------------------------------------
# Étape 3-4 : correspondance puis vérification
# ---------------------------------------------------------------------------
def _load_batch(db: OrmSession, batch_id: int, organization_id: int) -> ImportBatch:
    batch = get_scoped(db, ImportBatch, batch_id, organization_id)
    path = Path(batch.stored_path)
    if not path.exists():
        raise NotFoundError("Fichier temporaire introuvable : relancez l'importation.")
    return batch


@api_router.post("/{batch_id}/mapping")
async def apply_mapping(batch_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_api_context(request, db)
    require_write(context)
    payload = await request.json()
    mapping = {key: value for key, value in (payload.get("mapping") or {}).items() if value}
    include_duplicates = bool(payload.get("include_duplicates"))
    try:
        batch = _load_batch(db, batch_id, context.organization.id)
        report = validate_batch(db, batch, mapping, include_duplicates=include_duplicates)
    except AppError as exc:
        return _json_error(exc.message)
    batch.mapping = {"mapping": mapping, "include_duplicates": include_duplicates}
    batch.status = "mappe"
    batch.summary = {**(batch.summary or {}), "validation": report.stats}
    db.commit()
    preview = []
    for row in report.preview[:80]:
        preview.append(
            {
                "line": row["line"],
                "status": row["status"],
                "messages": row["messages"][:3],
                "date": row["date"].isoformat() if row["date"] else "",
                "supplier": row["supplier"],
                "description": row["description"],
                "amount_ht": str(row["amount_ht"]) if row["amount_ht"] is not None else "",
                "amount_ttc": str(row["amount_ttc"]) if row["amount_ttc"] is not None else "",
                "category": EXPENSE_CATEGORIES.get(row["category"], row["category"]),
                "carbon": row["carbon"],
            }
        )
    return {
        "ok": True,
        "stats": report.stats,
        "issues": [issue.to_dict() for issue in report.issues[:200]],
        "issues_truncated": len(report.issues) >= 400,
        "preview": preview,
    }


@api_router.get("/{batch_id}/errors.csv")
def download_errors(batch_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    batch = _load_batch(db, batch_id, context.organization.id)
    stored_mapping = (batch.mapping or {}).get("mapping") or {}
    include_duplicates = bool((batch.mapping or {}).get("include_duplicates"))
    try:
        report = validate_batch(db, batch, stored_mapping, include_duplicates=include_duplicates)
    except AppError as exc:
        raise exc
    content = rows_to_csv(report.issues)
    return StreamingResponse(
        iter(["\ufeff" + content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="erreurs_import_{batch.id}.csv"'},
    )


@api_router.post("/{batch_id}/confirm")
async def confirm_import(batch_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_api_context(request, db)
    require_write(context)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    try:
        batch = _load_batch(db, batch_id, context.organization.id)
        stored_mapping = (batch.mapping or {}).get("mapping") or {}
        mapping = {key: value for key, value in (payload.get("mapping") or stored_mapping).items() if value}
        include_duplicates = bool(payload.get("include_duplicates", (batch.mapping or {}).get("include_duplicates")))
        if not mapping:
            return _json_error("Aucune correspondance de colonnes enregistrée : relancez l'étape 3.")
        report = validate_batch(db, batch, mapping, include_duplicates=include_duplicates)
    except AppError as exc:
        return _json_error(exc.message)

    created, carbon_created = create_expenses_from_report(
        db,
        organization_id=context.organization.id,
        user_id=context.user.id,
        report=report,
        batch_filename=batch.filename,
    )

    batch.status = "importe"
    batch.summary = {**(batch.summary or {}), "imported": created, "carbon_created": carbon_created, "stats": report.stats}
    Path(batch.stored_path).unlink(missing_ok=True)  # minimisation des données : le fichier temporaire est supprimé
    audit.log(
        db,
        action="import_confirmed",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="import_batch",
        entity_id=batch.id,
        details={"lignes_importees": created, "carbone": carbon_created, "fichier": batch.filename},
        request=request,
    )
    db.commit()
    flash(
        db,
        context,
        "success" if created else "warning",
        f"Importation terminée : {created} dépense(s) créée(s), {carbon_created} estimation(s) carbone associée(s). "
        + (f"{report.stats.get('errors', 0)} ligne(s) en erreur ont été écartées." if report.stats.get("errors") else ""),
    )
    return {"ok": True, "created": created, "carbon_created": carbon_created, "stats": report.stats}
