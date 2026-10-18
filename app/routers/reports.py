"""Rapports et exportations (PDF, CSV, Excel)."""

from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.arbitration import arbitrate
from ..calc.dashboard import (
    category_breakdown,
    emissions_breakdown,
    parse_date,
    resolve_period,
    summarize_expenses,
)
from ..calc.decision import compare_options
from ..config import settings as app_settings
from ..db import get_db
from ..deps import flash, get_scoped, require_context, require_write
from ..enums import CARBON_CATEGORIES, EXPENSE_CATEGORIES, PRIORITIES, PROJECT_STATUSES
from ..errors import ValidationError
from ..models import CarbonRecord, DecisionProject, Expense, Report
from ..services import audit
from ..services.project_service import project_inputs
from ..services.report_pdf import generate_decision_pdf, generate_period_pdf
from ..web import page_context, render

router = APIRouter(prefix="/reports")


def collect_period_data(db: OrmSession, organization_id: int, resolved):
    expenses = (
        db.execute(
            select(Expense).where(
                Expense.organization_id == organization_id,
                Expense.expense_date >= resolved.start,
                Expense.expense_date <= resolved.end,
            )
        )
        .scalars()
        .all()
    )
    records = (
        db.execute(
            select(CarbonRecord).where(
                CarbonRecord.organization_id == organization_id,
                CarbonRecord.period_start <= resolved.end,
                CarbonRecord.period_end >= resolved.start,
            )
        )
        .scalars()
        .all()
    )
    return expenses, records


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


