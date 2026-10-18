"""Comptabilité carbone : registre des émissions (quantité x facteur documenté)."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import parse_date, resolve_period
from ..calc.emissions import compute_emissions_kg, status_from_method, summarize_records
from ..calc.formatting import fmt_kg, to_decimal
from ..calc.units import are_compatible, canonical_unit, convert
from ..db import get_db
from ..deps import flash, get_scoped, require_context, require_write
from ..enums import CARBON_CATEGORIES, CARBON_STATUSES, CONFIDENCE_LEVELS, EMISSION_METHODS
from ..errors import ValidationError
from ..models import CarbonRecord, EmissionFactor
from ..routers.expenses import factor_choices
from ..services import audit
from ..services.charts import hbar_chart
from ..web import page_context, render

router = APIRouter(prefix="/carbon")


@router.get("")
def list_records(
    request: Request,
    db: OrmSession = Depends(get_db),
    period: str = "12_mois",
    category: str = "",
    status: str = "",
    method: str = "",
    page: int = 1,
):
    context = require_context(request, db)
    resolved = resolve_period(period, today=date.today())
    query = select(CarbonRecord).where(
        CarbonRecord.organization_id == context.organization.id,
        CarbonRecord.period_start <= resolved.end,
        CarbonRecord.period_end >= resolved.start,
    )
    if category:
        query = query.where(CarbonRecord.category == category)
    if status:
        query = query.where(CarbonRecord.status == status)
    if method:
        query = query.where(CarbonRecord.method == method)
    rows = db.execute(query.order_by(CarbonRecord.period_start.desc(), CarbonRecord.id.desc())).scalars().all()
    summary = summarize_records(rows)

    from ..calc.formatting import fmt_tco2e

    category_chart = hbar_chart(
        [
            (CARBON_CATEGORIES.get(code, code), float(kg))
            for code, kg in sorted(summary.by_category.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
        value_fmt=lambda value: fmt_tco2e(to_decimal(value) / 1000),
        color="#172B4D",
        aria_label="Répartition des émissions par catégorie",
    )

    page_size = 25
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    page_rows = rows[(page - 1) * page_size : page * page_size]

    return render(
        request,
        "carbon/list.html",
        page_context(
            request,
            db,
            context,
            "carbon",
            {
                "period": resolved,
                "period_choice": period,
                "filters": {"category": category, "status": status, "method": method},
                "records": page_rows,
                "summary": summary,
                "category_chart": category_chart,
                "total_count": len(rows),
                "page": page,
                "total_pages": total_pages,
                "period_label": resolved.label,
            },
        ),
    )


@router.get("/new")
def new_record(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    return render(
        request,
        "carbon/form.html",
        page_context(
            request,
            db,
            context,
            "carbon",
            {
                "factors": factor_choices(db, context.organization.id),
                "today": date.today(),
                "form": {},
            },
        ),
    )


@router.post("")
async def create_record(
    request: Request,
    db: OrmSession = Depends(get_db),
    category: str = Form("energie"),
    period_start: str = Form(""),
    period_end: str = Form(""),
    quantity: str = Form(""),
    unit: str = Form(""),
    factor_id: str = Form(""),
    method: str = Form(""),
    status: str = Form(""),
    confidence: str = Form(""),
    notes: str = Form(""),
):
    context = require_context(request, db)
    require_write(context)
    form = {
        "category": category,
        "period_start": period_start,
        "period_end": period_end,
        "quantity": quantity,
        "unit": unit,
        "factor_id": factor_id,
        "method": method,
        "status": status,
        "confidence": confidence,
        "notes": notes,
    }
    try:
        start = parse_date(period_start)
        end = parse_date(period_end) or start
        if start is None:
            raise ValidationError("La date de début de période est obligatoire.")
        if end < start:
            start, end = end, start
        if category not in CARBON_CATEGORIES:
            raise ValidationError("Catégorie carbone inconnue.")
        quantity_value = to_decimal(quantity)
        if quantity_value is None or quantity_value <= 0:
            raise ValidationError("Saisissez une quantité d'activité positive.")
        unit_value = canonical_unit(unit)
        if unit_value is None:
            raise ValidationError("Unité non reconnue. Utilisez kWh, L, m3, km, t.km, kg, t, passager.km…")
        if not str(factor_id).isdigit():
            raise ValidationError("Sélectionnez un facteur d'émission documenté.")
        factor = db.get(EmissionFactor, int(factor_id))
        if factor is None or factor.organization_id not in (None, context.organization.id):
            raise ValidationError("Facteur d'émission introuvable pour votre organisation.")
        if not are_compatible(unit_value, factor.unit):
            raise ValidationError(
                f"Unité « {unit_value} » incompatible avec le facteur {factor.code} ({factor.unit}). "
                "Choisissez un facteur adapté à votre unité ou convertissez la quantité."
            )
        base_quantity = convert(quantity_value, unit_value, factor.unit)
        kg = compute_emissions_kg(base_quantity, factor.kgco2e_per_unit)
        method_value = method if method in EMISSION_METHODS else factor.method
        status_value = status if status in CARBON_STATUSES else status_from_method(method_value)
        confidence_value = confidence if confidence in CONFIDENCE_LEVELS else factor.confidence
    except ValidationError as exc:
        flash(db, context, "danger", exc.message)
        return render(
            request,
            "carbon/form.html",
            page_context(
                request,
                db,
                context,
                "carbon",
                {"factors": factor_choices(db, context.organization.id), "today": date.today(), "form": form},
            ),
            status_code=400,
        )

    record = CarbonRecord(
        organization_id=context.organization.id,
        category=category,
        period_start=start,
        period_end=end,
        activity_quantity=base_quantity,
        activity_unit=factor.unit,
        emission_factor_id=factor.id,
        method=method_value,
        kgco2e=kg,
        status=status_value,
        confidence=confidence_value,
        notes=notes.strip() or f"Saisie manuelle — facteur {factor.code} ({factor.source_name}).",
        is_demo=False,
    )
    db.add(record)
    audit.log(
        db,
        action="carbon_record_created",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="carbon_record",
        entity_id=record.id,
        details={"kgco2e": str(kg), "facteur": factor.code, "methode": method_value},
        request=request,
    )
    db.commit()
    flash(
        db,
        context,
        "success",
        f"Enregistrement carbone créé : {fmt_kg(kg)} ({CARBON_STATUSES.get(status_value, status_value)}).",
    )
    return RedirectResponse("/carbon", status_code=303)


@router.post("/{record_id}/delete")
def delete_record(record_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    record = get_scoped(db, CarbonRecord, record_id, context.organization.id)
    audit.log(
        db,
        action="carbon_record_deleted",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="carbon_record",
        entity_id=record.id,
        details={"kgco2e": str(record.kgco2e), "categorie": record.category},
        request=request,
    )
    db.delete(record)
    db.commit()
    flash(db, context, "success", "Enregistrement carbone supprimé.")
    return RedirectResponse("/carbon", status_code=303)


@router.get("/export.csv")
def export_records(request: Request, db: OrmSession = Depends(get_db), period: str = "12_mois"):
    context = require_context(request, db)
    resolved = resolve_period(period, today=date.today())
    rows = (
        db.execute(
            select(CarbonRecord)
            .where(
                CarbonRecord.organization_id == context.organization.id,
                CarbonRecord.period_start <= resolved.end,
                CarbonRecord.period_end >= resolved.start,
            )
            .order_by(CarbonRecord.period_start)
        )
        .scalars()
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow([
        "periode_debut", "periode_fin", "categorie", "quantite_activite", "unite", "facteur",
        "valeur_facteur_kgco2e_par_unite", "source_facteur", "perimetre", "methode", "statut", "confiance",
        "kg_co2e", "tonnes_co2e", "origine", "notes", "demonstration",
    ])
    for record in rows:
        factor = record.emission_factor
        writer.writerow([
            record.period_start.strftime("%d/%m/%Y"),
            record.period_end.strftime("%d/%m/%Y"),
            CARBON_CATEGORIES.get(record.category, record.category),
            f"{record.activity_quantity.normalize()}",
            record.activity_unit,
            factor.code if factor else "",
            f"{factor.kgco2e_per_unit}" if factor else "",
            factor.source_name if factor else "",
            factor.scope if factor else "",
            EMISSION_METHODS.get(record.method, record.method),
            CARBON_STATUSES.get(record.status, record.status),
            CONFIDENCE_LEVELS.get(record.confidence, record.confidence),
            f"{record.kgco2e:.3f}",
            f"{record.kgco2e / 1000:.3f}",
            "dépense liée" if record.expense_id else ("option de décision" if record.option_id else "saisie manuelle"),
            record.notes,
            "oui" if record.is_demo else "non",
        ])
    audit.log(
        db,
        action="export_carbon_csv",
        organization_id=context.organization.id,
        user_id=context.user.id,
        details={"lignes": len(rows), "periode": resolved.label},
        request=request,
        commit=True,
    )
    buffer.seek(0)
    return StreamingResponse(
        iter(["\ufeff" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="registre_carbone_{resolved.start}_{resolved.end}.csv"'},
    )
