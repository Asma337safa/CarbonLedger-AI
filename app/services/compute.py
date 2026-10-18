"""Orchestration : options saisies -> comparaison, arbitrage, sensibilité,
scénarios et graphiques, dans un format unique réutilisé par l'interface,
l'API JSON, les rapports PDF et le Copilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..calc.arbitration import ArbitrationResult, arbitrate
from ..calc.decision import (
    COST_PER_TONNE_FORMULA,
    ComparisonResult,
    OptionInput,
    ScenarioParams,
    ZERO,
    compare_options,
)
from ..calc.formatting import fmt_money, fmt_number, fmt_tco2e, to_decimal
from ..calc.scenarios import PRESET_DEFINITIONS, ScenarioOutcome, run_scenarios
from ..calc.sensitivity import SensitivityItem, sensitivity_analysis, sensitivity_summary
from . import charts


@dataclass
class ProjectAnalysis:
    comparison: ComparisonResult
    arbitration: ArbitrationResult
    sensitivity: list[SensitivityItem] = field(default_factory=list)
    sensitivity_lines: list[str] = field(default_factory=list)
    scenarios: list[ScenarioOutcome] = field(default_factory=list)
    charts: dict[str, str] = field(default_factory=dict)
    missing_data: list[dict[str, str]] = field(default_factory=list)
    formula: str = COST_PER_TONNE_FORMULA
    params: ScenarioParams = field(default_factory=ScenarioParams)

    @property
    def horizon_years(self) -> int:
        return self.comparison.horizon_years

    @property
    def carbon_price(self) -> Decimal:
        return self.comparison.carbon_price


def _key_pair(comparison: ComparisonResult) -> tuple[str, str] | None:
    """Paire la plus significative pour le coût par tonne évitée.

    Priorité : (moins cher) vs (moins émetteur) s'ils diffèrent, sinon les
    deux premières options.
    """
    if comparison.cheapest_key and comparison.greenest_key and comparison.cheapest_key != comparison.greenest_key:
        return comparison.cheapest_key, comparison.greenest_key
    keys = [r.key for r in comparison.results]
    if len(keys) >= 2:
        return keys[0], keys[1]
    return None


def key_figures(analysis: ProjectAnalysis) -> dict[str, Any]:
    """Chiffres clés affichés dans l'interface et les rapports."""
    comparison = analysis.comparison
    cheapest = comparison.cheapest
    greenest = comparison.greenest
    figures: dict[str, Any] = {
        "horizon_years": comparison.horizon_years,
        "options_count": len(comparison.results),
        "cheapest_name": cheapest.name if cheapest else None,
        "cheapest_cost": str(cheapest.total_cost) if cheapest else None,
        "greenest_name": greenest.name if greenest else None,
        "greenest_emissions_t": str(greenest.total_emissions_t) if greenest and greenest.total_emissions_t is not None else None,
        "best_treasury_name": (comparison.by_key[comparison.best_treasury_key].name if comparison.best_treasury_key else None),
        "cost_per_tonne_avoided": None,
        "avoided_t": None,
        "double_gain": None,
        "cost_premium": None,
        "pair": None,
        "break_even_years": None,
    }
    pair_keys = _key_pair(comparison)
    if pair_keys:
        pair = next(
            (p for p in comparison.pairs if {p.a_key, p.b_key} == set(pair_keys)),
            None,
        )
        if pair:
            figures["pair"] = {"a": pair.a_name, "b": pair.b_name}
            figures["avoided_t"] = str(pair.avoided_t) if pair.avoided_t is not None else None
            figures["cost_per_tonne_avoided"] = str(pair.cost_per_tonne_avoided) if pair.cost_per_tonne_avoided is not None else None
            figures["double_gain"] = pair.double_gain
            figures["cost_premium"] = str(pair.cost_delta)
            if pair.break_even:
                figures["break_even_years"] = pair.break_even.get("years")
    return figures


