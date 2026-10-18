"""Tests du formatage français des nombres, montants (MAD) et émissions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.calc.formatting import (
    NBSP,
    fmt_date,
    fmt_date_long,
    fmt_kg,
    fmt_money,
    fmt_money_compact,
    fmt_number,
    fmt_pct,
    fmt_period,
    fmt_quantity,
    fmt_tco2e,
    to_decimal,
)


def test_to_decimal_formats_francais_et_internationaux():
    assert to_decimal("12 345,67") == Decimal("12345.67")
    assert to_decimal("12345.67") == Decimal("12345.67")
    assert to_decimal("12,345.67") == Decimal("12345.67")
    assert to_decimal("1\u202f234,5") == Decimal("1234.5")
    assert to_decimal("") is None
    assert to_decimal(None) is None
    assert to_decimal("abc") is None
    assert to_decimal(15) == Decimal("15")
    assert to_decimal(15.5) == Decimal("15.5")


def test_formatage_montants_et_nombres():
    assert fmt_money(Decimal("20000")) == f"20{NBSP}000,00{NBSP}DH"
    assert fmt_money(Decimal("20000"), decimals=0) == f"20{NBSP}000{NBSP}DH"
    assert fmt_money(Decimal("-800.5")) == f"-800,50{NBSP}DH"
    assert fmt_money(Decimal("5000"), sign=True) == f"+5{NBSP}000,00{NBSP}DH"
    assert fmt_number(Decimal("5"), 2) == "5,00"
    assert fmt_pct(Decimal("12.5"), 1) == f"12,5{NBSP}%"
    assert fmt_money(None) == "—"


def test_formatage_compact_et_emissions():
    assert fmt_money_compact(Decimal("20000")) == f"20,0{NBSP}kDH"
    assert fmt_money_compact(Decimal("2000000")) == f"2{NBSP}000{NBSP}kDH"
    assert fmt_money_compact(Decimal("4500")) == f"4{NBSP}500,00{NBSP}DH"
    assert fmt_kg(Decimal("850")) == f"850,0{NBSP}kg CO₂e"
    assert fmt_kg(Decimal("25000")) == f"25,00{NBSP}t CO₂e"
    assert fmt_tco2e(Decimal("225")) == f"225,00{NBSP}t CO₂e"
    assert fmt_quantity(Decimal("15000"), "kWh") == f"15{NBSP}000,00{NBSP}kWh"


def test_formatage_dates():
    assert fmt_date(date(2026, 3, 4)) == "04/03/2026"
    assert fmt_date_long(date(2026, 3, 4)) == "4 mars 2026"
    assert fmt_period(date(2026, 3, 1), date(2026, 3, 31)) == "01/03/2026 → 31/03/2026"
    assert fmt_period(date(2026, 3, 4), date(2026, 3, 4)) == "04/03/2026"
    assert fmt_date(None) == "—"
