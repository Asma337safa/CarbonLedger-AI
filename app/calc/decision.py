"""Moteur de comparaison de décisions (coûts, trésorerie, émissions).

Règles de calcul (explicites et vérifiables) :

- Les options sont comparées sur une **période commune** (``horizon_years``).
- Le coût total d'une option = coût d'acquisition + coûts de transport +
  somme des coûts de fonctionnement, de maintenance et des économies
  attendues sur la période.
- Les émissions cumulées = émissions annuelles x nombre d'années, converties
  en tonnes de CO₂e (1 t = 1 000 kg).
- Le coût par tonne de CO₂e évitée entre deux options :
  ``(coût de l'option la moins émettrice - coût de l'option la plus émettrice)
  / (émissions de la plus émettrice - émissions de la moins émettrice)``.
  Un résultat négatif signifie que l'option la moins émettrice est aussi la
  moins chère (gain double) — il ne s'agit pas d'une économie générée par le
  carbone mais d'un indicateur de compromis.
- L'actualisation est optionnelle (taux explicite) et affichée séparément.
- Une durée de vie inférieure à l'horizon est signalée : aucun
  réinvestissement n'est chiffré automatiquement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..errors import ValidationError
from .formatting import fmt_money, fmt_number, fmt_tco2e, to_decimal

ZERO = Decimal("0")
MONEY_Q = Decimal("0.01")
EMIS_Q = Decimal("0.001")
HORIZON_MIN = 1
HORIZON_MAX = 30


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, ROUND_HALF_UP)


def _emissions_t(value: Decimal) -> Decimal:
    return value.quantize(EMIS_Q, ROUND_HALF_UP)


def _d(value, default: Decimal = ZERO) -> Decimal:
    result = to_decimal(value)
    return default if result is None else result


# ---------------------------------------------------------------------------
# Entrées
# ---------------------------------------------------------------------------
@dataclass
class ScenarioParams:
    """Hypothèses modifiables d'un scénario (en % sauf mention contraire)."""

    label: str = "Scénario de base"
    energy_price_delta_pct: Decimal = ZERO
    transport_delta_pct: Decimal = ZERO
    savings_delta_pct: Decimal = ZERO
    activity_volume_delta_pct: Decimal = ZERO
    emission_factor_delta_pct: Decimal = ZERO
    lifetime_delta_years: Decimal = ZERO
    discount_rate_pct: Decimal = ZERO

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ScenarioParams":
        data = data or {}
        return cls(
            label=str(data.get("label") or "Scénario personnalisé"),
            energy_price_delta_pct=_d(data.get("energy_price_delta_pct") or data.get("energy_price_pct")),
            transport_delta_pct=_d(data.get("transport_delta_pct") or data.get("transport_pct")),
            savings_delta_pct=_d(data.get("savings_delta_pct") or data.get("savings_pct")),
            activity_volume_delta_pct=_d(data.get("activity_volume_delta_pct") or data.get("activity_pct")),
            emission_factor_delta_pct=_d(data.get("emission_factor_delta_pct") or data.get("emission_factor_pct")),
            lifetime_delta_years=_d(data.get("lifetime_delta_years")),
            discount_rate_pct=_d(data.get("discount_rate_pct")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "energy_price_delta_pct": float(self.energy_price_delta_pct),
            "transport_delta_pct": float(self.transport_delta_pct),
            "savings_delta_pct": float(self.savings_delta_pct),
            "activity_volume_delta_pct": float(self.activity_volume_delta_pct),
            "emission_factor_delta_pct": float(self.emission_factor_delta_pct),
            "lifetime_delta_years": float(self.lifetime_delta_years),
            "discount_rate_pct": float(self.discount_rate_pct),
        }

    @property
    def is_base(self) -> bool:
        return all(
            value == ZERO
            for value in (
                self.energy_price_delta_pct,
                self.transport_delta_pct,
                self.savings_delta_pct,
                self.activity_volume_delta_pct,
                self.emission_factor_delta_pct,
                self.lifetime_delta_years,
            )
        )

    def description(self) -> str:
        """Description lisible des écarts par rapport au scénario de base."""
        parts: list[str] = []
        if self.energy_price_delta_pct:
            parts.append(f"prix de l'énergie {self.energy_price_delta_pct:+} %")
        if self.transport_delta_pct:
            parts.append(f"coûts de transport {self.transport_delta_pct:+} %")
        if self.savings_delta_pct:
            parts.append(f"économies attendues {self.savings_delta_pct:+} %")
        if self.activity_volume_delta_pct:
            parts.append(f"volume d'activité {self.activity_volume_delta_pct:+} %")
        if self.emission_factor_delta_pct:
            parts.append(f"facteurs d'émission {self.emission_factor_delta_pct:+} %")
        if self.lifetime_delta_years:
            parts.append(f"durée d'utilisation {self.lifetime_delta_years:+} an(s)")
        if self.discount_rate_pct:
            parts.append(f"actualisation {self.discount_rate_pct} %/an")
        return ", ".join(parts) if parts else "hypothèses de base (inchangées)"


@dataclass
class OptionInput:
    """Une option à comparer (saisie utilisateur)."""

    key: str
    name: str
    supplier: str = ""
    purchase_cost: Decimal = ZERO
    transport_cost: Decimal = ZERO
    annual_opex: Decimal = ZERO
    annual_energy_share_pct: Decimal | None = None
    annual_maintenance: Decimal = ZERO
    annual_savings: Decimal = ZERO
    useful_life_years: Decimal | None = None
    annual_emissions_kg: Decimal | None = None
    emissions_basis: str | None = None
    emissions_source_note: str = ""
    confidence: str = "moyenne"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], key: str | None = None, index: int = 0) -> "OptionInput":
        key = key or str(data.get("key") or f"option_{index + 1}")
        name = str(data.get("name") or "").strip() or f"Option {index + 1}"
        energy_share_raw = data.get("annual_energy_share_pct")
        energy_share = to_decimal(energy_share_raw) if energy_share_raw not in (None, "") else None
        emissions_raw = data.get("annual_emissions_kg")
        emissions = to_decimal(emissions_raw) if emissions_raw not in (None, "") else None

        option = cls(
            key=key,
            name=name,
            supplier=str(data.get("supplier") or "").strip(),
            purchase_cost=_d(data.get("purchase_cost")),
            transport_cost=_d(data.get("transport_cost")),
            annual_opex=_d(data.get("annual_opex")),
            annual_energy_share_pct=energy_share,
            annual_maintenance=_d(data.get("annual_maintenance")),
            annual_savings=_d(data.get("annual_savings")),
            useful_life_years=to_decimal(data.get("useful_life_years")) if data.get("useful_life_years") not in (None, "") else None,
            annual_emissions_kg=emissions,
            emissions_basis=(str(data["emissions_basis"]) if data.get("emissions_basis") else None),
            emissions_source_note=str(data.get("emissions_source_note") or "").strip(),
            confidence=str(data.get("confidence") or "moyenne"),
            notes=str(data.get("notes") or "").strip(),
        )
        option.validate(index)
        return option

    def validate(self, index: int = 0) -> None:
        errors: dict[str, str] = {}
        prefix = f"options[{index}]"
        for fieldname, value in (
            ("purchase_cost", self.purchase_cost),
            ("transport_cost", self.transport_cost),
            ("annual_opex", self.annual_opex),
            ("annual_maintenance", self.annual_maintenance),
            ("annual_savings", self.annual_savings),
        ):
            if value < 0:
                errors[f"{prefix}.{fieldname}"] = "Le montant ne peut pas être négatif."
        if self.annual_energy_share_pct is not None and not (ZERO <= self.annual_energy_share_pct <= 100):
            errors[f"{prefix}.annual_energy_share_pct"] = "La part d'énergie doit être comprise entre 0 et 100 %."
        if self.annual_emissions_kg is not None and self.annual_emissions_kg < 0:
            errors[f"{prefix}.annual_emissions_kg"] = "Les émissions ne peuvent pas être négatives."
        if self.useful_life_years is not None and self.useful_life_years <= 0:
            errors[f"{prefix}.useful_life_years"] = "La durée d'utilisation doit être supérieure à zéro."
        if self.confidence not in {"haute", "moyenne", "faible"}:
            errors[f"{prefix}.confidence"] = "Niveau de confiance inconnu."
        if errors:
            raise ValidationError("Certaines options contiennent des valeurs invalides.", fields=errors)


