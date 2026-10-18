"""Formatage des nombres, montants (MAD) et émissions, au style français."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

NBSP = "\u202f"  # espace fine insécable, standard pour les milliers en français


def to_decimal(value) -> Decimal | None:
    """Convertit une valeur hétérogène en ``Decimal`` (ou ``None``)."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip().replace(NBSP, "").replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    # Format français « 12 345,67 » ou format international « 12,345.67 »
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _group_fr(value: Decimal, decimals: int) -> str:
    quantized = value.quantize(Decimal(1).scaleb(-decimals)) if decimals else value.quantize(Decimal(1))
    text = f"{quantized:,.{decimals}f}"
    return text.replace(",", NBSP).replace(".", ",")


def fmt_number(value, decimals: int = 2) -> str:
    number = to_decimal(value)
    if number is None:
        return "—"
    return _group_fr(number, decimals)


def fmt_money(value, *, symbol: str = "DH", decimals: int = 2, sign: bool = False) -> str:
    """« 12 345,67 DH ». ``sign=True`` force l'affichage du signe (+/-)."""
    number = to_decimal(value)
    if number is None:
        return "—"
    prefix = "+" if sign and number > 0 else ""
    return f"{prefix}{_group_fr(number, decimals)}{NBSP}{symbol}"


def fmt_money_compact(value, *, symbol: str = "DH") -> str:
    """« 20,0 kDH » pour les cartes compactes."""
    number = to_decimal(value)
    if number is None:
        return "—"
    absolute = abs(number)
    if absolute >= 1_000_000:
        return f"{_group_fr(number / 1000, 0)}{NBSP}k{symbol}"
    if absolute >= 10_000:
        return f"{_group_fr(number / 1000, 1)}{NBSP}k{symbol}"
    return fmt_money(number, symbol=symbol)


def fmt_pct(value, decimals: int = 1, sign: bool = False) -> str:
    number = to_decimal(value)
    if number is None:
        return "—"
    prefix = "+" if sign and number > 0 else ""
    return f"{prefix}{_group_fr(number, decimals)}{NBSP}%"


def fmt_kg(value) -> str:
    """Émissions en kg, basculées en tonnes au-delà de 1 000 kg."""
    number = to_decimal(value)
    if number is None:
        return "—"
    if abs(number) >= 1000:
        return f"{_group_fr(number / 1000, 2)}{NBSP}t CO₂e"
    return f"{_group_fr(number, 1)}{NBSP}kg CO₂e"


def fmt_tco2e(value_t) -> str:
    number = to_decimal(value_t)
    if number is None:
        return "—"
    return f"{_group_fr(number, 2)}{NBSP}t CO₂e"


def fmt_quantity(value, unit: str | None = None, decimals: int = 2) -> str:
    number = to_decimal(value)
    if number is None:
        return "—"
    return f"{_group_fr(number, decimals)}{NBSP}{unit}" if unit else _group_fr(number, decimals)


MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


def fmt_date_long(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day} {MONTHS_FR[value.month - 1]} {value.year}"


def fmt_period(start: date | None, end: date | None) -> str:
    if start is None and end is None:
        return "—"
    if start and end and start == end:
        return fmt_date(start)
    return f"{fmt_date(start)} → {fmt_date(end)}"


def fmt_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return f"{fmt_date(value)} à {value.hour:02d}:{value.minute:02d} UTC"