def missing_data_checks(
    comparison: ComparisonResult, options_input: list[OptionInput]
) -> list[dict[str, str]]:
    """Liste explicite des données manquantes ou fragiles (aucune invention)."""
    checks: list[dict[str, str]] = []
    for result in comparison.results:
        if result.total_emissions_t is None:
            checks.append(
                {
                    "level": "attention",
                    "message": (
                        f"Émissions non renseignées pour « {result.name} » : écart carbone et coût par tonne "
                        "évitée indisponibles pour cette option."
                    ),
                    "hint": "Renseignez les émissions annuelles (mesurées, calculées ou estimées) dans l'option.",
                }
            )
        if result.option.annual_energy_share_pct is None and result.option.annual_opex > 0:
            checks.append(
                {
                    "level": "info",
                    "message": (
                        f"« {result.name} » : la part d'énergie dans les coûts de fonctionnement n'est pas "
                        "renseignée."
                    ),
                    "hint": "Le scénario « hausse du prix de l'énergie » ne s'appliquera pas à cette option.",
                }
            )
        if result.option.confidence == "faible":
            checks.append(
                {
                    "level": "attention",
                    "message": f"« {result.name} » : niveau de confiance des données déclaré faible.",
                    "hint": "Documentez la source des coûts et des émissions avant de décider.",
                }
            )
        if result.option.emissions_basis == "estime":
            checks.append(
                {
                    "level": "info",
                    "message": f"« {result.name} » : les émissions sont déclarées comme estimées (non mesurées).",
                    "hint": "Précisez le facteur d'émission utilisé et sa source pour renforcer la comparaison.",
                }
            )
        for warning in result.warnings:
            if "durée" in warning or "remplacement" in warning:
                checks.append({"level": "attention", "message": warning, "hint": "Vérifiez l'horizon de comparaison."})
    if comparison.carbon_price == ZERO:
        checks.append(
            {
                "level": "info",
                "message": "Aucun prix interne du carbone n'est appliqué dans cette comparaison.",
                "hint": "Définissez un prix interne (DH/tCO₂e) pour intégrer les émissions dans le classement économique.",
            }
        )
    return checks


def analyze(
    options: list[OptionInput],
    horizon_years: Any,
    *,
    priority: str = "equilibre",
    carbon_price: Decimal | float | str | None = ZERO,
    discount_rate_pct: Decimal | float | str | None = ZERO,
    params: ScenarioParams | None = None,
    custom_scenarios: list[dict[str, Any]] | None = None,
    with_scenarios: bool = True,
    with_sensitivity: bool = True,
    with_charts: bool = True,
) -> ProjectAnalysis:
    """Analyse complète d'un projet de décision."""
    base_params = params or ScenarioParams()
    if discount_rate_pct and to_decimal(discount_rate_pct):
        base_params = ScenarioParams(
            label=base_params.label,
            energy_price_delta_pct=base_params.energy_price_delta_pct,
            transport_delta_pct=base_params.transport_delta_pct,
            savings_delta_pct=base_params.savings_delta_pct,
            activity_volume_delta_pct=base_params.activity_volume_delta_pct,
            emission_factor_delta_pct=base_params.emission_factor_delta_pct,
            lifetime_delta_years=base_params.lifetime_delta_years,
            discount_rate_pct=to_decimal(discount_rate_pct) or ZERO,
        )
    comparison = compare_options(options, horizon_years, base_params, carbon_price)
    arbitration = arbitrate(comparison, priority)
    sensitivity_items: list[SensitivityItem] = []
    if with_sensitivity:
        sensitivity_items = sensitivity_analysis(options, horizon_years, base_params, carbon_price=carbon_price)
    analysis = ProjectAnalysis(
        comparison=comparison,
        arbitration=arbitration,
        sensitivity=sensitivity_items,
        sensitivity_lines=sensitivity_summary(sensitivity_items, comparison.horizon_years),
        scenarios=run_scenarios(options, horizon_years, carbon_price, custom_scenarios) if with_scenarios else [],
        missing_data=missing_data_checks(comparison, options),
        params=base_params,
    )
    if with_charts:
        analysis.charts = render_charts(analysis)
    return analysis