def validate_horizon(value: Any) -> int:
    years = int(_d(value, Decimal("5")))
    if years < HORIZON_MIN or years > HORIZON_MAX:
        raise ValidationError(f"La période de comparaison doit être comprise entre {HORIZON_MIN} et {HORIZON_MAX} ans.")
    return years


# ---------------------------------------------------------------------------
# Sorties
# ---------------------------------------------------------------------------
@dataclass
class OptionResult:
    """Résultat chiffré d'une option sur l'horizon commun."""

    option: OptionInput
    horizon_years: int
    initial_outlay: Decimal
    purchase_cost: Decimal
    transport_cost: Decimal
    annual_opex: Decimal
    annual_maintenance: Decimal
    annual_savings: Decimal
    annual_net_costs: list[Decimal] = field(default_factory=list)
    cost_curve: list[Decimal] = field(default_factory=list)
    cash_curve: list[Decimal] = field(default_factory=list)
    total_cost: Decimal = ZERO
    total_savings: Decimal = ZERO
    total_opex: Decimal = ZERO
    total_maintenance: Decimal = ZERO
    npv: Decimal | None = None
    annual_emissions_t: Decimal | None = None
    emissions_curve_t: list[Decimal] | None = None
    total_emissions_t: Decimal | None = None
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.option.key

    @property
    def name(self) -> str:
        return self.option.name

    @property
    def energy_delta_applicable(self) -> bool:
        return self.option.annual_energy_share_pct is not None

    @property
    def costs_known(self) -> bool:
        return True

    @property
    def emissions_known(self) -> bool:
        return self.total_emissions_t is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "supplier": self.option.supplier,
            "confidence": self.option.confidence,
            "emissions_basis": self.option.emissions_basis,
            "horizon_years": self.horizon_years,
            "initial_outlay": str(_money(self.initial_outlay)),
            "purchase_cost": str(_money(self.purchase_cost)),
            "transport_cost": str(_money(self.transport_cost)),
            "annual_opex": str(_money(self.annual_opex)),
            "annual_maintenance": str(_money(self.annual_maintenance)),
            "annual_savings": str(_money(self.annual_savings)),
            "annual_net_costs": [str(_money(v)) for v in self.annual_net_costs],
            "cost_curve": [str(_money(v)) for v in self.cost_curve],
            "cash_curve": [str(_money(v)) for v in self.cash_curve],
            "total_cost": str(_money(self.total_cost)),
            "total_savings": str(_money(self.total_savings)),
            "total_opex": str(_money(self.total_opex)),
            "total_maintenance": str(_money(self.total_maintenance)),
            "npv": str(_money(self.npv)) if self.npv is not None else None,
            "annual_emissions_t": str(self.annual_emissions_t) if self.annual_emissions_t is not None else None,
            "emissions_curve_t": [str(v) for v in self.emissions_curve_t] if self.emissions_curve_t is not None else None,
            "total_emissions_t": str(self.total_emissions_t) if self.total_emissions_t is not None else None,
            "warnings": self.warnings,
            "assumptions": self.assumptions,
            "energy_delta_applicable": self.energy_delta_applicable,
        }


