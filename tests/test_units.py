"""Tests des conversions d'unités (aucune conversion silencieuse)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.calc.units import are_compatible, canonical_unit, convert, is_known, normalize_unit, unit_family
from app.errors import UnitError


def test_normalisation_alias():
    assert normalize_unit("kWh ") == "kwh"
    assert normalize_unit("m³") == "m3"
    assert normalize_unit("DHS") == "mad"
    assert normalize_unit(None) == ""
    assert canonical_unit("mwh") == "MWh"
    assert canonical_unit("tonnes") == "t"
    assert canonical_unit("inconnue") is None


def test_conversion_dans_la_meme_famille():
    assert convert(Decimal("2"), "MWh", "kWh") == Decimal("2000")
    assert convert(Decimal("1500"), "kg", "t") == Decimal("1.5")
    assert convert(Decimal("1000"), "m3", "L") == Decimal("1000000")
    assert convert(Decimal("1"), "t.km", "t.km") == Decimal("1")


def test_conversion_refusee_entre_familles():
    with pytest.raises(UnitError):
        convert(Decimal("1"), "kWh", "kg")
    assert not are_compatible("kWh", "L")
    assert not are_compatible("MAD", "EUR")  # aucune conversion monétaire sans taux explicite
    assert are_compatible("tonne", "kg")
    assert not are_compatible("kWh", "unité_inconnue")


def test_familles_et_unicite():
    assert unit_family("kWh") == "energie"
    assert unit_family("t.km") == "fret"
    assert is_known("forfait")
    assert not is_known("")
    with pytest.raises(UnitError):
        unit_family("hectare")
