"""Tests du calcul des émissions et de l'agrégation du registre carbone."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.calc.emissions import compute_emissions_kg, status_from_method, summarize_records, to_tonnes


def test_formule_generale_quantite_fois_facteur():
    # Formule du cahier des charges : émissions = quantité d'activité × facteur d'émission
    assert compute_emissions_kg(Decimal("15000"), Decimal("0.0811")) == Decimal("1216.5")
    assert compute_emissions_kg(6200, Decimal("2.68")) == Decimal("16616")
    assert compute_emissions_kg(1, 1) == Decimal("1")


def test_formule_refuse_les_valeurs_incoherentes():
    with pytest.raises(ValueError):
        compute_emissions_kg(None, Decimal("1"))
    with pytest.raises(ValueError):
        compute_emissions_kg(Decimal("10"), None)
    with pytest.raises(ValueError):
        compute_emissions_kg(Decimal("-1"), Decimal("2"))
    with pytest.raises(ValueError):
        compute_emissions_kg(Decimal("10"), Decimal("-0.5"))


def test_conversion_en_tonnes():
    assert to_tonnes(25000) == Decimal("25")
    assert to_tonnes(1000) == Decimal("1")
    assert to_tonnes(0) == Decimal("0")
    assert to_tonnes(None) == Decimal("0")


def test_statut_deduit_de_la_methode():
    assert status_from_method("mesure") == "mesure"
    assert status_from_method("calcule") == "calcule"
    assert status_from_method("estime") == "estime"
    assert status_from_method("monetaire") == "estime"  # une estimation monétaire reste une estimation
    assert status_from_method(None) == "calcule"


def test_synthese_du_registre():
    records = [
        {"kgco2e": "12000", "status": "mesure", "method": "mesure", "category": "energie"},
        {"kgco2e": "8000", "status": "calcule", "method": "calcule", "category": "energie"},
        {"kgco2e": "2000", "status": "estime", "method": "monetaire", "category": "achats"},
        {"kgco2e": "1000", "status": "estime", "method": "estime", "category": "dechets"},
    ]
    summary = summarize_records(records)

    assert summary.total_kg == Decimal("23000.000")
    assert summary.total_t == Decimal("23")
    assert summary.measured_kg == Decimal("12000")
    assert summary.calculated_kg == Decimal("8000")
    assert summary.estimated_kg == Decimal("3000")
    assert summary.monetary_kg == Decimal("2000")
    assert summary.record_count == 4
    assert summary.by_category["energie"] == Decimal("20000")
    # Part estimée = 3 000 / 23 000 ≈ 13,0 %
    assert summary.estimated_share_pct == Decimal("13.0")
    # Part strictement monétaire = 2 000 / 23 000 ≈ 8,7 %
    assert summary.monetary_share_pct == Decimal("8.7")


def test_synthese_vide():
    summary = summarize_records([])
    assert summary.total_kg == Decimal("0")
    assert summary.record_count == 0
    assert summary.estimated_share_pct == Decimal("0")