def compute_option(option: OptionInput, horizon_years: int, params: ScenarioParams | None = None) -> OptionResult:
    """Calcule le résultat financier et carbone d'une option sur l'horizon commun."""
    params = params or ScenarioParams()
    horizon_years = validate_horizon(horizon_years)

    activity_mult = Decimal("1") + params.activity_volume_delta_pct / 100
    energy_mult = Decimal("1") + params.energy_price_delta_pct / 100
    transport_mult = Decimal("1") + params.transport_delta_pct / 100
    savings_mult = Decimal("1") + params.savings_delta_pct / 100
    emissions_mult = Decimal("1") + params.emission_factor_delta_pct / 100

    warnings: list[str] = []
    assumptions: list[str] = []

    # Coûts d'acquisition et de transport (année 0)
    transport_effective = _money(option.transport_cost * transport_mult)
    initial_outlay = _money(option.purchase_cost + transport_effective)

    # Coûts de fonctionnement annuels : la part d'énergie réagit au scénario
    # « prix de l'énergie » ; le reste suit le volume d'activité.
    share = option.annual_energy_share_pct
    if share is None:
        energy_part = ZERO
        other_part = option.annual_opex
        if params.energy_price_delta_pct:
            warnings.append(
                f"Option « {option.name} » : le scénario de prix de l'énergie n'a pas pu être appliqué "
                "(part d'énergie non renseignée dans les coûts de fonctionnement)."
            )
    else:
        energy_part = option.annual_opex * share / 100
        other_part = option.annual_opex - energy_part
        assumptions.append(
            f"Part d'énergie déclarée dans les coûts de fonctionnement : {fmt_number(share, 1)} %."
        )

    annual_opex = _money(activity_mult * (energy_part * energy_mult + other_part))
    annual_maintenance = _money(option.annual_maintenance)
    annual_savings = _money(activity_mult * (option.annual_savings * savings_mult))

    if params.activity_volume_delta_pct:
        assumptions.append(
            "Le volume d'activité module les coûts de fonctionnement et les économies attendues "
            "(hypothèse de coûts variables) ; la maintenance est maintenue constante."
        )

    net_year = annual_opex + annual_maintenance - annual_savings
    annual_net_costs = [net_year for _ in range(horizon_years)]

    cost_curve: list[Decimal] = [initial_outlay]
    for net in annual_net_costs:
        cost_curve.append(_money(cost_curve[-1] + net))

    cash_curve: list[Decimal] = [-initial_outlay]
    for net in annual_net_costs:
        cash_curve.append(_money(cash_curve[-1] - net))

    total_cost = cost_curve[-1]
    total_savings = _money(annual_savings * horizon_years)
    total_opex = _money(annual_opex * horizon_years)
    total_maintenance = _money(annual_maintenance * horizon_years)

    # Valeur actualisée nette (optionnelle)
    npv: Decimal | None = None
    if params.discount_rate_pct and params.discount_rate_pct != ZERO:
        rate = params.discount_rate_pct / 100
        discounted = initial_outlay
        for year, net in enumerate(annual_net_costs, start=1):
            discounted += net / ((Decimal("1") + rate) ** year)
        npv = _money(discounted)
        assumptions.append(
            f"Actualisation appliquée au taux de {fmt_number(params.discount_rate_pct, 2)} % par an."
        )

    # Émissions
    annual_emissions_t: Decimal | None = None
    emissions_curve: list[Decimal] | None = None
    total_emissions_t: Decimal | None = None
    if option.annual_emissions_kg is not None:
        annual_kg = option.annual_emissions_kg * emissions_mult * activity_mult
        annual_emissions_t = _emissions_t(annual_kg / 1000)
        emissions_curve = [ZERO]
        for _ in range(horizon_years):
            emissions_curve.append(_emissions_t(emissions_curve[-1] + annual_emissions_t))
        total_emissions_t = emissions_curve[-1]
        assumptions.append(
            "Émissions cumulées = émissions annuelles x nombre d'années (aucune variation annuelle inventée)."
        )
    else:
        warnings.append(
            f"Option « {option.name} » : émissions non renseignées — la comparaison carbone "
            "et le coût par tonne évitée restent indisponibles pour cette option."
        )

    # Durée de vie vs horizon
    effective_life = option.useful_life_years
    if effective_life is not None:
        effective_life = effective_life + params.lifetime_delta_years
        if effective_life <= 0:
            warnings.append(f"Option « {option.name} » : la durée d'utilisation effective est nulle.")
        elif effective_life < horizon_years:
            warnings.append(
                f"Option « {option.name} » : durée d'utilisation ({fmt_number(effective_life, 1)} ans) "
                f"inférieure à l'horizon commun ({horizon_years} ans). Aucun remplacement n'est chiffré "
                "automatiquement : le résultat suppose un usage maintenu sur toute la période."
            )
        elif effective_life > horizon_years:
            assumptions.append(
                f"Durée d'utilisation déclarée supérieure à l'horizon : seule la période de "
                f"{horizon_years} ans est comparée."
            )
    if option.purchase_cost == ZERO and option.transport_cost == ZERO:
        warnings.append(f"Option « {option.name} » : aucun coût d'acquisition renseigné.")

    return OptionResult(
        option=option,
        horizon_years=horizon_years,
        initial_outlay=initial_outlay,
        purchase_cost=_money(option.purchase_cost),
        transport_cost=transport_effective,
        annual_opex=annual_opex,
        annual_maintenance=annual_maintenance,
        annual_savings=annual_savings,
        annual_net_costs=annual_net_costs,
        cost_curve=[_money(v) for v in cost_curve],
        cash_curve=[_money(v) for v in cash_curve],
        total_cost=total_cost,
        total_savings=total_savings,
        total_opex=total_opex,
        total_maintenance=total_maintenance,
        npv=npv,
        annual_emissions_t=annual_emissions_t,
        emissions_curve_t=emissions_curve,
        total_emissions_t=total_emissions_t,
        warnings=warnings,
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------
# Comparaisons
# ---------------------------------------------------------------------------
@dataclass
class PairComparison:
    """Comparaison deux à deux de deux options (a - b)."""

    a_key: str
    b_key: str
    a_name: str
    b_name: str
    horizon_years: int
    cost_delta: Decimal
    upfront_delta: Decimal
    annual_net_delta: Decimal
    emissions_delta_t: Decimal | None
    avoided_t: Decimal | None
    cost_per_tonne_avoided: Decimal | None
    cheaper_key: str | None
    cleaner_key: str | None
    double_gain: bool | None
    dominated_by: str | None
    break_even: dict[str, Any] | None
    interpretation_parts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "a_key": self.a_key,
            "b_key": self.b_key,
            "a_name": self.a_name,
            "b_name": self.b_name,
            "horizon_years": self.horizon_years,
            "cost_delta": str(_money(self.cost_delta)),
            "upfront_delta": str(_money(self.upfront_delta)),
            "annual_net_delta": str(_money(self.annual_net_delta)),
            "emissions_delta_t": str(self.emissions_delta_t) if self.emissions_delta_t is not None else None,
            "avoided_t": str(self.avoided_t) if self.avoided_t is not None else None,
            "cost_per_tonne_avoided": str(self.cost_per_tonne_avoided) if self.cost_per_tonne_avoided is not None else None,
            "cheaper_key": self.cheaper_key,
            "cleaner_key": self.cleaner_key,
            "double_gain": self.double_gain,
            "dominated_by": self.dominated_by,
            "break_even": self.break_even,
            "interpretation_parts": self.interpretation_parts,
        }


