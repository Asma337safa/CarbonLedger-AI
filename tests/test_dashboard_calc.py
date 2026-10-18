"""Tests des agrégations du tableau de bord (périodes, dépenses, carbone)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.calc.dashboard import (
    category_breakdown,
    emissions_breakdown,
    evolution_pct,
    resolve_period,
    summarize_expenses,
    top_savings_opportunities,
)


def test_periode_annee_et_periode_precedente():
    period = resolve_period("annee", today=date(2026, 6, 15))
    assert (period.start, period.end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert (period.previous_start, period.previous_end) == (date(2025, 1, 1), date(2025, 12, 31))
    assert period.comparable is True


def test_periode_mois_glissante_avec_bascule_dannee():
    period = resolve_period("mois", today=date(2026, 1, 10))
    assert (period.start, period.end) == (date(2026, 1, 1), date(2026, 1, 31))
    assert (period.previous_start, period.previous_end) == (date(2025, 12, 1), date(2025, 12, 31))


def test_periode_trimestre():
    period = resolve_period("trimestre", today=date(2026, 5, 20))
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert (period.previous_start, period.previous_end) == (date(2026, 1, 1), date(2026, 3, 31))
    assert period.label == "Trimestre 2 — 2026"


def test_periode_12_mois_et_historique_complet():
    period = resolve_period("12_mois", today=date(2026, 6, 30))
    assert period.end == date(2026, 6, 30)
    assert period.start == date(2025, 7, 1)
    tout = resolve_period("tout", today=date(2026, 6, 30))
    assert tout.comparable is False
    assert tout.previous_start is None
    # « Tout l'historique » n'a aucune borne haute : les lignes datées plus tard
    # (factures prévisionnelles) restent visibles, comme au tableau de bord.
    assert tout.start <= date(2020, 1, 1)
    assert tout.end > date(2099, 12, 31)
    assert tout.range_slug == "tout"
    # Les périodes bornées gardent un fragment de nom de fichier explicite.
    assert period.range_slug == "2025-07-01_2026-06-30"


def test_periode_personnalisee_inversee_est_corrigee():
    period = resolve_period("personnalise", start=date(2026, 3, 31), end=date(2026, 3, 1))
    assert (period.start, period.end) == (date(2026, 3, 1), date(2026, 3, 31))
    assert period.previous_end == date(2026, 2, 28)


def test_periode_personnalisee_sans_bornes_retombe_sur_lannee():
    period = resolve_period("personnalise", today=date(2026, 6, 30))
    assert period.key == "annee"


# ---------------------------------------------------------------------------
# Dépenses
# ---------------------------------------------------------------------------
def test_synthese_des_depenses():
    expenses = [
        SimpleNamespace(
            amount_ht=Decimal("18000"),
            vat_amount=Decimal("3600"),
            amount_ttc=Decimal("21600"),
            verification_status="verifiee",
            emission_factor_id=1,
        ),
        SimpleNamespace(
            amount_ht=Decimal("5000"),
            vat_amount=Decimal("1000"),
            amount_ttc=Decimal("6000"),
            verification_status="a_verifier",
            emission_factor_id=None,
        ),
        SimpleNamespace(
            amount_ht=Decimal("2000"),
            vat_amount=Decimal("0"),
            amount_ttc=Decimal("2000"),
            verification_status="verifiee",
            emission_factor_id=2,
        ),
    ]
    summary = summarize_expenses(expenses)
    assert summary.total_ht == Decimal("25000.00")
    assert summary.total_vat == Decimal("4600.00")
    assert summary.total_ttc == Decimal("29600.00")
    assert summary.count == 3
    assert summary.unverified_count == 1
    assert summary.verified_share_pct == Decimal("66.7")
    assert summary.without_factor_count == 1
    assert summary.without_factor_amount == Decimal("5000")


def test_repartition_par_categorie_ordonnee():
    expenses = [
        SimpleNamespace(amount_ht=Decimal("100"), category="energie"),
        SimpleNamespace(amount_ht=Decimal("300"), category="transport"),
        SimpleNamespace(amount_ht=Decimal("50"), category="energie"),
    ]
    rows = category_breakdown(expenses)
    assert [row["code"] for row in rows] == ["transport", "energie"]
    assert rows[0]["ht"] == Decimal("300")
    assert rows[0]["label"] == "Transport"
    assert rows[0]["count"] == 1
    # 300 / 450 = 66,7 % et 150 / 450 = 33,3 %
    assert rows[0]["share_pct"] == Decimal("66.7")
    assert rows[1]["share_pct"] == Decimal("33.3")
    assert sum(row["share_pct"] for row in rows) == Decimal("100.0")


def test_evolution_pourcentage():
    assert evolution_pct(Decimal("120"), Decimal("100")) == Decimal("20.0")
    assert evolution_pct(Decimal("100"), Decimal("200")) == Decimal("-50.0")
    assert evolution_pct(Decimal("100"), Decimal("0")) is None
    assert evolution_pct(None, Decimal("10")) is None


# ---------------------------------------------------------------------------
# Carbone
# ---------------------------------------------------------------------------
def test_repartition_carbone_et_part_estimee():
    records = [
        {"kgco2e": "12000", "status": "mesure", "category": "energie"},
        {"kgco2e": "6000", "status": "calcule", "category": "energie"},
        {"kgco2e": "2000", "status": "estime", "category": "achats"},
    ]
    summary, rows = emissions_breakdown(records)
    assert summary.total_t == Decimal("20")
    assert summary.estimated_share_pct == Decimal("10.0")
    assert rows[0]["code"] == "energie"
    assert rows[0]["kg"] == Decimal("18000")
    assert rows[0]["share_pct"] == Decimal("90.0")
    assert rows[0]["label"] == "Énergie (combustion et électricité)"


def test_top_opportunites_declarees():
    projects = [
        SimpleNamespace(
            id=1,
            title="Projet économies",
            is_demo=False,
            options=[
                SimpleNamespace(name="Biomasse", supplier="BioÉnergie", annual_savings=Decimal("5000")),
                SimpleNamespace(name="Sans économie", supplier="", annual_savings=Decimal("0")),
            ],
        ),
        SimpleNamespace(
            id=2,
            title="Projet sans économie",
            is_demo=True,
            options=[SimpleNamespace(name="Isolation", supplier="IsoPro", annual_savings=Decimal("12000"))],
        ),
    ]
    rows = top_savings_opportunities(projects, limit=5)
    assert len(rows) == 2  # les options sans économie déclarée sont ignorées
    assert rows[0]["project_title"] == "Projet sans économie"
    assert rows[0]["annual_savings"] == Decimal("12000")
    assert rows[0]["is_demo"] is True
    assert rows[1]["option_name"] == "Biomasse"
    assert top_savings_opportunities(projects, limit=1) == rows[:1]