def _factor_sources(db: OrmSession, organization_id: int, records) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()
    for record in records:
        factor = record.emission_factor
        if factor is None:
            continue
        text = f"{factor.code} — {factor.label} : {factor.kgco2e_per_unit} kgCO₂e/{factor.unit} — source : {factor.source_name or 'non documentée'}"
        if text not in seen:
            seen.add(text)
            sources.append(text)
    return sources


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
        inputs = project_inputs(project)
        if len(inputs) < 2:
            flash(db, context, "danger", "Ce projet comporte moins de deux options : rapport impossible.")
            return RedirectResponse("/reports", status_code=303)
        from ..services.project_service import analyze_project

        analysis = analyze_project(project)
        target_dir = app_settings.reports_dir / str(context.organization.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        report = Report(
            organization_id=context.organization.id,
            project_id=project.id,
            kind="pdf",
            scope="projet",
            title=f"Rapport de décision — {project.title}",
            created_by_id=context.user.id,
        )
        db.add(report)
        db.flush()
        path = target_dir / f"rapport_decision_{project.id}_{report.id}.pdf"
        payload = generate_decision_pdf(
            path,
            organization_name=context.organization.name,
            project_title=project.title,
            project_category=EXPENSE_CATEGORIES.get(project.category, project.category),
            horizon_years=project.horizon_years,
            priority_label=PRIORITIES.get(project.priority, project.priority),
            carbon_price=project.internal_carbon_price,
            analysis=analysis,
            author_name=context.user.full_name or context.user.email,
        )
        report.file_path = str(path)
        report.payload = payload
        audit.log(
            db,
            action="report_generated",
            organization_id=context.organization.id,
            user_id=context.user.id,
            entity_type="report",
            entity_id=report.id,
            details={"scope": "projet", "projet": project.title},
            request=request,
        )
        db.commit()
        flash(db, context, "success", f"Rapport généré : {report.title}.")
        return FileResponse(path, media_type="application/pdf", filename=f"rapport_decision_{project.id}.pdf")

    # Scope période
    resolved = resolve_period(period_preset, today=date.today())
    if period_preset == "personnalise":
        start = parse_date(form.get("start"))
        end = parse_date(form.get("end"))
        if start and end:
            resolved = resolve_period("personnalise", start=start, end=end)
    expenses, records = collect_period_data(db, context.organization.id, resolved)
    expense_summary = summarize_expenses(expenses)
    emission_summary, emission_rows = emissions_breakdown(records)
    category_rows = category_breakdown(expenses)
    projects = (
        db.execute(
            select(DecisionProject).where(DecisionProject.organization_id == context.organization.id)
        )
        .scalars()
        .all()
    )
    projects_rows = [
        {
            "title": project.title,
            "status": PROJECT_STATUSES.get(project.status, project.status),
            "summary": (project.description or "")[:200],
        }
        for project in projects
    ]
    sources = _factor_sources(db, context.organization.id, records)
    notes = [
        f"Période analysée : {resolved.label}.",
        "Les montants proviennent des dépenses saisies ou importées, hors éléments non renseignés.",
        (
            f"{expense_summary.without_factor_count} dépense(s) sans facteur d'émission : "
            "leur carbone n'est pas estimé (aucun facteur attribué automatiquement)."
        ),
    ]

    if output == "xlsx":
        return _excel_export(context, resolved, expenses, records, projects)

    target_dir = app_settings.reports_dir / str(context.organization.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Pour « Tout l'historique », on historise les bornes réelles des données
    # (sinon le journal afficherait 01/01/2000 → 31/12/9999).
    period_start, period_end = resolved.start, resolved.end
    if resolved.key == "tout":
        dates = [row.expense_date for row in expenses if row.expense_date]
        if dates:
            period_start, period_end = min(dates), max(dates)
    report = Report(
        organization_id=context.organization.id,
        kind="pdf",
        scope="periode",
        title=f"Rapport de gestion — {resolved.label}",
        period_start=period_start,
        period_end=period_end,
        created_by_id=context.user.id,
    )
    db.add(report)
    db.flush()
    path = target_dir / f"rapport_gestion_{report.id}.pdf"
    payload = generate_period_pdf(
        path,
        organization_name=context.organization.name,
        period_label=resolved.label,
        expense_summary=expense_summary,
        category_rows=category_rows,
        emission_summary=emission_summary,
        emission_rows=emission_rows,
        projects_rows=projects_rows,
        factor_sources=sources,
        notes=notes,
        author_name=context.user.full_name or context.user.email,
    )
    report.file_path = str(path)
    report.payload = payload
    audit.log(
        db,
        action="report_generated",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="report",
        entity_id=report.id,
        details={"scope": "periode", "periode": resolved.label},
        request=request,
    )
    db.commit()
    flash(db, context, "success", f"Rapport généré : {report.title}.")
    return FileResponse(path, media_type="application/pdf", filename=f"rapport_gestion_{resolved.range_slug}.pdf")


def _excel_export(context, resolved, expenses, records, projects) -> StreamingResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="176B4D")

    sheet = workbook.active
    sheet.title = "Dépenses"
    sheet.append([
        "Date", "Catégorie", "Fournisseur", "Description", "Montant HT", "TVA", "Montant TTC",
        "Quantité", "Unité", "Facteur", "Statut", "Démonstration",
    ])
    for expense in expenses:
        sheet.append([
            expense.expense_date.isoformat(),
            EXPENSE_CATEGORIES.get(expense.category, expense.category),
            expense.supplier,
            expense.description,
            float(expense.amount_ht),
            float(expense.vat_amount),
            float(expense.amount_ttc),
            float(expense.quantity) if expense.quantity is not None else None,
            expense.unit or "",
            expense.emission_factor.code if expense.emission_factor else "",
            expense.verification_status,
            "oui" if expense.is_demo else "non",
        ])

    sheet = workbook.create_sheet("Registre carbone")
    sheet.append([
        "Début", "Fin", "Catégorie", "Quantité d'activité", "Unité", "Facteur", "kg CO2e", "t CO2e",
        "Méthode", "Statut", "Confiance", "Source du facteur",
    ])
    for record in records:
        sheet.append([
            record.period_start.isoformat(),
            record.period_end.isoformat(),
            CARBON_CATEGORIES.get(record.category, record.category),
            float(record.activity_quantity),
            record.activity_unit,
            record.emission_factor.code if record.emission_factor else "",
            float(record.kgco2e),
            float(record.kgco2e / 1000),
            record.method,
            record.status,
            record.confidence,
            record.emission_factor.source_name if record.emission_factor else "",
        ])

    sheet = workbook.create_sheet("Décisions")
    sheet.append([
        "Projet", "Statut", "Option", "Fournisseur", "Coût d'acquisition", "Coût total (horizon)",
        "Émissions cumulées (t)", "Confiance", "Options complètes",
    ])
    for project in projects:
        inputs = project_inputs(project)
        if len(inputs) < 2:
            sheet.append([project.title, project.status, "—", "", None, None, None, "", "moins de deux options"])
            continue
        try:
            comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
            for result in comparison.results:
                sheet.append([
                    project.title,
                    PROJECT_STATUSES.get(project.status, project.status),
                    result.name,
                    result.option.supplier,
                    float(result.purchase_cost),
                    float(result.total_cost),
                    float(result.total_emissions_t) if result.total_emissions_t is not None else None,
                    result.option.confidence,
                    "",
                ])
        except Exception:
            sheet.append([project.title, project.status, "—", "", None, None, None, "", "calcul impossible"])

    for sheet in workbook.worksheets:
        for cell in sheet[1]:
            cell.font = header_font
            cell.fill = header_fill
        for column_cells in sheet.columns:
            length = max((len(str(cell.value)) if cell.value is not None else 0) for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(42, max(12, length + 2))

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="carbonledger_export_{resolved.range_slug}.xlsx"'},
    )


@router.get("/{report_id}/download")
def download_report(report_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    report = get_scoped(db, Report, report_id, context.organization.id)
    from pathlib import Path

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
    from pathlib import Path

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
