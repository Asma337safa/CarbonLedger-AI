"""Passage des projets ORM au moteur de calcul (et inversement)."""

from __future__ import annotations

from typing import Any

from ..calc.decision import OptionInput, ScenarioParams
from ..errors import ValidationError
from ..models import DecisionProject
from .compute import ProjectAnalysis, analyze


def option_input_from_orm(option) -> OptionInput:
    return OptionInput.from_dict(
        {
            "name": option.name,
            "supplier": option.supplier,
            "purchase_cost": str(option.purchase_cost),
            "transport_cost": str(option.transport_cost),
            "annual_opex": str(option.annual_opex),
            "annual_energy_share_pct": str(option.annual_energy_share_pct)
            if option.annual_energy_share_pct is not None
            else None,
            "annual_maintenance": str(option.annual_maintenance),
            "annual_savings": str(option.annual_savings),
            "useful_life_years": str(option.useful_life_years) if option.useful_life_years is not None else None,
            "annual_emissions_kg": str(option.annual_emissions_kg) if option.annual_emissions_kg is not None else None,
            "emissions_basis": option.emissions_basis,
            "emissions_source_note": option.emissions_source_note,
            "confidence": option.confidence,
            "notes": option.notes,
        },
        key=f"o{option.id}",
    )


def project_inputs(project: DecisionProject) -> list[OptionInput]:
    return [option_input_from_orm(option) for option in project.options]


def analyze_project(
    project: DecisionProject,
    *,
    priority: str | None = None,
    with_scenarios: bool = True,
    with_sensitivity: bool = True,
    with_charts: bool = True,
    params: ScenarioParams | None = None,
) -> ProjectAnalysis:
    inputs = project_inputs(project)
    if len(inputs) < 2:
        raise ValidationError("Un projet doit comporter au moins deux options pour être comparé.")
    return analyze(
        inputs,
        project.horizon_years,
        priority=priority or project.priority,
        carbon_price=project.internal_carbon_price,
        discount_rate_pct=project.discount_rate_pct,
        params=params,
        with_scenarios=with_scenarios,
        with_sensitivity=with_sensitivity,
        with_charts=with_charts,
    )


def options_from_form(form_data: dict[str, Any], *, keep_keys: bool = True) -> list[OptionInput]:
    """Construit les options depuis un formulaire (listes ``option_name[]``…)."""
    names = form_data.get("option_name") or []
    if isinstance(names, str):
        names = [names]
    keys = form_data.get("option_key") or []
    if isinstance(keys, str):
        keys = [keys]
    options: list[OptionInput] = []
    for index, name in enumerate(names):
        data = {
            "name": name,
            "supplier": _pick(form_data, "option_supplier", index),
            "purchase_cost": _pick(form_data, "option_purchase_cost", index),
            "transport_cost": _pick(form_data, "option_transport_cost", index),
            "annual_opex": _pick(form_data, "option_annual_opex", index),
            "annual_energy_share_pct": _pick(form_data, "option_annual_energy_share_pct", index),
            "annual_maintenance": _pick(form_data, "option_annual_maintenance", index),
            "annual_savings": _pick(form_data, "option_annual_savings", index),
            "useful_life_years": _pick(form_data, "option_useful_life_years", index),
            "annual_emissions_kg": _pick(form_data, "option_annual_emissions_kg", index),
            "emissions_basis": _pick(form_data, "option_emissions_basis", index),
            "emissions_source_note": _pick(form_data, "option_emissions_source_note", index),
            "confidence": _pick(form_data, "option_confidence", index) or "moyenne",
            "notes": _pick(form_data, "option_notes", index),
        }
        key = _pick(form_data, "option_key", index) if keep_keys else None
        options.append(OptionInput.from_dict(data, key=str(key) if key else None, index=index))
    return options


def _pick(form_data: dict[str, Any], field: str, index: int):
    values = form_data.get(field)
    if values is None:
        return None
    if isinstance(values, (str, int, float)):
        return values if index == 0 else None
    try:
        return values[index]
    except (IndexError, TypeError):
        return None
