"""Conversions d'unités d'activité.

Chaque unité appartient à une famille ; on ne convertit qu'à l'intérieur
d'une même famille. Toute conversion impossible lève ``UnitError`` — le
code appelant doit alors refuser l'estimation carbone au lieu de produire
un chiffre faux.
"""

from __future__ import annotations

from decimal import Decimal

from ..errors import UnitError

# unités -> (famille, facteur vers l'unité de base)
_UNITS: dict[str, tuple[str, Decimal]] = {
    "kwh": ("energie", Decimal("1")),
    "mwh": ("energie", Decimal("1000")),
    "gj": ("energie", Decimal("277.777778")),
    "l": ("volume", Decimal("1")),
    "m3": ("volume", Decimal("1000")),
    "litre": ("volume", Decimal("1")),
    "kg": ("masse", Decimal("1")),
    "g": ("masse", Decimal("0.001")),
    "t": ("masse", Decimal("1000")),
    "tonne": ("masse", Decimal("1000")),
    "km": ("distance", Decimal("1")),
    "t.km": ("fret", Decimal("1")),
    "passager.km": ("passagers", Decimal("1")),
    "m2": ("surface", Decimal("1")),
    "unite": ("compte", Decimal("1")),
    "nuit": ("compte", Decimal("1")),
    "forfait": ("compte", Decimal("1")),
    "mad": ("monetaire", Decimal("1")),
    "eur": ("monetaire", Decimal("1")),
}

_ALIASES = {
    "m³": "m3",
    "m3 ": "m3",
    "l ": "l",
    "lt": "l",
    "kwh ": "kwh",
    "kw h": "kwh",
    "tonnes": "t",
    "kms": "km",
    "km ": "km",
    "dh": "mad",
    "dhs": "mad",
    "dirham": "mad",
    "dirhams": "mad",
    "": "",
}

FAMILY_LABELS = {
    "energie": "énergie",
    "volume": "volume",
    "masse": "masse",
    "distance": "distance",
    "fret": "fret",
    "passagers": "passagers",
    "surface": "surface",
    "compte": "quantité",
    "monetaire": "montant",
}


def normalize_unit(unit: str | None) -> str:
    """Normalise l'écriture d'une unité (casse, alias courants)."""
    if unit is None:
        return ""
    normalized = str(unit).strip().lower().replace(" ", "")
    normalized = _ALIASES.get(normalized, normalized)
    return normalized


def canonical_unit(unit: str | None) -> str | None:
    """Retourne l'unité canonique affichée (``kWh``, ``t``, ``m3``…)."""
    normalized = normalize_unit(unit)
    if not normalized:
        return None
    for canonical in ("kWh", "MWh", "GJ", "L", "m3", "kg", "t", "km", "t.km", "passager.km", "m2", "unite", "nuit", "forfait", "MAD"):
        if normalize_unit(canonical) == normalized:
            return canonical
    return None


def unit_family(unit: str | None) -> str:
    """Famille de l'unité. Lève ``UnitError`` si l'unité est inconnue."""
    normalized = normalize_unit(unit)
    if normalized not in _UNITS:
        raise UnitError(f"Unité inconnue : « {unit} ».")
    return _UNITS[normalized][0]


def is_known(unit: str | None) -> bool:
    return normalize_unit(unit) in _UNITS


def are_compatible(unit_a: str | None, unit_b: str | None) -> bool:
    """Vrai si les deux unités appartiennent à la même famille."""
    if not is_known(unit_a) or not is_known(unit_b):
        return False
    if normalize_unit(unit_a) == normalize_unit(unit_b):
        return True
    family = unit_family(unit_a)
    if family == "monetaire":
        # MAD et EUR ne sont pas des unités convertibles entre elles sans taux.
        return normalize_unit(unit_a) == normalize_unit(unit_b)
    return family == unit_family(unit_b)


def convert(value: Decimal, from_unit: str | None, to_unit: str | None) -> Decimal:
    """Convertit ``value`` de ``from_unit`` vers ``to_unit``.

    Exemple : ``convert(Decimal("2"), "MWh", "kWh") == Decimal("2000")``.
    """
    if not are_compatible(from_unit, to_unit):
        raise UnitError(
            f"Conversion impossible entre « {from_unit} » et « {to_unit} » : familles différentes."
        )
    source = _UNITS[normalize_unit(from_unit)][1]
    target = _UNITS[normalize_unit(to_unit)][1]
    return (Decimal(value) * source) / target