def _pair(a: OptionResult, b: OptionResult) -> PairComparison:
    horizon = a.horizon_years
    cost_delta = _money(a.total_cost - b.total_cost)
    upfront_delta = _money(a.initial_outlay - b.initial_outlay)
    annual_net_delta = _money(a.annual_net_costs[0] - b.annual_net_costs[0])

    cheaper_key: str | None
    if cost_delta < 0:
        cheaper_key = a.key
    elif cost_delta > 0:
        cheaper_key = b.key
    else:
        cheaper_key = None

    emissions_delta_t: Decimal | None = None
    avoided_t: Decimal | None = None
    cost_per_tonne_avoided: Decimal | None = None
    cleaner_key: str | None = None
    double_gain: bool | None = None
    if a.total_emissions_t is not None and b.total_emissions_t is not None:
        emissions_delta_t = _emissions_t(a.total_emissions_t - b.total_emissions_t)
        if emissions_delta_t < 0:
            cleaner_key = a.key
        elif emissions_delta_t > 0:
            cleaner_key = b.key
        if cleaner_key is not None:
            avoided_t = abs(emissions_delta_t)
            cleaner = a if cleaner_key == a.key else b
            dirtier = b if cleaner_key == a.key else a
            premium = _money(cleaner.total_cost - dirtier.total_cost)
            if avoided_t > 0:
                cost_per_tonne_avoided = (premium / avoided_t).quantize(MONEY_Q, ROUND_HALF_UP)
                double_gain = premium < 0

    dominated_by: str | None = None
    if a.total_emissions_t is not None and b.total_emissions_t is not None:
        if a.total_cost <= b.total_cost and a.total_emissions_t <= b.total_emissions_t and (
            a.total_cost < b.total_cost or a.total_emissions_t < b.total_emissions_t
        ):
            dominated_by = a.key  # a domine b
        elif b.total_cost <= a.total_cost and b.total_emissions_t <= a.total_emissions_t and (
            b.total_cost < a.total_cost or b.total_emissions_t < a.total_emissions_t
        ):
            dominated_by = b.key

    # Délai de rattrapage : une option plus chère à l'achat mais moins chère à l'usage
    break_even: dict[str, Any] | None = None
    if upfront_delta > 0 and annual_net_delta < 0:
        years = (upfront_delta / (-annual_net_delta)).quantize(EMIS_Q, ROUND_HALF_UP)
        break_even = {"favors_key": a.key, "years": str(years)}
    elif upfront_delta < 0 and annual_net_delta > 0:
        years = ((-upfront_delta) / annual_net_delta).quantize(EMIS_Q, ROUND_HALF_UP)
        break_even = {"favors_key": b.key, "years": str(years)}

    parts: list[str] = []
    if cheaper_key:
        cheaper_name = a.name if cheaper_key == a.key else b.name
        parts.append(
            f"Sur {horizon} ans, l'option « {cheaper_name} » coûte {fmt_money(abs(cost_delta))} de moins."
        )
    else:
        parts.append(f"Sur {horizon} ans, les deux options ont un coût total équivalent.")

    if avoided_t is not None and cleaner_key is not None:
        cleaner_name = a.name if cleaner_key == a.key else b.name
        if cost_per_tonne_avoided is not None:
            if double_gain:
                parts.append(
                    f"L'option « {cleaner_name} » évite {fmt_number(avoided_t, 2)} t CO₂e en étant aussi "
                    f"la moins chère : {fmt_money(abs(cost_per_tonne_avoided))} économisés par tonne évitée."
                )
            else:
                parts.append(
                    f"L'option « {cleaner_name} » évite {fmt_number(avoided_t, 2)} t CO₂e pour un surcoût de "
                    f"{fmt_money(cost_per_tonne_avoided)} par tonne évitée."
                )
        else:
            parts.append(
                f"L'option « {cleaner_name} » évite {fmt_number(avoided_t, 2)} t CO₂e, montant du surcoût à préciser."
            )
    elif a.total_emissions_t is None or b.total_emissions_t is None:
        missing = a.name if a.total_emissions_t is None else b.name
        parts.append(f"Comparaison carbone indisponible : émissions non renseignées pour « {missing} ».")
    else:
        parts.append("Les deux options ont des émissions cumulées identiques.")

    if break_even:
        favored = a.name if break_even["favors_key"] == a.key else b.name
        parts.append(
            f"Le surcoût initial de « {favored} » est compensé en environ "
            f"{fmt_number(break_even['years'], 1)} an(s) par des coûts annuels plus faibles."
        )

    return PairComparison(
        a_key=a.key,
        b_key=b.key,
        a_name=a.name,
        b_name=b.name,
        horizon_years=horizon,
        cost_delta=cost_delta,
        upfront_delta=upfront_delta,
        annual_net_delta=annual_net_delta,
        emissions_delta_t=emissions_delta_t,
        avoided_t=avoided_t,
        cost_per_tonne_avoided=cost_per_tonne_avoided,
        cheaper_key=cheaper_key,
        cleaner_key=cleaner_key,
        double_gain=double_gain,
        dominated_by=dominated_by,
        break_even=break_even,
        interpretation_parts=parts,
    )


