"""Rapports et exportations (PDF, CSV, Excel).

L'assemblage des documents vit dans ``app.services.report_build`` : la même
logique sert l'interface web FastAPI et l'application Streamlit.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import parse_date, resolve_period
from ..db import get_db
from ..deps import flash, get_scoped, require_context, require_write
from ..errors import ValidationError
from ..models import DecisionProject, Report
from ..services import audit
from ..services.report_build import (
    export_period_excel,
    generate_period_report,
    generate_project_report,
)
from ..web import page_context, render

router = APIRouter(prefix="/reports")


@router.get("")
def reports_page(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    reports = (
        db.execute(
            select(Report)
            .where(Report.organization_id == context.organization.id)
            .order_by(Report.created_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    projects = (
        db.execute(
            select(DecisionProject)
            .where(DecisionProject.organization_id == context.organization.id)
            .order_by(DecisionProject.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return render(
        request,
        "reports/index.html",
        page_context(
            request,
            db,
            context,
            "reports",
            {"reports": reports, "projects": projects},
        ),
    )


@router.post("/generate")
async def generate_report(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    form = dict(await request.form())
    scope = form.get("scope") or "periode"
    output = form.get("output") or "pdf"
    period_preset = form.get("period") or "annee"
    project_id = form.get("project_id") or ""

    if scope == "projet":
        if not str(project_id).isdigit():
            flash(db, context, "danger", "Sélectionnez un projet de décision.")
            return RedirectResponse("/reports", status_code=303)
        project = get_scoped(db, DecisionProject, int(project_id), context.organization.id)
        try:
            report = generate_project_report(
                db,
                organization=context.organization,
                user=context.user,
                project=project,
                request=request,
            )
        except ValidationError as exc:
            flash(db, context, "danger", exc.message)
            return RedirectResponse("/reports", status_code=303)
        flash(db, context, "success", f"Rapport généré : {report.title}.")
        return FileResponse(
            Path(report.file_path),
            media_type="application/pdf",
            filename=f"rapport_decision_{project.id}.pdf",
        )

    # Scope période
    resolved = resolve_period(period_preset, today=date.today())
    if period_preset == "personnalise":
        start = parse_date(form.get("start"))
        end = parse_date(form.get("end"))
        if start and end:
            resolved = resolve_period("personnalise", start=start, end=end)

    if output == "xlsx":
        filename, content = export_period_excel(
            db, organization_id=context.organization.id, resolved=resolved
        )
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    report = generate_period_report(
        db,
        organization=context.organization,
        user=context.user,
        resolved=resolved,
        request=request,
    )
    flash(db, context, "success", f"Rapport généré : {report.title}.")
    return FileResponse(
        Path(report.file_path),
        media_type="application/pdf",
        filename=f"rapport_gestion_{resolved.range_slug}.pdf",
    )


@router.get("/{report_id}/download")
def download_report(report_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    report = get_scoped(db, Report, report_id, context.organization.id)
    path = Path(report.file_path)
    if not report.file_path or not path.exists():
        flash(db, context, "danger", "Fichier introuvable : regénérez le rapport.")
        return RedirectResponse("/reports", status_code=303)
    return FileResponse(path, media_type="application/pdf", filename=f"{report.title}.pdf")


@router.post("/{report_id}/delete")
def delete_report(report_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    report = get_scoped(db, Report, report_id, context.organization.id)
    if report.file_path:
        Path(report.file_path).unlink(missing_ok=True)
    audit.log(
        db,
        action="report_deleted",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="report",
        entity_id=report.id,
        details={"titre": report.title},
        request=request,
        commit=True,
    )
    db.delete(report)
    db.commit()
    flash(db, context, "success", "Rapport supprimé.")
    return RedirectResponse("/reports", status_code=303)
