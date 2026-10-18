"""Calcul des émissions : formule générale et agrégations du registre carbone.

Formule générale : **Émissions (kg CO₂e) = quantité d'activité x facteur d'émission**.

La distinction entre mesures, calculs documentés et estimations est
préservée dans toute la chaîne, y compris pour les estimations monétaires
(approximatives par nature).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from ..calc.formatting import to_decimal

KG_Q = Decimal("0.001")


def _attr(record: Any, name: str, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def compute_emissions_kg(quantity, kgco2e_per_unit) -> Decimal:
    """Émissions = quantité d'activité x facteur d'émission (arrondi 3 décimales)."""
    q = to_decimal(quantity)
    f = to_decimal(kgco2e_per_unit)
    if q is None or f is None:
        raise ValueError("La quantité d'activité et le facteur d'émission sont obligatoires.")
    if q < 0 or f < 0:
        raise ValueError("La quantité d'activité et le facteur d'émission doivent être positifs.")
    return (q * f).quantize(KG_Q, ROUND_HALF_UP)


def to_tonnes(kg) -> Decimal:
    value = to_decimal(kg)
    if value is None:
        return Decimal("0")
    return (value / 1000).quantize(KG_Q, ROUND_HALF_UP)


def status_from_method(method: str | None) -> str:
    """Statut de donnée déduit de la méthode du facteur d'émission."""
    if method in {"mesure", "calcule", "estime"}:
        return method
    if method == "monetaire":
        return "estime"
    return "calcule"


@dataclass
class EmissionSummary:
    """Synthèse du registre carbone d'une période."""

    total_kg: Decimal = Decimal("0")
    measured_kg: Decimal = Decimal("0")
    calculated_kg: Decimal = Decimal("0")
    estimated_kg: Decimal = Decimal("0")
    monetary_kg: Decimal = Decimal("0")
    record_count: int = 0
    measured_count: int = 0
    estimated_count: int = 0
    by_category: dict[str, Decimal] = field(default_factory=dict)
    by_scope: dict[str, Decimal] = field(default_factory=dict)

    @property
    def total_t(self) -> Decimal:
        return to_tonnes(self.total_kg)

    @property
    def estimated_share_pct(self) -> Decimal:
        """Part des émissions estimées (y compris monétaires) dans le total."""
        if self.total_kg <= 0:
            return Decimal("0")
        return ((self.estimated_kg / self.total_kg) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)

    @property
    def monetary_share_pct(self) -> Decimal:
        if self.total_kg <= 0:
            return Decimal("0")
        return ((self.monetary_kg / self.total_kg) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)


def summarize_records(records: Iterable[Any]) -> EmissionSummary:
    """Agrège des enregistrements carbone (objets ORM ou dictionnaires)."""
    summary = EmissionSummary()
    for record in records:
        kg = to_decimal(_attr(record, "kgco2e", 0)) or Decimal("0")
        status = (_attr(record, "status", "calcule") or "calcule").lower()
        method = (_attr(record, "method", "") or "").lower()
        category = _attr(record, "category", "autres") or "autres"
        factor = _attr(record, "emission_factor", None)
        scope = str(getattr(factor, "scope", "") or _attr(record, "scope", "") or "")

        summary.total_kg += kg
        summary.record_count += 1
        summary.by_category[category] = summary.by_category.get(category, Decimal("0")) + kg
        if scope:
            summary.by_scope[scope] = summary.by_scope.get(scope, Decimal("0")) + kg

        if status == "mesure":
            summary.measured_kg += kg
            summary.measured_count += 1
        elif status == "estime":
            summary.estimated_kg += kg
            summary.estimated_count += 1
            if method == "monetaire":
                summary.monetary_kg += kg
        else:
            summary.calculated_kg += kg

    summary.total_kg = summary.total_kg.quantize(KG_Q, ROUND_HALF_UP)
    return summary
