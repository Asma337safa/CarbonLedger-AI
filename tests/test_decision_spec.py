"""Tests du comparateur — l'exemple chiffré du cahier des charges doit tomber juste.

Exemple de référence (5 ans) :
    Option A : achat 80 000 DH + 24 000 DH/an = 200 000 DH, 45 t CO₂e/an → 225 t
    Option B : achat 95 000 DH + 17 000 DH/an = 180 000 DH, 40 t CO₂e/an → 200 t
    Économie : 20 000 DH · Émissions évitées : 5 t/an, soit 25 t cumulées
    Coût par tonne évitée : (180 000 − 200 000) ÷ 25 = −800 DH/t (double gain)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.calc.decision import (
    COST_PER_TONNE_FORMULA,
    OptionInput,
    ScenarioParams,
    build_comparison,
    compare_options,
    compute_option,
    validate_horizon,
)
from app.calc.formatting import NBSP
from app.errors import ValidationError


def option_a(**overrides) -> OptionInput:
    data = {
        "key": "a",
        "name": "Chaudière fioul",
        "purchase_cost": Decimal("80000"),
        "annual_opex": Decimal("24000"),
        "annual_emissions_kg": Decimal("45000"),
        "confidence": "haute",
    }
    data.update(overrides)
    return OptionInput.from_dict(data, key=data.pop("key"), index=0)


def option_b(**overrides) -> OptionInput:
    data = {
        "key": "b",
        "name": "Chaudière biomasse",
        "purchase_cost": Decimal("95000"),
        "annual_opex": Decimal("17000"),
        "annual_emissions_kg": Decimal("40000"),
        "confidence": "moyenne",
    }
    data.update(overrides)
    return OptionInput.from_dict(data, key=data.pop("key"), index=1)


# ---------------------------------------------------------------------------
# Exemple de référence
# ---------------------------------------------------------------------------
def test_exemple_du_cahier_des_charges():
    comparison = compare_options([option_a(), option_b()], horizon_years=5)

    a = comparison.by_key["a"]
    b = comparison.by_key["b"]

    # Coûts totaux
    assert a.total_cost == Decimal("200000.00")
    assert b.total_cost == Decimal("180000.00")
    assert a.initial_outlay == Decimal("80000.00")
    assert b.initial_outlay == Decimal("95000.00")

    # Émissions cumulées
    assert a.annual_emissions_t == Decimal("45.000")
    assert b.annual_emissions_t == Decimal("40.000")
    assert a.total_emissions_t == Decimal("225.000")
    assert b.total_emissions_t == Decimal("200.000")

    # Comparaison deux à deux : économie et coût par tonne évitée
    pair = comparison.pairs[0]
    assert pair.cost_delta == Decimal("20000.00")           # A coûte 20 000 DH de plus
    assert pair.cheaper_key == "b"                          # B est la moins chère
    assert pair.cleaner_key == "b"                          # B est aussi la moins émettrice
    assert pair.avoided_t == Decimal("25.000")              # 5 t/an × 5 ans
    assert pair.cost_per_tonne_avoided == Decimal("-800.00")  # double gain
    assert pair.double_gain is True

    # Classements
    assert comparison.cheapest_key == "b"
    assert comparison.greenest_key == "b"
    assert comparison.best_treasury_key == "a"              # A demande moins de trésorerie au départ
    assert comparison.frontier == ["b"]                     # B domine A (moins chère et moins émettrice)
    assert pair.dominated_by == "b"


def test_phrase_de_comparaison_sans_invention_de_chiffre():
    comparison = compare_options([option_a(), option_b()], horizon_years=5)
    pair = comparison.pairs[0]
    texte = " ".join(pair.interpretation_parts)
    assert f"20{NBSP}000,00{NBSP}DH" in texte
    assert "25,00 t CO₂e" in texte
    assert f"800,00{NBSP}DH économisés par tonne évitée" in texte
    # Le surcoût initial est compensé : B est plus chère à l'achat (15 000 DH) mais moins chère à l'usage
    assert pair.break_even is not None
    assert pair.break_even["favors_key"] == "b"
    assert pair.break_even["years"] == "2.143"  # 15 000 DH / 7 000 DH par an
    assert any("surcoût initial" in part for part in pair.interpretation_parts)


def test_formule_du_cout_par_tonne_est_documentee():
    assert "coût par tonne" in COST_PER_TONNE_FORMULA.lower()
    assert "÷" in COST_PER_TONNE_FORMULA


def test_surcout_du_choix_bas_carbone_positif():
    """Quand l'option propre est plus chère, le coût par tonne évitée est positif."""
    # A : 200 000 DH et 225 t (sale et chère) ; B : 220 000 DH et 100 t (propre mais chère)
    comparison = compare_options(
        [
            option_a(),
            option_b(purchase_cost=Decimal("135000"), annual_opex=Decimal("17000"), annual_emissions_kg=Decimal("20000")),
        ],
        horizon_years=5,
    )
    pair = comparison.pairs[0]
    assert pair.cheaper_key == "a"
    assert pair.cleaner_key == "b"
    assert pair.avoided_t == Decimal("125.000")
    assert pair.cost_per_tonne_avoided == Decimal("160.00")  # (220 000 − 200 000) / 125
    assert pair.double_gain is False
    assert f"surcoût de 160,00{NBSP}DH par tonne évitée" in " ".join(pair.interpretation_parts)


