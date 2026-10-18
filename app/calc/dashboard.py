"""Agrégations du tableau de bord et résolution des périodes.

Aucune donnée n'est inventée : les indicateurs sont construits uniquement
à partir des enregistrements présents en base. L'évolution par rapport à la
période précédente n'est affichée que si des données comparables existent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from ..enums import CARBON_CATEGORIES, EXPENSE_CATEGORIES
from .emissions import EmissionSummary, summarize_records
from .formatting import to_decimal


@dataclass
class Period:
    key: str
    label: str
    start: date
    end: date
    previous_start: date | None = None
    previous_end: date | None = None
    previous_label: str = ""
    comparable: bool = True

    @property
    def range_slug(self) -> str:
        """Fragment de nom de fichier : bornes réelles, ou clé pour les périodes ouvertes."""
        if self.key == "tout":
            return "tout"
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    first_month = 3 * (quarter - 1) + 1
    start = date(year, first_month, 1)
    end_month = first_month + 2
    end = date(year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def resolve_period(
    preset: str = "annee",
    *,
    today: date | None = None,
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Period:
    """Résout une période d'analyse et la période précédente comparable."""
    today = today or date.today()
    year = year or today.year

    if preset == "mois":
        s, e = _month_bounds(year, month or today.month)
        prev_year = year - 1 if (month or today.month) == 1 else year
        prev_month = 12 if (month or today.month) == 1 else (month or today.month) - 1
        p_s, p_e = _month_bounds(prev_year, prev_month)
        return Period("mois", "Mois en cours", s, e, p_s, p_e, "Mois précédent")

    if preset == "mois_precedent":
        m = (month or today.month) - 1
        y = year
        if m == 0:
            m, y = 12, year - 1
        s, e = _month_bounds(y, m)
        pm = m - 1
        py = y
        if pm == 0:
            pm, py = 12, y - 1
        p_s, p_e = _month_bounds(py, pm)
        return Period("mois_precedent", "Mois précédent", s, e, p_s, p_e, "Mois d'avant")

    if preset == "trimestre":
        q = quarter or ((today.month - 1) // 3 + 1)
        s, e = _quarter_bounds(year, q)
        pq = q - 1
        py = year
        if pq == 0:
            pq, py = 4, year - 1
        p_s, p_e = _quarter_bounds(py, pq)
        return Period("trimestre", f"Trimestre {q} — {year}", s, e, p_s, p_e, f"Trimestre {pq} — {py}")

    if preset == "12_mois":
        s = date(today.year - 1, today.month, today.day) + timedelta(days=1)
        e = today
        p_e = s - timedelta(days=1)
        p_s = date(p_e.year - 1, p_e.month, p_e.day) + timedelta(days=1)
        return Period("12_mois", "12 derniers mois", s, e, p_s, p_e, "12 mois précédents")

    if preset == "tout":
        # « Tout l'historique » couvre TOUTES les lignes enregistrées, y compris
        # celles datées plus tard (factures prévisionnelles saisies à l'avance) :
        # aucun plafond de date, contrairement aux autres périodes.
        return Period(
            "tout",
            "Tout l'historique",
            date(2000, 1, 1),
            date(9999, 12, 31),
            None,
            None,
            "Historique complet (aucune période précédente comparable)",
            comparable=False,
        )

    if preset == "personnalise" and start and end:
        if end < start:
            start, end = end, start
        length = (end - start).days + 1
        p_e = start - timedelta(days=1)
        p_s = p_e - timedelta(days=length - 1)
        return Period("personnalise", "Période personnalisée", start, end, p_s, p_e, "Période précédente équivalente")

    # Par défaut : année en cours
    s, e = date(year, 1, 1), date(year, 12, 31)
    p_s, p_e = date(year - 1, 1, 1), date(year - 1, 12, 31)
    return Period("annee", f"Année {year}", s, e, p_s, p_e, f"Année {year - 1}")


@dataclass
class ExpenseSummary:
    total_ht: Decimal = Decimal("0")
    total_vat: Decimal = Decimal("0")
    total_ttc: Decimal = Decimal("0")
    count: int = 0
    unverified_count: int = 0
    without_factor_count: int = 0
    without_factor_amount: Decimal = Decimal("0")

    @property
    def verified_share_pct(self) -> Decimal:
        if self.count == 0:
            return Decimal("0")
        return (Decimal(self.count - self.unverified_count) / Decimal(self.count) * 100).quantize(
            Decimal("0.1"), ROUND_HALF_UP
        )


def summarize_expenses(expenses: Iterable[Any]) -> ExpenseSummary:
    """Totaux financiers d'une liste de dépenses."""
    summary = ExpenseSummary()
    for expense in expenses:
        amount_ht = to_decimal(getattr(expense, "amount_ht", 0)) or Decimal("0")
        vat = to_decimal(getattr(expense, "vat_amount", 0)) or Decimal("0")
        ttc = to_decimal(getattr(expense, "amount_ttc", 0)) or Decimal("0")
        summary.total_ht += amount_ht
        summary.total_vat += vat
        summary.total_ttc += ttc
        summary.count += 1
        status = getattr(expense, "verification_status", "a_verifier")
        if status != "verifiee":
            summary.unverified_count += 1
        if getattr(expense, "emission_factor_id", None) is None:
            summary.without_factor_count += 1
            summary.without_factor_amount += amount_ht
    summary.total_ht = summary.total_ht.quantize(Decimal("0.01"), ROUND_HALF_UP)
    summary.total_vat = summary.total_vat.quantize(Decimal("0.01"), ROUND_HALF_UP)
    summary.total_ttc = summary.total_ttc.quantize(Decimal("0.01"), ROUND_HALF_UP)
    return summary


def category_breakdown(expenses: Iterable[Any], order: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Répartition des dépenses par catégorie (montants HT, part, nombre)."""
    order = order or EXPENSE_CATEGORIES
    totals: dict[str, dict[str, Any]] = {}
    for expense in expenses:
        code = getattr(expense, "category", "autres")
        bucket = totals.setdefault(code, {"code": code, "ht": Decimal("0"), "count": 0})
        bucket["ht"] += to_decimal(getattr(expense, "amount_ht", 0)) or Decimal("0")
        bucket["count"] += 1
    grand_total = sum((bucket["ht"] for bucket in totals.values()), Decimal("0"))
    rows: list[dict[str, Any]] = []
    for code, bucket in totals.items():
        share = (
            (bucket["ht"] / grand_total * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
            if grand_total > 0
            else Decimal("0")
        )
        rows.append(
            {
                "code": code,
                "label": order.get(code, code),
                "ht": bucket["ht"],
                "count": bucket["count"],
                "share_pct": share,
            }
        )
    rows.sort(key=lambda row: row["ht"], reverse=True)
    return rows


def emissions_breakdown(carbon_records: Iterable[Any]) -> tuple[EmissionSummary, list[dict[str, Any]]]:
    """Synthèse carbone + répartition par catégorie."""
    records = list(carbon_records)
    summary = summarize_records(records)
    rows: list[dict[str, Any]] = []
    for code, kg in summary.by_category.items():
        share = (
            (kg / summary.total_kg * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
            if summary.total_kg > 0
            else Decimal("0")
        )
        rows.append(
            {
                "code": code,
                "label": CARBON_CATEGORIES.get(code, code),
                "kg": kg,
                "share_pct": share,
            }
        )
    rows.sort(key=lambda row: row["kg"], reverse=True)
    return summary, rows


def evolution_pct(current: Decimal, previous: Decimal) -> Decimal | None:
    """Évolution en % — ``None`` si l'une des valeurs manque ou si la base est nulle."""
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def top_savings_opportunities(projects: Iterable[Any], limit: int = 5) -> list[dict[str, Any]]:
    """Principales opportunités d'économie déclarées dans les décisions."""
    rows: list[dict[str, Any]] = []
    for project in projects:
        for option in getattr(project, "options", []) or []:
            annual_savings = to_decimal(getattr(option, "annual_savings", 0)) or Decimal("0")
            if annual_savings <= 0:
                continue
            rows.append(
                {
                    "project_id": getattr(project, "id", None),
                    "project_title": getattr(project, "title", ""),
                    "option_name": getattr(option, "name", ""),
                    "annual_savings": annual_savings,
                    "supplier": getattr(option, "supplier", ""),
                    "is_demo": bool(getattr(project, "is_demo", False)),
                }
            )
    rows.sort(key=lambda row: row["annual_savings"], reverse=True)
    return rows[:limit]


def parse_date(value: Any, default: date | None = None) -> date | None:
    """Analyse une date (formats français, ISO, Excel)."""
    if value in (None, ""):
        return default
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(getattr(value, "date")):
        try:
            return value.date()
        except Exception:  # pragma: no cover - défensive
            pass
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            from datetime import datetime as _dt

            return _dt.strptime(text, fmt).date()
        except ValueError:
            continue
    return default
