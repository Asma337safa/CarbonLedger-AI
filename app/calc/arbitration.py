"""Moteur d'arbitrage : recommandation explicable, fondée sur les calculs.

Le moteur ne distribue pas de « score vert » : il classe les options selon
la priorité choisie par l'utilisateur, expose les avantages, les
inconvénients, les coûts et les émissions de chaque option, et signale
explicitement les données manquantes. Aucun chiffre n'est inventé : toutes
les phrases sont construites à partir des résultats du moteur de calcul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..enums import PRIORITIES
from ..errors import ValidationError
from .decision import ComparisonResult, OptionResult, ZERO
from .formatting import fmt_money, fmt_number, fmt_tco2e, to_decimal

_PRIORITY_LABELS = PRIORITIES


@dataclass
class OptionAssessment:
    key: str
    name: str
    rank: int
    composite_score: Decimal | None
    advantages: list[str] = field(default_factory=list)
    disadvantages: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "rank": self.rank,
            "composite_score": str(self.composite_score) if self.composite_score is not None else None,
            "advantages": self.advantages,
            "disadvantages": self.disadvantages,
            "facts": self.facts,
        }


@dataclass
class ArbitrationResult:
    priority: str
    priority_label: str
    ranking: list[OptionAssessment]
    recommended_key: str | None
    frontier: list[str]
    recommendation_title: str
    recommendation_paragraphs: list[str]
    caveats: list[str]
    method_note: str
    basis: str  # cout | cout_etendu

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "priority_label": self.priority_label,
            "ranking": [a.to_dict() for a in self.ranking],
            "recommended_key": self.recommended_key,
            "frontier": self.frontier,
            "recommendation_title": self.recommendation_title,
            "recommendation_paragraphs": self.recommendation_paragraphs,
            "caveats": self.caveats,
            "method_note": self.method_note,
            "basis": self.basis,
        }


def _normalize(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Normalisation min-max sur 0-100 (50 si toutes les valeurs sont égales)."""
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: Decimal("50") for key in values}
    return {
        key: (((value - low) / (high - low)) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
        for key, value in values.items()
    }


def _delta_phrase(delta: Decimal) -> str:
    return f"{fmt_money(abs(delta))} de {'plus' if delta > 0 else 'moins'}"


def arbitrate(comparison: ComparisonResult, priority: str = "equilibre") -> ArbitrationResult:
    """Construit la recommandation explicable pour la priorité choisie."""
    if priority not in _PRIORITY_LABELS:
        raise ValidationError(f"Priorité inconnue : {priority}")

    results = comparison.results
    horizon = comparison.horizon_years
    carbon_price = comparison.carbon_price
    use_extended = carbon_price > ZERO and comparison.extended_best_key is not None
    basis = "cout_etendu" if use_extended else "cout"

    def cost_of(result: OptionResult) -> Decimal:
        if use_extended and comparison.extended_cost.get(result.key) is not None:
            return comparison.extended_cost[result.key]  # type: ignore[return-value]
        return result.total_cost

    cost_map = {r.key: cost_of(r) for r in results}
    upfront_map = {r.key: r.initial_outlay for r in results}
    emissions_map = {r.key: r.total_emissions_t for r in results if r.total_emissions_t is not None}
    confidence_rank = {"haute": 0, "moyenne": 1, "faible": 2}

    # Classement selon la priorité
    emissions_available = len(emissions_map) >= 2
    if priority == "cout":
        ordered = sorted(results, key=lambda r: (cost_map[r.key], r.key))
        scores = None
    elif priority == "tresorerie":
        ordered = sorted(results, key=lambda r: (upfront_map[r.key], r.annual_net_costs[0], r.key))
        scores = None
    elif priority == "emissions":
        if emissions_available:
            ordered = sorted(
                results,
                key=lambda r: (
                    emissions_map.get(r.key, Decimal("Infinity")),
                    cost_map[r.key],
                    r.key,
                ),
            )
        else:
            ordered = sorted(results, key=lambda r: (cost_map[r.key], r.key))
        scores = None
    else:  # equilibre
        cost_norm = _normalize(cost_map)
        if emissions_available:
            emissions_norm = _normalize({k: v for k, v in emissions_map.items()})
            scores = {
                r.key: (
                    (cost_norm.get(r.key, Decimal("50")) + emissions_norm.get(r.key, Decimal("50"))) / 2
                ).quantize(Decimal("0.1"), ROUND_HALF_UP)
                for r in results
            }
        else:
            scores = {r.key: cost_norm.get(r.key, Decimal("50")) for r in results}
        ordered = sorted(results, key=lambda r: (scores[r.key], r.key))

    # Fiches par option
    cheapest = comparison.by_key.get(comparison.cheapest_key)
    greenest = comparison.by_key.get(comparison.greenest_key) if comparison.greenest_key else None
    treasury_best = comparison.by_key.get(comparison.best_treasury_key)

    assessments: list[OptionAssessment] = []
    for rank, result in enumerate(ordered, start=1):
        advantages: list[str] = []
        disadvantages: list[str] = []
        facts: list[str] = []

        if cheapest and result.key == cheapest.key:
            advantages.append(f"Coût total estimé le plus faible sur {horizon} ans : {fmt_money(result.total_cost)}.")
        elif cheapest:
            delta = result.total_cost - cheapest.total_cost
            disadvantages.append(
                f"Coût total supérieur de {fmt_money(delta)} à l'option la moins chère sur {horizon} ans."
            )

        if treasury_best and result.key == treasury_best.key:
            advantages.append(f"Sortie de trésorerie initiale la plus faible : {fmt_money(result.initial_outlay)}.")
        elif treasury_best:
            delta = result.initial_outlay - treasury_best.initial_outlay
            disadvantages.append(
                f"Mise de fonds initiale supérieure de {fmt_money(delta)} à l'option la plus sobre en trésorerie."
            )

        if greenest and result.key == greenest.key:
            advantages.append(f"Émissions cumulées estimées les plus faibles : {fmt_tco2e(result.total_emissions_t)}.")
        elif greenest and result.total_emissions_t is not None and greenest.total_emissions_t is not None:
            delta = result.total_emissions_t - greenest.total_emissions_t
            disadvantages.append(
                f"Émissions cumulées supérieures de {fmt_number(delta, 2)} t CO₂e à l'option la moins émettrice."
            )
        if result.total_emissions_t is None:
            disadvantages.append("Émissions non renseignées : comparaison carbone impossible pour cette option.")

        if result.total_savings > ZERO:
            advantages.append(
                f"Économies attendues cumulées déclarées : {fmt_money(result.total_savings)} "
                "(données saisies, à confirmer par le réalisé)."
            )
        if result.npv is not None:
            facts.append(f"Coût actualisé net : {fmt_money(result.npv)}.")
        if result.annual_savings > ZERO and result.purchase_cost > ZERO:
            facts.append(
                f"Coût de fonctionnement annuel après économies : {fmt_money(result.annual_net_costs[0])}."
            )
        facts.append(f"Mise de fonds initiale : {fmt_money(result.initial_outlay)}.")
        facts.append(f"Confiance des données déclarée : {result.option.confidence}.")

        if result.option.confidence == "faible":
            disadvantages.append("Niveau de confiance déclaré faible : à documenter avant décision.")
        for warning in result.warnings:
            if "domaine" not in warning and warning not in disadvantages:
                disadvantages.append(warning)

        assessments.append(
            OptionAssessment(
                key=result.key,
                name=result.name,
                rank=rank,
                composite_score=scores.get(result.key) if scores else None,
                advantages=advantages,
                disadvantages=disadvantages,
                facts=facts,
            )
        )

    recommended = ordered[0]

    # ------------------------------------------------------------------
    # Texte de recommandation
    # ------------------------------------------------------------------
    paragraphs: list[str] = []
    priority_label = _PRIORITY_LABELS[priority]
    frontier_names = [comparison.by_key[k].name for k in comparison.frontier if k in comparison.by_key]

    if priority == "cout":
        title = f"Priorité coût : « {recommended.name} » présente le coût total le plus faible."
    elif priority == "tresorerie":
        title = f"Priorité trésorerie : « {recommended.name} » limite la sortie de fonds initiale."
    elif priority == "emissions":
        if recommended.total_emissions_t is not None:
            title = f"Priorité émissions : « {recommended.name} » présente les émissions cumulées estimées les plus faibles."
        else:
            title = "Priorité émissions : données carbone insuffisantes pour classer les options."
    else:
        title = (
            f"Compromis équilibré : « {recommended.name} » obtient le meilleur résultat combiné "
            "coût / émissions."
        )

    intro = (
        f"Sur {horizon} ans, l'option « {recommended.name} » arrive en tête selon votre priorité "
        f"« {priority_label.lower()} »."
    )
    if scores:
        intro += f" Score combiné coût-émissions : {fmt_number(scores[recommended.key], 1)}/100 (pondération égale)."
    paragraphs.append(intro)

    # Positionnement des autres options
    for other in ordered[1:3]:
        delta_cost = other.total_cost - recommended.total_cost
        if delta_cost != ZERO:
            paragraphs.append(
                f"« {other.name} » coûte {_delta_phrase(delta_cost)} sur {horizon} ans "
                f"({fmt_money(other.total_cost)} contre {fmt_money(recommended.total_cost)})."
            )
        if other.total_emissions_t is not None and recommended.total_emissions_t is not None:
            delta_em = other.total_emissions_t - recommended.total_emissions_t
            if delta_em != ZERO:
                direction = "de plus" if delta_em > 0 else "de moins"
                paragraphs.append(
                    f"Émissions cumulées de « {other.name} » : {fmt_tco2e(other.total_emissions_t)}, "
                    f"soit {fmt_number(abs(delta_em), 2)} t CO₂e {direction} que l'option retenue."
                )

    # Compromis trésorerie
    if treasury_best and recommended.key != treasury_best.key:
        extra = recommended.initial_outlay - treasury_best.initial_outlay
        if extra > ZERO:
            paragraphs.append(
                f"Point de vigilance : la mise de fonds initiale de « {recommended.name} » est supérieure de "
                f"{fmt_money(extra)} à celle de « {treasury_best.name} ». Si votre priorité est la trésorerie "
                "à court terme, vérifiez votre capacité de financement avant de retenir cette option."
            )
            pair = next(
                (
                    p
                    for p in comparison.pairs
                    if {p.a_key, p.b_key} == {recommended.key, treasury_best.key}
                ),
                None,
            )
            if pair and pair.break_even:
                years = to_decimal(pair.break_even.get("years"))
                favored = pair.break_even.get("favors_key")
                if years and favored == recommended.key:
                    paragraphs.append(
                        f"Le surcoût initial est compensé en environ {fmt_number(years, 1)} an(s) par des "
                        "coûts annuels plus faibles : c'est le délai de rattrapage estimé."
                    )

    # Coût par tonne évitée entre l'option retenue et la moins émettrice
    if greenest and recommended.total_emissions_t is not None and greenest.total_emissions_t is not None:
        pair = next(
            (p for p in comparison.pairs if {p.a_key, p.b_key} == {recommended.key, greenest.key}),
            None,
        )
        if pair and pair.avoided_t and pair.avoided_t > ZERO and pair.cost_per_tonne_avoided is not None:
            if pair.double_gain:
                paragraphs.append(
                    f"L'option « {greenest.name} » évite {fmt_number(pair.avoided_t, 2)} t CO₂e en étant aussi "
                    "la moins chère : le compromis coût / carbone est favorable dans les deux dimensions."
                )
            elif greenest.key != recommended.key:
                paragraphs.append(
                    f"Pour atteindre les émissions les plus faibles (« {greenest.name} »), le surcoût estimé est de "
                    f"{fmt_money(pair.cost_per_tonne_avoided)} par tonne de CO₂e évitée. "
                    "Une réduction d'émissions n'est pas une économie financière automatique."
                )
        elif recommended.key == greenest.key:
            # L'option retenue est aussi la moins émettrice : on l'annonce sans laisser
            # croire qu'un arbitrage a été fait contre le carbone.
            if comparison.cheapest_key == recommended.key:
                paragraphs.append(
                    f"« {recommended.name} » est à la fois l'option la moins chère et la moins émettrice "
                    f"({fmt_tco2e(recommended.total_emissions_t)} cumulées) : le compromis coût / carbone est "
                    "favorable dans les deux dimensions, sous réserve des hypothèses saisies."
                )
            else:
                eco_pair = next(
                    (
                        p
                        for p in comparison.pairs
                        if comparison.cheapest_key in (p.a_key, p.b_key) and recommended.key in (p.a_key, p.b_key)
                    ),
                    None,
                )
                surcout = ""
                if eco_pair and eco_pair.avoided_t and eco_pair.cost_per_tonne_avoided is not None:
                    surcout = (
                        f", soit {fmt_money(eco_pair.cost_per_tonne_avoided)} par tonne de CO₂e évitée "
                        "par rapport à l'option la moins chère"
                    )
                paragraphs.append(
                    f"« {recommended.name} » présente les émissions cumulées estimées les plus faibles "
                    f"({fmt_tco2e(recommended.total_emissions_t)}) pour un coût total de "
                    f"{fmt_money(recommended.total_cost)} sur {horizon} ans{surcout}."
                )

    if len(frontier_names) > 1 and not (len(frontier_names) == 1):
        paragraphs.append(
            "Plusieurs options restent en frontière de compromis ("
            + ", ".join(f"« {name} »" for name in frontier_names)
            + ") : si elles présentent des avantages différents, choisissez selon votre situation financière "
            "et vos engagements, plutôt que sur un score unique."
        )

    # Limites et avertissements
    caveats: list[str] = []
    low_confidence = [r.name for r in results if r.option.confidence == "faible"]
    if low_confidence:
        caveats.append(
            "Données à confiance faible pour : " + ", ".join(f"« {n} »" for n in low_confidence) + "."
        )
    missing = [r.name for r in results if r.total_emissions_t is None]
    if missing:
        caveats.append("Émissions non renseignées : " + ", ".join(f"« {n} »" for n in missing) + ".")
    if any(r.option.emissions_basis == "estime" for r in results):
        caveats.append(
            "Certaines émissions sont déclarées comme estimées (et non mesurées) : précisez la source du facteur "
            "pour renforcer la comparaison."
        )
    for note in comparison.notes:
        caveats.append(note)
    caveats.append(
        "Cette recommandation est un outil d'aide à la décision fondé sur les hypothèses saisies ; "
        "elle ne remplace ni une validation comptable, ni une vérification technique."
    )

    method_note = (
        "Méthode : classement fondé sur les coûts totaux et les émissions cumulées calculés sur la période "
        "commune, avec la priorité choisie. "
    )
    if basis == "cout_etendu":
        method_note += (
            "Les émissions sont valorisées au prix interne du carbone défini : le classement utilise le coût "
            "étendu (coût total + émissions x prix interne)."
        )
    else:
        method_note += (
            "Aucun prix interne du carbone n'est appliqué : le critère coût repose uniquement sur les flux "
            "financiers saisis."
        )

    return ArbitrationResult(
        priority=priority,
        priority_label=priority_label,
        ranking=assessments,
        recommended_key=recommended.key,
        frontier=list(comparison.frontier),
        recommendation_title=title,
        recommendation_paragraphs=paragraphs,
        caveats=caveats,
        method_note=method_note,
        basis=basis,
    )