# ---------------------------------------------------------------------------
# Détails de calcul
# ---------------------------------------------------------------------------
def test_resultat_dune_option_seule():
    result = compute_option(option_a(), 5)
    assert result.annual_net_costs == [Decimal("24000.00")] * 5
    assert result.total_opex == Decimal("120000.00")
    assert result.cost_curve[-1] == Decimal("200000.00")
    assert result.cash_curve[-1] == Decimal("-200000.00")
    assert result.cash_curve[0] == Decimal("-80000.00")
    assert len(result.emissions_curve_t) == 6


def test_transport_et_economies_annuelles():
    option = OptionInput.from_dict(
        {
            "name": "Solution avec transport et économies",
            "purchase_cost": 100000,
            "transport_cost": 5000,
            "annual_opex": 30000,
            "annual_maintenance": 4000,
            "annual_savings": 10000,
        },
        key="a",
    )
    result = compute_option(option, 5)
    assert result.initial_outlay == Decimal("105000.00")
    assert result.annual_net_costs[0] == Decimal("24000.00")  # 30 000 + 4 000 − 10 000
    assert result.total_cost == Decimal("225000.00")
    assert result.total_savings == Decimal("50000.00")


def test_duree_de_vie_inferieure_a_lhorizon_signalee_sans_reinvestissement():
    option = OptionInput.from_dict(
        {"name": "Machine courte durée", "purchase_cost": 10000, "annual_opex": 1000, "useful_life_years": 3},
        key="a",
    )
    result = compute_option(option, 5)
    assert any("durée d'utilisation" in warning.lower() for warning in result.warnings)
    assert any("Aucun remplacement n'est chiffré" in warning for warning in result.warnings)
    # Aucun réinvestissement n'est inventé : le coût reste 10 000 + 5 × 1 000
    assert result.total_cost == Decimal("15000.00")


def test_emissions_absentes_ne_sont_pas_inventees():
    option = OptionInput.from_dict({"name": "Option sans carbone", "purchase_cost": 1000}, key="a")
    result = compute_option(option, 5)
    assert result.total_emissions_t is None
    assert result.emissions_known is False
    assert any("émissions non renseignées" in warning.lower() for warning in result.warnings)


def test_comparaison_carbone_partielle_est_annoncee():
    comparison = compare_options([option_a(), OptionInput.from_dict({"name": "Sans carbone"}, key="b")], 5)
    pair = comparison.pairs[0]
    assert pair.cost_per_tonne_avoided is None
    assert pair.avoided_t is None
    assert "indisponible" in " ".join(pair.interpretation_parts)
    assert any("Comparaison carbone partielle" in note for note in comparison.notes)


def test_prix_interne_du_carbone_modifie_le_cout_etendu_seulement():
    comparison = compare_options([option_a(), option_b()], 5, carbon_price=Decimal("500"))
    assert comparison.by_key["a"].total_cost == Decimal("200000.00")  # coût financier inchangé
    # Coût étendu : 200 000 + 225 t × 500 DH = 312 500 DH ; 180 000 + 200 × 500 = 280 000 DH
    assert comparison.extended_cost["a"] == Decimal("312500.00")
    assert comparison.extended_cost["b"] == Decimal("280000.00")
    assert comparison.extended_best_key == "b"
    assert any("Prix interne du carbone appliqué" in note for note in comparison.notes)


def test_aucun_carbone_par_defaut():
    comparison = compare_options([option_a(), option_b()], 5)
    assert comparison.carbon_price == Decimal("0")
    assert any("Aucun prix interne du carbone" in note for note in comparison.notes)


