"""Tests de l'analyse de sensibilité et des scénarios prédéfinis."""

from __future__ import annotations

from decimal import Decimal

from app.calc.decision import OptionInput
from app.calc.scenarios import PRESET_DEFINITIONS, preset_params, run_scenarios
from app.calc.sensitivity import sensitivity_analysis, sensitivity_summary


def options():
    """A : coûts variables élevés (part énergie), forte émission. B : sobre et peu variable."""
    a = OptionInput.from_dict(
        {
            "name": "Chaudière fioul",
            "purchase_cost": 80000,
            "annual_opex": 24000,
            "annual_energy_share_pct": 100,
            "annual_emissions_kg": 45000,
            "confidence": "haute",
        },
        key="a",
        index=0,
    )
    b = OptionInput.from_dict(
        {
            "name": "Chaudière biomasse",
            "purchase_cost": 95000,
            "annual_opex": 17000,
            "annual_energy_share_pct": 60,
            "annual_emissions_kg": 40000,
            "confidence": "moyenne",
        },
        key="b",
        index=1,
    )
    return [a, b]


def test_sensibilite_couvre_les_six_hypotheses():
    items = sensitivity_analysis(options(), 5)
    drivers = [item.driver for item in items]
    assert set(drivers) == {
        "energy_price_delta_pct",
        "transport_delta_pct",
        "savings_delta_pct",
        "activity_volume_delta_pct",
        "emission_factor_delta_pct",
        "lifetime_delta_years",
    }
    # Classement par influence décroissante : d'abord l'écart de coût, puis l'écart d'émissions
    swings = [(item.cost_swing, item.emissions_swing or Decimal("0")) for item in items]
    assert swings == sorted(swings, reverse=True)
    assert items[0].cost_swing == Decimal("13800.00")  # ±10 % de prix de l'énergie sur le fioul


def test_le_prix_de_lenergie_est_le_levier_principal_ici():
    items = sensitivity_analysis(options(), 5)
    assert items[0].driver == "energy_price_delta_pct"
    assert items[0].cost_swing > Decimal("0")
    assert items[0].label == "Prix de l'énergie"
    assert items[0].low_case == "−10 %"
    assert items[0].high_case == "+10 %"


def test_bascule_de_classement_detectee():
    """Un écart annuel faible peut s'inverser : la sensibilité doit le signaler."""
    a = OptionInput.from_dict(
        {
            "name": "Option A (fioul)",
            "purchase_cost": 100000,
            "annual_opex": 20000,
            "annual_energy_share_pct": 100,  # entièrement exposée au prix de l'énergie
            "annual_emissions_kg": 45000,
        },
        key="a",
        index=0,
    )
    b = OptionInput.from_dict(
        {
            "name": "Option B (contrat à prix fixe)",
            "purchase_cost": 108000,
            "annual_opex": 18000,  # coût fixe : insensible au prix de l'énergie
            "annual_emissions_kg": 40000,
        },
        key="b",
        index=1,
    )
    items = sensitivity_analysis([a, b], 5, perturbation_pct=15)
    energy = next(item for item in items if item.driver == "energy_price_delta_pct")
    assert energy.base_cost_delta == Decimal("2000.00")     # A coûte 2 000 DH de plus au départ
    assert energy.cost_delta_low == Decimal("-13000.00")    # −15 % : A devient la moins chère
    assert energy.cost_delta_high == Decimal("17000.00")
    assert energy.can_flip_ranking is True
    assert energy.cost_delta_low < 0 < energy.cost_delta_high


def test_hypothese_inactive_est_annotee():
    """Sans part d'énergie déclarée ni émissions, les hypothèses correspondantes n'ont aucun effet."""
    a = OptionInput.from_dict({"name": "Option A", "purchase_cost": 1000, "annual_opex": 500}, key="a", index=0)
    b = OptionInput.from_dict({"name": "Option B", "purchase_cost": 2000, "annual_opex": 100}, key="b", index=1)
    items = sensitivity_analysis([a, b], 5)
    energy = next(item for item in items if item.driver == "energy_price_delta_pct")
    assert energy.cost_swing == Decimal("0")
    assert "Aucune option ne précise la part d'énergie" in energy.note
    emissions = next(item for item in items if item.driver == "emission_factor_delta_pct")
    assert emissions.note.startswith("Sans données d'émissions")
    assert emissions.emissions_swing is None


def test_resume_de_sensibilite():
    items = sensitivity_analysis(options(), 5)
    lines = sensitivity_summary(items, 5, limit=2)
    assert lines
    assert lines[0].startswith("Prix de l'énergie :")
    assert "fait varier l'écart de coût" in lines[0]


def test_sensibilite_avec_une_seule_option():
    a = OptionInput.from_dict({"name": "Unique", "purchase_cost": 1000}, key="a", index=0)
    assert sensitivity_analysis([a], 5) == []


def test_scenarios_preset_et_personnalises():
    outcomes = run_scenarios(options(), 5, custom=[{"label": "Gasoil +20 %", "energy_price_delta_pct": 20}])
    kinds = [outcome.kind for outcome in outcomes]
    assert kinds[:3] == ["base", "optimiste", "defavorable"]
    assert len(outcomes) == 4

    base = outcomes[0]
    assert base.label == PRESET_DEFINITIONS["base"]["label"]
    assert all(delta == Decimal("0.00") for delta in base.cost_deltas.values())
    assert any("scénario de base" in line.lower() for line in base.summary_lines)

    optimiste = next(o for o in outcomes if o.kind == "optimiste")
    defavorable = next(o for o in outcomes if o.kind == "defavorable")
    assert defavorable.cost_deltas["a"] > Decimal("0")     # la facture du fioul augmente
    assert optimiste.cost_deltas["a"] < Decimal("0")       # l'énergie baisse
    assert defavorable.emissions_deltas["a"] > Decimal("0")  # facteurs d'émission majorés
    assert any("à examiner avec attention" in line or "stable" in line for line in defavorable.summary_lines)

    custom = outcomes[3]
    assert custom.label == "Gasoil +20 %"
    assert custom.params.energy_price_delta_pct == Decimal("20")
    assert "prix de l'énergie +20 %" in custom.params.description()


def test_preset_optimiste_ne_modifie_pas_les_options_du_catalogue():
    """Les scénarios ne changent jamais les données saisies : ils recalculent seulement."""
    a, b = options()
    avant = (a.purchase_cost, a.annual_opex, a.annual_emissions_kg)
    run_scenarios([a, b], 5)
    assert (a.purchase_cost, a.annual_opex, a.annual_emissions_kg) == avant


def test_preset_inconnu_renvoie_les_hypotheses_de_base():
    params = preset_params("inexistant")
    assert params.is_base
    assert params.label == "Scénario personnalisé"