@dataclass
class ComparisonResult:
    """Comparaison complète de 2 à N options."""

    horizon_years: int
    results: list[OptionResult]
    by_key: dict[str, OptionResult]
    pairs: list[PairComparison]
    cheapest_key: str | None
    greenest_key: str | None
    best_treasury_key: str | None
    extended_cost: dict[str, Decimal | None]
    extended_best_key: str | None
    frontier: list[str]
    carbon_price: Decimal
    notes: list[str] = field(default_factory=list)

    @property
    def cheapest(self) -> OptionResult | None:
        return self.by_key.get(self.cheapest_key) if self.cheapest_key else None

    @property
    def greenest(self) -> OptionResult | None:
        return self.by_key.get(self.greenest_key) if self.greenest_key else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_years": self.horizon_years,
            "carbon_price": str(_money(self.carbon_price)),
            "options": [r.to_dict() for r in self.results],
            "pairs": [p.to_dict() for p in self.pairs],
            "cheapest_key": self.cheapest_key,
            "greenest_key": self.greenest_key,
            "best_treasury_key": self.best_treasury_key,
            "extended_cost": {k: (str(_money(v)) if v is not None else None) for k, v in self.extended_cost.items()},
            "extended_best_key": self.extended_best_key,
            "frontier": self.frontier,
            "notes": self.notes,
        }