def test_actualisation_optionnelle():
    result = compute_option(option_a(), 5, ScenarioParams(discount_rate_pct=Decimal("5")))
    assert result.npv is not None
    # 80 000 + 24 000 × (1/1,05 + … + 1/1,05⁵) = 183 907,44 DH (actualisé au taux déclaré)
    assert result.npv == Decimal("183907.44")
    assert result.npv < result.total_cost
    assert any("Actualisation appliquée" in assumption for assumption in result.assumptions)
    result_sans_taux = compute_option(option_a(), 5)
    assert result_sans_taux.npv is None


def test_parametres_de_scenario_appliques():
    """Le scénario module l'énergie (part déclarée), l'activité et les émissions."""
    option = OptionInput.from_dict(
        {
            "name": "Option avec part énergie",
            "purchase_cost": 10000,
            "annual_opex": 10000,
            "annual_energy_share_pct": 100,
            "annual_emissions_kg": 10000,
        },
        key="a",
    )
    base = compute_option(option, 5)
    hausse = compute_option(option, 5, ScenarioParams(energy_price_delta_pct=Decimal("50")))
    assert base.total_cost == Decimal("60000.00")
    assert hausse.total_cost == Decimal("85000.00")  # 10 000 achat + 5 × 15 000
    baisse_facteurs = compute_option(option, 5, ScenarioParams(emission_factor_delta_pct=Decimal("-20")))
    assert baisse_facteurs.total_emissions_t == Decimal("40.000")  # 10 t/an − 20 % = 8 t/an
    volume = compute_option(option, 5, ScenarioParams(activity_volume_delta_pct=Decimal("10")))
    assert volume.total_cost == Decimal("65000.00")  # activité +10 % sur les coûts variables


def test_part_energie_absente_signalee():
    option = OptionInput.from_dict({"name": "Sans part énergie", "purchase_cost": 1000, "annual_opex": 5000}, key="a")
    result = compute_option(option, 5, ScenarioParams(energy_price_delta_pct=Decimal("20")))
    assert any("part d'énergie non renseignée" in warning for warning in result.warnings)
    assert result.total_cost == Decimal("26000.00")  # aucun effet appliqué


# ---------------------------------------------------------------------------
# Validation des entrées
# ---------------------------------------------------------------------------
def test_horizon_borne():
    assert validate_horizon(5) == 5
    assert validate_horizon("12") == 12
    with pytest.raises(ValidationError):
        validate_horizon(0)
    with pytest.raises(ValidationError):
        validate_horizon(31)


def test_options_invalides_refusees():
    with pytest.raises(ValidationError) as info:
        OptionInput.from_dict({"name": "Coûts négatifs", "purchase_cost": -1}, key="a", index=0)
    assert "options[0].purchase_cost" in info.value.fields

    with pytest.raises(ValidationError):
        OptionInput.from_dict({"name": "Part énergie > 100 %", "annual_energy_share_pct": 120}, index=1)

    with pytest.raises(ValidationError):
        OptionInput.from_dict({"name": "Confiance inconnue", "confidence": "certaine"}, index=0)

    with pytest.raises(ValidationError):
        OptionInput.from_dict({"name": "Durée nulle", "useful_life_years": 0}, index=0)


def test_comparaison_exige_deux_options():
    with pytest.raises(ValidationError):
        build_comparison([compute_option(option_a(), 5)])


def test_prix_carbone_negatif_refuse():
    with pytest.raises(ValidationError):
        build_comparison([compute_option(option_a(), 5), compute_option(option_b(), 5)], carbon_price=-1)


def test_trois_options_frontiere_de_compromis():
    """Avec trois options, la frontière contient les compromis non dominés."""
    tres_propre_chere = option_b(
        key="c",
        name="Chaudière biomasse haut de gamme",
        purchase_cost=Decimal("130000"),
        annual_emissions_kg=Decimal("10000"),
    )
    comparison = compare_options([option_a(), option_b(), tres_propre_chere], 5, carbon_price=Decimal("0"))
    assert comparison.cheapest_key == "b"          # 180 000 DH
    assert comparison.greenest_key == "c"          # 50 t cumulées
    assert set(comparison.frontier) == {"b", "c"}  # A est dominée (plus chère et plus émettrice que B)
    assert len(comparison.pairs) == 3
    assert any("frontière de compromis" in note for note in comparison.notes)
