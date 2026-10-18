"""Analyse de sensibilité : quelles hypothèses influencent le plus le résultat ?

Chaque hypothèse est perturbée à la hausse et à la baisse autour du scénario
de base ; on mesure l'effet sur l'écart de coût et l'écart d'émissions entre
les deux options comparées. Le résultat est un classement explicite des
hypothèses les plus influentes (graphique « tornade » dans l'interface).
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
from .formatting import fmt_money, fmt_number, fmt_tco2e

DEFAULT_PERTURBATION_PCT = Decimal("10")


@dataclass
class SensitivityItem:
    driver: str
    label: str
    low_case: str
    high_case: str
    base_cost_delta: Decimal
    cost_delta_low: Decimal
    cost_delta_high: Decimal
    base_emissions_delta: Decimal | None
    emissions_delta_low: Decimal | None
    emissions_delta_high: Decimal | None
    cost_swing: Decimal
    emissions_swing: Decimal | None
    can_flip_ranking: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "label": self.label,
            "low_case": self.low_case,
            "high_case": self.high_case,
            "base_cost_delta": str(_money(self.base_cost_delta)),
            "cost_delta_low": str(_money(self.cost_delta_low)),
            "cost_delta_high": str(_money(self.cost_delta_high)),
            "base_emissions_delta": str(self.base_emissions_delta) if self.base_emissions_delta is not None else None,
            "emissions_delta_low": str(self.emissions_delta_low) if self.emissions_delta_low is not None else None,
            "emissions_delta_high": str(self.emissions_delta_high) if self.emissions_delta_high is not None else None,
            "cost_swing": str(self.cost_swing),
            "emissions_swing": str(self.emissions_swing) if self.emissions_swing is not None else None,
            "can_flip_ranking": self.can_flip_ranking,
            "note": self.note,
        }


def _pair_deltas(
    options: list[OptionInput],
    horizon: int,
    params: ScenarioParams,
    carbon_price,
) -> tuple[Decimal, Decimal | None, str, str]:
    """Écarts (coût, émissions) entre les deux premières options, et clés (moins cher, moins émetteur)."""
    comparison = compare_options(options, horizon, params, carbon_price)
    pair = comparison.pairs[0]
    return pair.cost_delta, pair.emissions_delta_t, pair.cheaper_key or "", pair.cleaner_key or ""


def sensitivity_analysis(
    options: list[OptionInput],
    horizon_years: Any,
    base_params: ScenarioParams | None = None,
    perturbation_pct: Decimal | float | str = DEFAULT_PERTURBATION_PCT,
    carbon_price=ZERO,
) -> list[SensitivityItem]:
    """Classement des hypothèses par influence décroissante sur la comparaison."""
    if len(options) < 2:
        return []
    horizon = validate_horizon(horizon_years)
    base_params = base_params or ScenarioParams()
    pct = Decimal(str(perturbation_pct))
    if pct <= 0:
        pct = DEFAULT_PERTURBATION_PCT

    base_cost, base_em, base_cheaper, base_cleaner = _pair_deltas(options, horizon, base_params, carbon_price)

    drivers = [
        ("energy_price_delta_pct", "Prix de l'énergie", f"−{pct} %", f"+{pct} %"),
        ("transport_delta_pct", "Coûts de transport", f"−{pct} %", f"+{pct} %"),
        ("savings_delta_pct", "Économies attendues", f"−{pct} %", f"+{pct} %"),
        ("activity_volume_delta_pct", "Volume d'activité", f"−{pct} %", f"+{pct} %"),
        ("emission_factor_delta_pct", "Facteurs d'émission", f"−{pct} %", f"+{pct} %"),
        ("lifetime_delta_years", "Durée d'utilisation", "−1 an", "+1 an"),
    ]

    items: list[SensitivityItem] = []
    for driver, label, low_label, high_label in drivers:
        low_params = ScenarioParams(**{**base_params.__dict__})
        high_params = ScenarioParams(**{**base_params.__dict__})
        if driver == "lifetime_delta_years":
            low_params.lifetime_delta_years = base_params.lifetime_delta_years - Decimal("1")
            high_params.lifetime_delta_years = base_params.lifetime_delta_years + Decimal("1")
        else:
            low_value = getattr(base_params, driver) - pct
            high_value = getattr(base_params, driver) + pct
            setattr(low_params, driver, low_value)
            setattr(high_params, driver, high_value)

        low_cost, low_em, low_cheaper, _ = _pair_deltas(options, horizon, low_params, carbon_price)
        high_cost, high_em, high_cheaper, _ = _pair_deltas(options, horizon, high_params, carbon_price)

        cost_swing = abs(max(base_cost, low_cost, high_cost) - min(base_cost, low_cost, high_cost))
        emissions_swing = None
        if base_em is not None and low_em is not None and high_em is not None:
            emissions_swing = abs(max(base_em, low_em, high_em) - min(base_em, low_em, high_em))

        flip = bool(base_cheaper) and ({low_cheaper, high_cheaper} - {base_cheaper}) != set()

        note = ""
        if driver == "emission_factor_delta_pct" and all(o.annual_emissions_kg is None for o in options):
            note = "Sans données d'émissions, cette hypothèse n'a aucun effet."
        if driver == "energy_price_delta_pct" and all(o.annual_energy_share_pct is None for o in options):
            note = (
                "Aucune option ne précise la part d'énergie dans ses coûts de fonctionnement : "
                "renseignez-la pour activer cette hypothèse."
            )

        items.append(
            SensitivityItem(
                driver=driver,
                label=label,
                low_case=low_label,
                high_case=high_label,
                base_cost_delta=base_cost,
                cost_delta_low=low_cost,
                cost_delta_high=high_cost,
                base_emissions_delta=base_em,
                emissions_delta_low=low_em,
                emissions_delta_high=high_em,
                cost_swing=cost_swing,
                emissions_swing=emissions_swing,
                can_flip_ranking=flip,
                note=note,
            )
        )

    items.sort(key=lambda item: (item.cost_swing, item.emissions_swing or ZERO), reverse=True)
    return items


def sensitivity_summary(items: list[SensitivityItem], horizon_years: int, limit: int = 3) -> list[str]:
    """Phrases de synthèse sur les hypothèses déterminantes (sans invention)."""
    lines: list[str] = []
    for item in items[:limit]:
        if item.note and item.cost_swing == ZERO:
            lines.append(f"{item.label} : {item.note}")
            continue
        line = (
            f"{item.label} : une variation de {item.low_case} à {item.high_case} fait varier l'écart de coût "
            f"entre les deux options de {fmt_money(item.cost_swing)}"
        )
        if item.emissions_swing:
            line += f" et l'écart d'émissions de {fmt_number(item.emissions_swing, 2)} t CO₂e"
        line += "."
        if item.can_flip_ranking:
            line += " Cette hypothèse peut inverser le classement des options."
        lines.append(line)
    return lines
