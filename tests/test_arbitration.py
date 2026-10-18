"""Tests du moteur d'arbitrage : recommandation explicable, jamais un « gagnant » inventé."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.calc.arbitration import arbitrate
from app.calc.decision import OptionInput, compare_options
from app.errors import ValidationError


def make_options():
    """A : moins chère à l'achat mais plus chère et plus émettrice sur 5 ans.

    B : coûteuse à l'achat, moins chère à l'usage et moins émettrice.
    """
    a = OptionInput.from_dict(
        {
            "name": "Chaudière fioul",
            "purchase_cost": 80000,
            "annual_opex": 24000,
            "annual_emissions_kg": 45000,
            "emissions_basis": "calcule",
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
            "annual_emissions_kg": 40000,
            "emissions_basis": "estime",
            "confidence": "moyenne",
        },
        key="b",
        index=1,
    )
    return [a, b]


def test_priorite_cout_classe_par_cout_total():
    comparison = compare_options(make_options(), 5)
    result = arbitrate(comparison, "cout")
    assert result.recommended_key == "b"
    assert result.ranking[0].key == "b"
    assert result.basis == "cout"
    assert result.priority_label == "Réduire les coûts totaux"
    assert "coût total le plus faible" in result.recommendation_title
    assert result.method_note.startswith("Méthode :")


def test_priorite_tresorerie_classe_par_mise_de_fonds():
    comparison = compare_options(make_options(), 5)
    result = arbitrate(comparison, "tresorerie")
    assert result.recommended_key == "a"  # 80 000 DH vs 95 000 DH
    assert "trésorerie" in result.recommendation_title.lower()
    # La fiche de A signale explicitement le surcoût de fonctionnement sur 5 ans
    fiche_a = next(item for item in result.ranking if item.key == "a")
    assert any("Coût total supérieur" in disadvantage for disadvantage in fiche_a.disadvantages)


def test_priorite_emissions_classe_par_emissions_cumulees():
    comparison = compare_options(make_options(), 5)
    result = arbitrate(comparison, "emissions")
    assert result.recommended_key == "b"
    assert "émissions cumulées" in result.recommendation_title.lower()


def test_score_equilibre_et_ponderation_annoncee():
    comparison = compare_options(make_options(), 5)
    result = arbitrate(comparison, "equilibre")
    assert result.recommended_key == "b"
    assert all(item.composite_score is not None for item in result.ranking)
    # Les scores restent bornés sur 0-100
    for item in result.ranking:
        assert Decimal("0") <= item.composite_score <= Decimal("100")
    assert any("pondération égale" in paragraph for paragraph in result.recommendation_paragraphs)
    assert any("Score combiné" in paragraph for paragraph in result.recommendation_paragraphs)


def test_priorite_emissions_sans_donnees_carbone_le_dit_clairement():
    options = [
        OptionInput.from_dict({"name": "Option A", "purchase_cost": 1000, "annual_opex": 500}, key="a", index=0),
        OptionInput.from_dict({"name": "Option B", "purchase_cost": 2000, "annual_opex": 100}, key="b", index=1),
    ]
    comparison = compare_options(options, 5)
    result = arbitrate(comparison, "emissions")
    assert "données carbone insuffisantes" in result.recommendation_title
    assert any("Émissions non renseignées" in caveat for caveat in result.caveats)
    for item in result.ranking:
        assert any("Émissions non renseignées" in disadvantage for disadvantage in item.disadvantages)


def test_aucune_option_dominante_signalee_dans_les_limites():
    """Un compromis coût / carbone doit rester visible : pas de gagnant unique imposé."""
    propre_chere = OptionInput.from_dict(
        {
            "name": "Solution haute performance",
            "purchase_cost": 135000,
            "annual_opex": 17000,
            "annual_emissions_kg": 20000,
            "confidence": "faible",
        },
        key="c",
        index=2,
    )
    comparison = compare_options(make_options() + [propre_chere], 5)
    result = arbitrate(comparison, "equilibre")
    assert len(set(comparison.frontier)) >= 2
    assert any("frontière de compromis" in paragraph for paragraph in result.recommendation_paragraphs)
    # Confiance faible signalée en limite
    assert any("confiance faible" in caveat.lower() for caveat in result.caveats)
    # La recommandation rappelle toujours qu'elle ne remplace pas une validation humaine
    assert any("aide à la décision" in caveat for caveat in result.caveats)


def test_cout_par_tonne_evitee_est_rappele_sans_promettre_deconomie():
    propre_chere = OptionInput.from_dict(
        {
            "name": "Solution haute performance",
            "purchase_cost": 135000,
            "annual_opex": 17000,
            "annual_emissions_kg": 20000,
        },
        key="c",
        index=2,
    )
    comparison = compare_options([make_options()[0], propre_chere], 5)
    result = arbitrate(comparison, "cout")
    texte = " ".join(result.recommendation_paragraphs)
    assert "par tonne de CO₂e évitée" in texte
    assert "n'est pas une économie financière automatique" in texte


def test_prix_interne_du_carbone_change_la_base_de_classement():
    comparison = compare_options(make_options(), 5, carbon_price=Decimal("2000"))
    result = arbitrate(comparison, "cout")
    assert result.basis == "cout_etendu"
    assert "prix interne du carbone" in result.method_note
    # 2 000 DH/t rend l'option B (moins émettrice) encore plus avantageuse
    assert result.recommended_key == "b"


def test_double_gain_est_annonce_comme_tel():
    comparison = compare_options(make_options(), 5)
    result = arbitrate(comparison, "emissions")
    texte = " ".join(result.recommendation_paragraphs)
    assert "favorable dans les deux dimensions" in texte


def test_priorite_inconnue_refusee():
    comparison = compare_options(make_options(), 5)
    with pytest.raises(ValidationError):
        arbitrate(comparison, "priorite_inexistante")


def test_arbitrage_serialisable():
    comparison = compare_options(make_options(), 5)
    payload = arbitrate(comparison, "equilibre").to_dict()
    assert set(payload) >= {
        "priority",
        "ranking",
        "recommended_key",
        "recommendation_title",
        "recommendation_paragraphs",
        "caveats",
        "method_note",
        "basis",
    }
    assert payload["ranking"][0]["rank"] == 1
