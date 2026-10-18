"""Simulations : scénarios prédéfinis et personnalisés.

Les scénarios sont des hypothèses de travail explicitement affichées
(optimiste / défavorable), jamais des prévisions. Chaque paramètre agit sur
une grandeur identifiée du moteur de calcul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .decision import (
    ComparisonResult,
    OptionInput,
    ScenarioParams,
    ZERO,
    _money,
    compare_options,
    validate_horizon,
)
from .formatting import fmt_money, fmt_number

# Scénarios pédagogiques par défaut, affichés à l'utilisateur avant application.
PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "base": {
        "label": "Scénario de base",
        "description": "Hypothèses saisies, sans modification.",
        "parameters": {},
    },
    "optimiste": {
        "label": "Scénario optimiste",
        "description": (
            "Énergie −10 %, transport −10 %, économies attendues +10 %, facteurs d'émission −5 %. "
            "Hypothèses favorables destinées à tester la robustesse de la décision."
        ),
        "parameters": {
            "energy_price_delta_pct": -10,
            "transport_delta_pct": -10,
            "savings_delta_pct": 10,
            "emission_factor_delta_pct": -5,
        },
    },
    "defavorable": {
        "label": "Scénario défavorable",
        "description": (
            "Énergie +15 %, transport +15 %, économies attendues −20 %, facteurs d'émission +10 %. "
            "Hypothèses prudentes : hausses de coûts et performance carbone dégradée."
        ),
        "parameters": {
            "energy_price_delta_pct": 15,
            "transport_delta_pct": 15,
            "savings_delta_pct": -20,
            "emission_factor_delta_pct": 10,
        },
    },
}


def preset_params(kind: str) -> ScenarioParams:
    """Paramètres d'un scénario prédéfini (``base``, ``optimiste``, ``defavorable``)."""
    definition = PRESET_DEFINITIONS.get(kind)
    if definition is None:
        return ScenarioParams(label="Scénario personnalisé")
    params = ScenarioParams.from_dict({**definition["parameters"], "label": definition["label"]})
    return params


@dataclass
class ScenarioOutcome:
    kind: str
    label: str
    description: str
    params: ScenarioParams
    comparison: ComparisonResult
    cost_deltas: dict[str, Decimal] = field(default_factory=dict)      # par option, vs scénario de base
    emissions_deltas: dict[str, Decimal | None] = field(default_factory=dict)
    cash_deltas: dict[str, Decimal] = field(default_factory=dict)      # trésorerie année 1, vs base
    summary_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "params": self.params.to_dict(),
            "params_description": self.params.description(),
            "comparison": self.comparison.to_dict(),
            "cost_deltas": {k: str(_money(v)) for k, v in self.cost_deltas.items()},
            "emissions_deltas": {
                k: (str(v) if v is not None else None) for k, v in self.emissions_deltas.items()
            },
            "cash_deltas": {k: str(_money(v)) for k, v in self.cash_deltas.items()},
            "summary_lines": self.summary_lines,
        }


def _scenario_summary(base: ComparisonResult, outcome: ComparisonResult, horizon: int) -> list[str]:
    """Phrases factuelles décrivant l'effet du scénario (aucune prévision)."""
    lines: list[str] = []
    for result in outcome.results:
        base_result = base.by_key.get(result.key)
        if base_result is None:
            continue
        delta_cost = result.total_cost - base_result.total_cost
        if delta_cost:
            direction = "augmente" if delta_cost > 0 else "baisse"
            lines.append(
                f"« {result.name} » : le coût total sur {horizon} ans {direction} de "
                f"{fmt_money(abs(delta_cost))} ({fmt_money(result.total_cost)} contre {fmt_money(base_result.total_cost)})."
            )
        if result.total_emissions_t is not None and base_result.total_emissions_t is not None:
            delta_em = result.total_emissions_t - base_result.total_emissions_t
            if delta_em:
                direction = "augmentent" if delta_em > 0 else "baissent"
                lines.append(
                    f"« {result.name} » : les émissions cumulées {direction} de {fmt_number(abs(delta_em), 2)} t CO₂e."
                )
    base_cheapest = base.cheapest_key
    if outcome.cheapest_key and base_cheapest and outcome.cheapest_key != base_cheapest:
        lines.append(
            "Dans ce scénario, l'option la moins chère devient « "
            + outcome.by_key[outcome.cheapest_key].name
            + " » : la conclusion change, à examiner avec attention."
        )
    elif outcome.cheapest_key and base_cheapest:
        lines.append(
            "Dans ce scénario, l'option la moins chère reste « "
            + outcome.by_key[outcome.cheapest_key].name
            + " » : la conclusion financière est stable."
        )
    return lines


def run_scenarios(
    options: list[OptionInput],
    horizon_years: Any,
    carbon_price=ZERO,
    custom: list[dict[str, Any]] | None = None,
) -> list[ScenarioOutcome]:
    """Exécute le scénario de base, les scénarios prédéfinis et les scénarios personnalisés."""
    horizon = validate_horizon(horizon_years)

    base_params = preset_params("base")
    base = compare_options(options, horizon, base_params, carbon_price)

    outcomes: list[ScenarioOutcome] = []
    kinds = ["base", "optimiste", "defavorable"]
    for kind in kinds:
        definition = PRESET_DEFINITIONS[kind]
        params = preset_params(kind)
        comparison = base if kind == "base" else compare_options(options, horizon, params, carbon_price)
        outcome = ScenarioOutcome(
            kind=kind,
            label=definition["label"],
            description=definition["description"],
            params=params,
            comparison=comparison,
        )
        if kind != "base":
            outcome.summary_lines = _scenario_summary(base, comparison, horizon)
        else:
            outcome.summary_lines = [
                "Le scénario de base reprend vos hypothèses telles que saisies (aucune modification)."
            ]
        for result in comparison.results:
            base_result = base.by_key.get(result.key)
            if base_result is None:
                continue
            outcome.cost_deltas[result.key] = result.total_cost - base_result.total_cost
            if result.total_emissions_t is not None and base_result.total_emissions_t is not None:
                outcome.emissions_deltas[result.key] = result.total_emissions_t - base_result.total_emissions_t
            else:
                outcome.emissions_deltas[result.key] = None
            outcome.cash_deltas[result.key] = result.cash_curve[1] - base_result.cash_curve[1] if len(result.cash_curve) > 1 and len(base_result.cash_curve) > 1 else ZERO
        outcomes.append(outcome)

    for index, entry in enumerate(custom or [], start=1):
        params = ScenarioParams.from_dict({**entry, "label": entry.get("label") or f"Scénario personnalisé {index}"})
        comparison = compare_options(options, horizon, params, carbon_price)
        outcome = ScenarioOutcome(
            kind="personnalise",
            label=params.label,
            description="Scénario personnalisé : " + params.description() + ".",
            params=params,
            comparison=comparison,
            summary_lines=_scenario_summary(base, comparison, horizon),
        )
        for result in comparison.results:
            base_result = base.by_key.get(result.key)
            if base_result is None:
                continue
            outcome.cost_deltas[result.key] = result.total_cost - base_result.total_cost
            outcome.emissions_deltas[result.key] = (
                (result.total_emissions_t - base_result.total_emissions_t)
                if result.total_emissions_t is not None and base_result.total_emissions_t is not None
                else None
            )
            outcome.cash_deltas[result.key] = (
                result.cash_curve[1] - base_result.cash_curve[1]
                if len(result.cash_curve) > 1 and len(base_result.cash_curve) > 1
                else ZERO
            )
        outcomes.append(outcome)

    return outcomes