def build_comparison(
    results: list[OptionResult],
    carbon_price: Decimal | float | str | None = ZERO,
) -> ComparisonResult:
    """Compare les résultats de 2 à N options (coûts, trésorerie, émissions)."""
    if len(results) < 2:
        raise ValidationError("Ajoutez au moins deux options pour lancer la comparaison.")
    carbon_price = _d(carbon_price)
    if carbon_price < 0:
        raise ValidationError("Le prix interne du carbone ne peut pas être négatif.")

    by_key = {r.key: r for r in results}
    horizon = results[0].horizon_years

    cheapest_key = min(results, key=lambda r: (r.total_cost, r.key)).key
    treasury_key = min(results, key=lambda r: (r.initial_outlay, r.key)).key
    with_emissions = [r for r in results if r.total_emissions_t is not None]
    greenest_key = min(with_emissions, key=lambda r: (r.total_emissions_t, r.key)).key if with_emissions else None

    extended_cost: dict[str, Decimal | None] = {}
    for r in results:
        if r.total_emissions_t is not None:
            extended_cost[r.key] = _money(r.total_cost + r.total_emissions_t * carbon_price)
        else:
            extended_cost[r.key] = None
    priced = {k: v for k, v in extended_cost.items() if v is not None}
    extended_best_key = min(priced, key=lambda k: (priced[k], k)) if priced else None

    # Frontière de Pareto : options qu'aucune autre ne domine
    pairs: list[PairComparison] = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            pairs.append(_pair(results[i], results[j]))

    dominated: set[str] = set()
    for pair in pairs:
        if pair.dominated_by == pair.a_key:
            dominated.add(pair.b_key)
        elif pair.dominated_by == pair.b_key:
            dominated.add(pair.a_key)
    frontier = [r.key for r in results if r.key not in dominated]

    notes: list[str] = []
    missing_emissions = [r.name for r in results if r.total_emissions_t is None]
    if missing_emissions:
        notes.append(
            "Comparaison carbone partielle : émissions non renseignées pour "
            + ", ".join(f"« {name} »" for name in missing_emissions)
            + ". Les indicateurs carbone restent indisponibles pour ces options."
        )
    if carbon_price == ZERO:
        notes.append(
            "Aucun prix interne du carbone n'est défini : les émissions ne sont pas converties en dirhams "
            "dans le coût total. Une réduction d'émissions n'est pas une économie financière automatique."
        )
    else:
        notes.append(
            f"Prix interne du carbone appliqué : {fmt_money(carbon_price)} par tonne de CO₂e évitée "
            "(hypothèse de décision, non une charge comptable)."
        )
    if len(frontier) > 1:
        notes.append(
            "Aucune option ne domine les autres sur les deux critères : comparez la frontière de compromis "
            "plutôt que de chercher un gagnant unique."
        )

    return ComparisonResult(
        horizon_years=horizon,
        results=results,
        by_key=by_key,
        pairs=pairs,
        cheapest_key=cheapest_key,
        greenest_key=greenest_key,
        best_treasury_key=treasury_key,
        extended_cost=extended_cost,
        extended_best_key=extended_best_key,
        frontier=frontier,
        carbon_price=carbon_price,
        notes=notes,
    )


def compare_options(
    options: list[OptionInput],
    horizon_years: Any,
    params: ScenarioParams | None = None,
    carbon_price: Decimal | float | str | None = ZERO,
) -> ComparisonResult:
    """Point d'entrée principal : options -> résultats comparés."""
    horizon = validate_horizon(horizon_years)
    results = [compute_option(option, horizon, params) for option in options]
    return build_comparison(results, carbon_price)


COST_PER_TONNE_FORMULA = (
    "Coût par tonne de CO₂e évitée = (coût total de l'option la moins émettrice "
    "− coût total de l'option la plus émettrice) ÷ (émissions de la plus émettrice "
    "− émissions de la moins émettrice)"
)
