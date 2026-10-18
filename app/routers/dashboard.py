"""Tableau de bord principal (indicateurs financiers et carbone)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import (
    category_breakdown,
    emissions_breakdown,
    evolution_pct,
    resolve_period,
    summarize_expenses,
    top_savings_opportunities,
)
from ..calc.formatting import fmt_money, fmt_tco2e, to_decimal
from ..db import get_db
from ..deps import require_context
from ..models import CarbonRecord, DecisionProject, Expense
from ..services import charts
from ..web import page_context, render

router = APIRouter()


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("/")
def dashboard(
    request: Request,
    db: OrmSession = Depends(get_db),
    period: str = "annee",
    year: str = "",
    month: str = "",
    quarter: str = "",
    start: str = "",
    end: str = "",
):
    context = require_context(request, db)
    organization = context.organization

    range_start = None
    range_end = None
    from ..calc.dashboard import parse_date

    if period == "personnalise":
        range_start = parse_date(start)
        range_end = parse_date(end)
        if not range_start or not range_end:
            period = "annee"

    resolved = resolve_period(
        period,
        today=date.today(),
        year=_parse_int(year),
        month=_parse_int(month),
        quarter=_parse_int(quarter),
        start=range_start,
        end=range_end,
    )

    expenses = (
        db.execute(
            select(Expense)
            .where(
                Expense.organization_id == organization.id,
                Expense.expense_date >= resolved.start,
                Expense.expense_date <= resolved.end,
            )
            .order_by(Expense.expense_date.desc())
        )
        .scalars()
        .all()
    )
    records = (
        db.execute(
            select(CarbonRecord).where(
                CarbonRecord.organization_id == organization.id,
                CarbonRecord.period_start <= resolved.end,
                CarbonRecord.period_end >= resolved.start,
            )
        )
        .scalars()
        .all()
    )
    projects = (
        db.execute(
            select(DecisionProject)
            .where(DecisionProject.organization_id == organization.id)
            .order_by(DecisionProject.updated_at.desc())
        )
        .scalars()
        .all()
    )

    expense_summary = summarize_expenses(expenses)
    emission_summary, emission_rows = emissions_breakdown(records)
    spend_rows = category_breakdown(expenses)

    previous_expenses = []
    previous_records = []
    if resolved.comparable and resolved.previous_start and resolved.previous_end:
        previous_expenses = (
            db.execute(
                select(Expense).where(
                    Expense.organization_id == organization.id,
                    Expense.expense_date >= resolved.previous_start,
                    Expense.expense_date <= resolved.previous_end,
                )
            )
            .scalars()
            .all()
        )
        previous_records = (
            db.execute(
                select(CarbonRecord).where(
                    CarbonRecord.organization_id == organization.id,
                    CarbonRecord.period_start <= resolved.previous_end,
                    CarbonRecord.period_end >= resolved.previous_start,
                )
            )
            .scalars()
            .all()
        )
    previous_expense_summary = summarize_expenses(previous_expenses)
    previous_emission_summary, _ = emissions_breakdown(previous_records)

    spend_evolution = evolution_pct(expense_summary.total_ht, previous_expense_summary.total_ht)
    emission_evolution = evolution_pct(emission_summary.total_kg, previous_emission_summary.total_kg)

    opportunities = top_savings_opportunities(projects, limit=5)
    recent_projects = projects[:5]
    empty_state = not expenses and not records and not projects

    spend_chart = charts.hbar_chart(
        [(row["label"], float(row["ht"])) for row in spend_rows[:7]],
        value_fmt=lambda v: fmt_money(v, decimals=0),
        aria_label="Répartition des dépenses par catégorie",
    )
    emission_chart = charts.hbar_chart(
        [(row["label"], float(row["kg"])) for row in emission_rows[:7]],
        value_fmt=lambda v: fmt_tco2e(to_decimal(v) / 1000),
        color="#172B4D",
        aria_label="Répartition des émissions par catégorie",
    )

    return render(
        request,
        "dashboard.html",
        page_context(
            request,
            db,
            context,
            "dashboard",
            {
                "period": resolved,
                "period_choice": period,
                "year_value": resolved.end.year,
                "expense_summary": expense_summary,
                "emission_summary": emission_summary,
                "spend_rows": spend_rows,
                "emission_rows": emission_rows,
                "spend_evolution": spend_evolution,
                "emission_evolution": emission_evolution,
                "previous_expense_summary": previous_expense_summary,
                "previous_emission_summary": previous_emission_summary,
                "spend_chart": spend_chart,
                "emission_chart": emission_chart,
                "opportunities": opportunities,
                "recent_projects": recent_projects,
                "projects_count": len(projects),
                "saved_projects_count": sum(1 for project in projects if project.status == "enregistree"),
                "empty_state": empty_state,
                "period_label": resolved.label,
            },
        ),
    )