def render_charts(analysis: ProjectAnalysis) -> dict[str, str]:
    """Graphiques SVG du comparateur (coûts cumulés, émissions cumulées, totaux, tornade)."""
    comparison = analysis.comparison
    results = comparison.results
    names = [r.name for r in results]
    horizon = comparison.horizon_years
    year_labels = [f"Année {index}" for index in range(horizon + 1)]

    cost_series = [
        (r.name, charts.PALETTE[index % len(charts.PALETTE)], [float(v) for v in r.cost_curve])
        for index, r in enumerate(results)
    ]
    emissions_known = [r for r in results if r.emissions_curve_t is not None]
    emissions_series = [
        (r.name, charts.PALETTE[index % len(charts.PALETTE)], [float(v) for v in r.emissions_curve_t or []])
        for index, r in enumerate(emissions_known)
    ]

    totals_series = [
        ("Mise de fonds initiale", "#172B4D", [float(r.initial_outlay) for r in results]),
        (f"Coût total sur {horizon} ans", "#176B4D", [float(r.total_cost) for r in results]),
    ]
    emissions_totals_series = [
        (
            f"Émissions cumulées (t CO₂e)",
            "#172B4D",
            [float(r.total_emissions_t) for r in emissions_known],
        )
    ] if emissions_known else []

    tornado_items = [
        (
            item.label,
            float(item.cost_delta_low - item.base_cost_delta),
            float(item.cost_delta_high - item.base_cost_delta),
        )
        for item in analysis.sensitivity
        if item.cost_swing > 0
    ]

    return {
        "cost_curve": charts.multi_line_chart(
            year_labels,
            cost_series,
            value_fmt=lambda v: fmt_money(v, decimals=0),
            axis_fmt=lambda v: charts.compact_number(v) + " DH",
            aria_label="Coûts cumulés par option et par année",
        ),
        "emissions_curve": charts.multi_line_chart(
            year_labels,
            emissions_series,
            value_fmt=lambda v: fmt_tco2e(v),
            axis_fmt=lambda v: charts.compact_number(v) + " t",
            aria_label="Émissions cumulées par option et par année",
        ) if emissions_series else "",
        "cost_totals": charts.grouped_bar_chart(
            names,
            totals_series,
            value_fmt=lambda v: fmt_money(v, decimals=0),
            axis_fmt=lambda v: charts.compact_number(v) + " DH",
            aria_label="Coût total et mise de fonds initiale par option",
        ),
        "emissions_totals": charts.grouped_bar_chart(
            [r.name for r in emissions_known],
            emissions_totals_series,
            value_fmt=lambda v: fmt_tco2e(v),
            axis_fmt=lambda v: charts.compact_number(v) + " t",
            aria_label="Émissions cumulées par option",
        ) if emissions_totals_series else "",
        "tornado": charts.tornado_chart(tornado_items, value_fmt=lambda v: fmt_money(v, decimals=0)),
    }


def analysis_to_dict(analysis: ProjectAnalysis) -> dict[str, Any]:
    """Sérialisation complète (API JSON, recalcul en direct)."""
    return {
        "comparison": analysis.comparison.to_dict(),
        "arbitration": analysis.arbitration.to_dict(),
        "sensitivity": [item.to_dict() for item in analysis.sensitivity],
        "sensitivity_lines": analysis.sensitivity_lines,
        "scenarios": [outcome.to_dict() for outcome in analysis.scenarios],
        "charts": analysis.charts,
        "key_figures": key_figures(analysis),
        "missing_data": analysis.missing_data,
        "formula": analysis.formula,
        "presets": {
            kind: {"label": definition["label"], "description": definition["description"]}
            for kind, definition in PRESET_DEFINITIONS.items()
        },
    }
