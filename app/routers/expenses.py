"""Dépenses : saisie manuelle, modification, filtres, vérification, export."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import parse_date, resolve_period, summarize_expenses
from ..calc.emissions import compute_emissions_kg, status_from_method
from ..calc.formatting import fmt_money, to_decimal
from ..calc.units import are_compatible, canonical_unit, convert
from ..db import get_db
from ..deps import Context, flash, get_scoped, require_context, require_write
from ..enums import EXPENSE_CATEGORIES, VERIFICATION_STATUSES
from ..errors import ValidationError
from ..models import CarbonRecord, EmissionFactor, Expense
from ..services import audit
from ..web import page_context, render

router = APIRouter(prefix="/expenses")

PAGE_SIZE = 25


def factor_choices(db: OrmSession, organization_id: int) -> list[EmissionFactor]:
    return (
        db.execute(
            select(EmissionFactor)
            .where(
                (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == organization_id)
            )
            .order_by(EmissionFactor.label)
        )
        .scalars()
        .all()
    )


def _amounts(amount_ht: str, vat_amount: str, amount_ttc: str) -> tuple[Decimal, Decimal, Decimal]:
    ht = to_decimal(amount_ht)
    vat = to_decimal(vat_amount) or Decimal("0")
    ttc = to_decimal(amount_ttc)
    if ht is None and ttc is None:
        raise ValidationError("Saisissez au moins un montant HT ou TTC.")
    if ht is None:
        ht = (ttc or Decimal("0")) - vat
    if ttc is None:
        ttc = ht + vat
    if ht < 0 or vat < 0 or ttc < 0:
        raise ValidationError("Les montants ne peuvent pas être négatifs.")
    return (
        ht.quantize(Decimal("0.01")),
        vat.quantize(Decimal("0.01")),
        ttc.quantize(Decimal("0.01")),
    )


def _sync_carbon(
    db: OrmSession,
    context: Context,
    expense: Expense,
    *,
    quantity: Decimal | None,
    unit: str | None,
    factor_id: int | None,
) -> tuple[bool, str]:
    """Crée/met à jour l'enregistrement carbone lié, ou l'efface si les données sont insuffisantes."""
    existing = [record for record in expense.carbon_records]
    if factor_id is None or quantity is None or not unit:
        for record in existing:
            db.delete(record)
        missing = []
        if factor_id is None:
            missing.append("aucun facteur d'émission sélectionné")
        if quantity is None or not unit:
            missing.append("quantité ou unité manquante")
        expense.carbon_source_note = "Carbone non estimé : " + " ; ".join(missing) + "."
        return False, expense.carbon_source_note

    factor = db.get(EmissionFactor, factor_id)
    if factor is None or (factor.organization_id not in (None, context.organization.id)):
        raise ValidationError("Facteur d'émission introuvable pour votre organisation.")
    if not are_compatible(unit, factor.unit):
        for record in existing:
            db.delete(record)
        expense.carbon_source_note = (
            f"Carbone non estimé : unité « {unit} » incompatible avec le facteur {factor.code} ({factor.unit})."
        )
        return False, expense.carbon_source_note

    try:
        base_quantity = convert(quantity, unit, factor.unit)
    except Exception:
        for record in existing:
            db.delete(record)
        expense.carbon_source_note = "Carbone non estimé : conversion d'unité impossible."
        return False, expense.carbon_source_note

    kg = compute_emissions_kg(base_quantity, factor.kgco2e_per_unit)
    record = existing[0] if existing else CarbonRecord(
        organization_id=context.organization.id,
        expense=expense,
        is_demo=expense.is_demo,
    )
    record.category = expense.category
    record.period_start = expense.expense_date.replace(day=1)
    record.period_end = expense.expense_date
    record.activity_quantity = base_quantity
    record.activity_unit = factor.unit
    record.emission_factor_id = factor.id
    record.method = factor.method
    record.kgco2e = kg
    record.status = status_from_method(factor.method)
    record.confidence = factor.confidence
    record.notes = f"Calculé depuis la dépense du {expense.expense_date.strftime('%d/%m/%Y')} (quantité x facteur)."
    db.add(record)
    for extra in existing[1:]:
        db.delete(extra)
    expense.carbon_source_note = f"Facteur {factor.code} — source : {factor.source_name}"
    return True, expense.carbon_source_note


def _parse_expense_form(request_form: dict, db: OrmSession, context: Context) -> dict:
    expense_date = parse_date(request_form.get("expense_date"))
    if expense_date is None:
        raise ValidationError("La date de la dépense est obligatoire (JJ/MM/AAAA).")
    category = request_form.get("category") or "autres"
    if category not in EXPENSE_CATEGORIES:
        raise ValidationError("Catégorie de dépense inconnue.")
    status = request_form.get("verification_status") or "a_verifier"
    if status not in VERIFICATION_STATUSES:
        raise ValidationError("Statut de vérification inconnu.")
    ht, vat, ttc = _amounts(
        request_form.get("amount_ht", ""), request_form.get("vat_amount", ""), request_form.get("amount_ttc", "")
    )
    quantity = to_decimal(request_form.get("quantity"))
    unit = canonical_unit(request_form.get("unit")) if request_form.get("unit") else None
    factor_raw = request_form.get("emission_factor_id") or ""
    factor_id = int(factor_raw) if str(factor_raw).isdigit() else None
    if quantity is not None and quantity <= 0:
        raise ValidationError("La quantité doit être supérieure à zéro.")
    return {
        "expense_date": expense_date,
        "category": category,
        "supplier": (request_form.get("supplier") or "").strip()[:160],
        "description": (request_form.get("description") or "").strip(),
        "amount_ht": ht,
        "vat_amount": vat,
        "amount_ttc": ttc,
        "quantity": quantity,
        "unit": unit,
        "factor_id": factor_id,
        "verification_status": status,
        "carbon_source_note": (request_form.get("carbon_source_note") or "").strip(),
    }


@router.get("")
def list_expenses(
    request: Request,
    db: OrmSession = Depends(get_db),
    period: str = "12_mois",
    category: str = "",
    supplier: str = "",
    status: str = "",
    page: int = 1,
):
    context = require_context(request, db)
    resolved = resolve_period(period, today=date.today())
    query = select(Expense).where(
        Expense.organization_id == context.organization.id,
        Expense.expense_date >= resolved.start,
        Expense.expense_date <= resolved.end,
    )
    if category:
        query = query.where(Expense.category == category)
    if supplier:
        query = query.where(Expense.supplier.ilike(f"%{supplier.strip()}%"))
    if status:
        query = query.where(Expense.verification_status == status)
    rows = db.execute(query.order_by(Expense.expense_date.desc(), Expense.id.desc())).scalars().all()
    summary = summarize_expenses(rows)

    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    page_rows = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    suppliers = [
        value
        for (value,) in db.execute(
            select(Expense.supplier)
            .where(Expense.organization_id == context.organization.id, Expense.supplier != "")
            .distinct()
            .order_by(Expense.supplier)
        ).all()
    ]

    return render(
        request,
        "expenses/list.html",
        page_context(
            request,
            db,
            context,
            "expenses",
            {
                "period": resolved,
                "period_choice": period,
                "filters": {"category": category, "supplier": supplier, "status": status},
                "expenses": page_rows,
                "summary": summary,
                "total_count": len(rows),
                "page": page,
                "total_pages": total_pages,
                "suppliers": suppliers,
                "period_label": resolved.label,
            },
        ),
    )


@router.get("/new")
def new_expense(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    return render(
        request,
        "expenses/form.html",
        page_context(
            request,
            db,
            context,
            "expenses",
            {"expense": None, "factors": factor_choices(db, context.organization.id), "today": date.today(), "form": {}},
        ),
    )


@router.post("")
async def create_expense(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    form = dict(await request.form())
    try:
        data = _parse_expense_form(form, db, context)
    except ValidationError as exc:
        flash(db, context, "danger", exc.message)
        return render(
            request,
            "expenses/form.html",
            page_context(
                request,
                db,
                context,
                "expenses",
                {"expense": None, "factors": factor_choices(db, context.organization.id), "today": date.today(), "form": form},
            ),
            status_code=400,
        )
    expense = Expense(organization_id=context.organization.id, is_demo=False, created_by_id=context.user.id)
    for key, value in data.items():
        if key != "factor_id":
            setattr(expense, key, value)
    expense.emission_factor_id = data["factor_id"]
    db.add(expense)
    db.flush()
    carbon_ok, note = _sync_carbon(
        db, context, expense, quantity=data["quantity"], unit=data["unit"], factor_id=data["factor_id"]
    )
    audit.log(
        db,
        action="expense_created",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="expense",
        entity_id=expense.id,
        details={"montant_ht": str(expense.amount_ht), "categorie": expense.category, "carbone": carbon_ok},
        request=request,
    )
    db.commit()
    flash(
        db,
        context,
        "success" if carbon_ok else "warning",
        f"Dépense enregistrée ({fmt_money(expense.amount_ht)} HT)."
        + ("" if carbon_ok else " " + note),
    )
    return RedirectResponse("/expenses", status_code=303)


@router.get("/{expense_id}/edit")
def edit_expense(expense_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    expense = get_scoped(db, Expense, expense_id, context.organization.id)
    return render(
        request,
        "expenses/form.html",
        page_context(
            request,
            db,
            context,
            "expenses",
            {"expense": expense, "factors": factor_choices(db, context.organization.id), "today": date.today(), "form": {}},
        ),
    )


@router.post("/{expense_id}")
async def update_expense(expense_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    expense = get_scoped(db, Expense, expense_id, context.organization.id)
    form = dict(await request.form())
    try:
        data = _parse_expense_form(form, db, context)
    except ValidationError as exc:
        flash(db, context, "danger", exc.message)
        return RedirectResponse(f"/expenses/{expense.id}/edit", status_code=303)
    for key, value in data.items():
        if key != "factor_id":
            setattr(expense, key, value)
    expense.emission_factor_id = data["factor_id"]
    db.flush()
    carbon_ok, note = _sync_carbon(
        db, context, expense, quantity=data["quantity"], unit=data["unit"], factor_id=data["factor_id"]
    )
    audit.log(
        db,
        action="expense_updated",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="expense",
        entity_id=expense.id,
        details={"montant_ht": str(expense.amount_ht)},
        request=request,
    )
    db.commit()
    flash(db, context, "success" if carbon_ok else "warning", f"Dépense mise à jour. {'' if carbon_ok else note}")
    return RedirectResponse("/expenses", status_code=303)


@router.post("/{expense_id}/delete")
def delete_expense(expense_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    expense = get_scoped(db, Expense, expense_id, context.organization.id)
    audit.log(
        db,
        action="expense_deleted",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="expense",
        entity_id=expense.id,
        details={"montant_ht": str(expense.amount_ht), "fournisseur": expense.supplier},
        request=request,
    )
    db.delete(expense)
    db.commit()
    flash(db, context, "success", "Dépense supprimée.")
    return RedirectResponse("/expenses", status_code=303)


@router.post("/{expense_id}/verify")
def verify_expense(expense_id: int, request: Request, db: OrmSession = Depends(get_db), status: str = Form("verifiee")):
    context = require_context(request, db)
    require_write(context)
    if status not in VERIFICATION_STATUSES:
        raise ValidationError("Statut inconnu.")
    expense = get_scoped(db, Expense, expense_id, context.organization.id)
    expense.verification_status = status
    audit.log(
        db,
        action="expense_verified",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="expense",
        entity_id=expense.id,
        details={"statut": status},
        request=request,
    )
    db.commit()
    flash(db, context, "success", f"Statut mis à jour : {VERIFICATION_STATUSES[status]}.")
    return RedirectResponse(request.headers.get("referer") or "/expenses", status_code=303)


@router.get("/export.csv")
def export_expenses(
    request: Request,
    db: OrmSession = Depends(get_db),
    period: str = "12_mois",
    category: str = "",
    supplier: str = "",
    status: str = "",
):
    context = require_context(request, db)
    resolved = resolve_period(period, today=date.today())
    query = select(Expense).where(
        Expense.organization_id == context.organization.id,
        Expense.expense_date >= resolved.start,
        Expense.expense_date <= resolved.end,
    )
    if category:
        query = query.where(Expense.category == category)
    if supplier:
        query = query.where(Expense.supplier.ilike(f"%{supplier.strip()}%"))
    if status:
        query = query.where(Expense.verification_status == status)
    rows = db.execute(query.order_by(Expense.expense_date)).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow([
        "date", "categorie", "fournisseur", "description", "montant_ht", "tva", "montant_ttc",
        "quantite", "unite", "facteur", "source_carbone", "statut_verification", "emissions_kg_co2e", "demonstration",
    ])
    for expense in rows:
        kg = sum((to_decimal(record.kgco2e) or Decimal("0")) for record in expense.carbon_records)
        writer.writerow([
            expense.expense_date.strftime("%d/%m/%Y"),
            EXPENSE_CATEGORIES.get(expense.category, expense.category),
            expense.supplier,
            expense.description,
            f"{expense.amount_ht:.2f}",
            f"{expense.vat_amount:.2f}",
            f"{expense.amount_ttc:.2f}",
            f"{expense.quantity.normalize()}" if expense.quantity is not None else "",
            expense.unit or "",
            expense.emission_factor.code if expense.emission_factor else "",
            expense.carbon_source_note,
            VERIFICATION_STATUSES.get(expense.verification_status, expense.verification_status),
            f"{kg:.3f}" if kg else "",
            "oui" if expense.is_demo else "non",
        ])
    audit.log(
        db,
        action="export_expenses_csv",
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
        headers={"Content-Disposition": f'attachment; filename="depenses_{resolved.range_slug}.csv"'},
    )
