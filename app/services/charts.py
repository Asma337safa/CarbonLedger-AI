"""Génération de graphiques SVG côté serveur.

Aucune dépendance JavaScript : les graphiques sont accessibles (``role=img``,
libellés texte), sobres et adaptés à un usage professionnel. Les valeurs sont
toujours affichées en infobulle (``<title>``) et en étiquette.
"""

from __future__ import annotations

import html
from decimal import Decimal
from typing import Callable, Iterable, Sequence

from ..calc.formatting import to_decimal

AXIS = "#94A3B8"
GRID = "#E2E8F0"
TEXT = "#172B4D"
MUTED = "#64748B"
SURFACE = "#FFFFFF"
BRAND = "#176B4D"
PALETTE = ["#176B4D", "#172B4D", "#64748B", "#F4B942", "#0E7490", "#7C3AED"]


def compact_number(value: Decimal | float) -> str:
    """« 180 k », « 1,2 M » — pour les axes."""
    number = to_decimal(value) or Decimal("0")
    absolute = abs(number)
    if absolute >= 1_000_000:
        text = f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text.replace('.', ',')} M"
    if absolute >= 1_000:
        text = f"{number / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{text.replace('.', ',')} k"
    if absolute == absolute.to_integral_value():
        return f"{int(number)}"
    text = f"{number:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _nice_max(values: Iterable[Decimal], minimum: Decimal = Decimal("1")) -> Decimal:
    high = max([to_decimal(v) or Decimal("0") for v in values] + [minimum])
    if high <= 0:
        return minimum
    magnitude = Decimal(10) ** (len(str(int(abs(high)))) - 1)
    for multiplier in ("1", "1.5", "2", "2.5", "3", "4", "5", "6", "8", "10"):
        candidate = Decimal(multiplier) * magnitude
        if candidate >= high:
            return candidate
    return magnitude * 10


def _grid_and_axis(
    x0: float, y0: float, width: float, height: float, y_max: Decimal, axis_fmt: Callable[[Decimal], str]
) -> str:
    parts: list[str] = []
    steps = 4
    for index in range(steps + 1):
        value = y_max * Decimal(index) / steps
        y = y0 + height - (height * float(value / y_max) if y_max else 0)
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x0 + width:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0 - 8:.1f}" y="{y + 4:.1f}" text-anchor="end" font-size="10.5" fill="{MUTED}">'
            f"{html.escape(axis_fmt(value))}</text>"
        )
    return "".join(parts)


def grouped_bar_chart(
    categories: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[Decimal | float]]],
    *,
    axis_fmt: Callable[[Decimal], str] = compact_number,
    value_fmt: Callable[[Decimal], str] = compact_number,
    width: int = 680,
    height: int = 300,
    aria_label: str = "Graphique à barres groupées",
    show_values: bool = True,
) -> str:
    """Barres groupées : une barre par série et par catégorie."""
    if not categories or not series:
        return ""
    pad_left, pad_right, pad_top, pad_bottom = 68, 16, 28 if any(s[0] for s in series) else 12, 52
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    all_values = [to_decimal(v) or Decimal("0") for _, _, values in series for v in values]
    y_max = _nice_max(all_values)
    group_width = plot_width / len(categories)
    bar_width = min(34.0, (group_width * 0.7) / max(1, len(series)))

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;height:auto" '
        f'role="img" aria-label="{html.escape(aria_label)}" class="chart">'
    ]
    parts.append(_grid_and_axis(pad_left, pad_top, plot_width, plot_height, y_max, axis_fmt))

    for cat_index, category in enumerate(categories):
        group_x = pad_left + cat_index * group_width
        total_bars = len(series) * bar_width
        start_x = group_x + (group_width - total_bars) / 2
        for ser_index, (name, color, values) in enumerate(series):
            value = to_decimal(values[cat_index]) or Decimal("0")
            bar_height = float(value / y_max) * plot_height if y_max else 0
            x = start_x + ser_index * bar_width
            y = pad_top + plot_height - bar_height
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width - 4:.1f}" height="{max(0.0, bar_height):.1f}" '
                f'rx="3" fill="{color}"><title>{html.escape(name)} — {html.escape(category)} : '
                f"{html.escape(value_fmt(value))}</title></rect>"
            )
            if show_values and value > 0:
                parts.append(
                    f'<text x="{x + (bar_width - 4) / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle" '
                    f'font-size="10" fill="{MUTED}">{html.escape(value_fmt(value))}</text>'
                )
        parts.append(
            f'<text x="{group_x + group_width / 2:.1f}" y="{pad_top + plot_height + 18:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{TEXT}">{html.escape(category)}</text>'
        )

    legend_y = height - 16
    legend_x = pad_left
    for name, color, _ in series:
        if not name:
            continue
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 8}" width="10" height="10" rx="2" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 15}" y="{legend_y}" font-size="11" fill="{MUTED}">{html.escape(name)}</text>'
        )
        legend_x += 22 + len(name) * 6.4
    parts.append("</svg>")
    return "".join(parts)


def multi_line_chart(
    x_labels: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[Decimal | float]]],
    *,
    axis_fmt: Callable[[Decimal], str] = compact_number,
    value_fmt: Callable[[Decimal], str] = compact_number,
    width: int = 680,
    height: int = 300,
    aria_label: str = "Graphique d'évolution",
) -> str:
    """Courbes cumulées (une ligne par option)."""
    if not x_labels or not series:
        return ""
    pad_left, pad_right, pad_top, pad_bottom = 68, 16, 20, 52
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    all_values = [to_decimal(v) or Decimal("0") for _, _, values in series for v in values]
    y_max = _nice_max(all_values)

    def px(index: int) -> float:
        if len(x_labels) == 1:
            return pad_left + plot_width / 2
        return pad_left + plot_width * index / (len(x_labels) - 1)

    def py(value: Decimal) -> float:
        return pad_top + plot_height - (float(value / y_max) * plot_height if y_max else 0)

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;height:auto" '
        f'role="img" aria-label="{html.escape(aria_label)}" class="chart">'
    ]
    parts.append(_grid_and_axis(pad_left, pad_top, plot_width, plot_height, y_max, axis_fmt))

    label_step = max(1, len(x_labels) // 10)
    for index, label in enumerate(x_labels):
        if index % label_step and index != len(x_labels) - 1:
            continue
        parts.append(
            f'<text x="{px(index):.1f}" y="{pad_top + plot_height + 18:.1f}" text-anchor="middle" '
            f'font-size="10.5" fill="{MUTED}">{html.escape(label)}</text>'
        )

    for name, color, values in series:
        points = [(px(i), py(to_decimal(v) or Decimal("0"))) for i, v in enumerate(values)]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round"/>')
        for (x, y), value in zip(points, values):
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="{SURFACE}" stroke="{color}" stroke-width="2">'
                f"<title>{html.escape(name)} — {html.escape(x_labels[points.index((x, y))])} : "
                f"{html.escape(value_fmt(to_decimal(value) or Decimal('0')))}</title></circle>"
            )

    legend_y = height - 14
    legend_x = pad_left
    for name, color, _ in series:
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 8}" width="10" height="10" rx="2" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 15}" y="{legend_y}" font-size="11" fill="{MUTED}">{html.escape(name)}</text>'
        )
        legend_x += 22 + len(name) * 6.4
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(
    rows: Sequence[tuple[str, Decimal | float]],
    *,
    value_fmt: Callable[[Decimal], str] = compact_number,
    width: int = 680,
    color: str = BRAND,
    aria_label: str = "Répartition",
    label_width: int = 210,
) -> str:
    """Barres horizontales (répartitions par catégorie, top fournisseurs…)."""
    if not rows:
        return ""
    row_height = 30
    height = len(rows) * row_height + 12
    bar_x = label_width + 12
    bar_width = width - bar_x - 110
    values = [to_decimal(v) or Decimal("0") for _, v in rows]
    maximum = max(values + [Decimal("1")])

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;height:auto" '
        f'role="img" aria-label="{html.escape(aria_label)}" class="chart">'
    ]
    for index, (label, value) in enumerate(rows):
        number = to_decimal(value) or Decimal("0")
        y = index * row_height + 6
        length = float(number / maximum) * bar_width if maximum else 0
        text = label if len(label) <= 30 else label[:29] + "…"
        parts.append(
            f'<text x="{label_width}" y="{y + 15}" text-anchor="end" font-size="11.5" fill="{TEXT}">'
            f"{html.escape(text)}</text>"
        )
        parts.append(f'<rect x="{bar_x}" y="{y + 4}" width="{bar_width}" height="14" rx="4" fill="#F1F5F9"/>')
        parts.append(
            f'<rect x="{bar_x}" y="{y + 4}" width="{max(1.0, length):.1f}" height="14" rx="4" fill="{color}">'
            f"<title>{html.escape(label)} : {html.escape(value_fmt(number))}</title></rect>"
        )
        parts.append(
            f'<text x="{bar_x + bar_width + 10}" y="{y + 15}" font-size="11.5" fill="{MUTED}" font-weight="500">'
            f"{html.escape(value_fmt(number))}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def tornado_chart(
    items: Sequence[tuple[str, Decimal | float, Decimal | float]],
    *,
    value_fmt: Callable[[Decimal], str] = compact_number,
    width: int = 680,
    aria_label: str = "Analyse de sensibilité",
    low_label: str = "hypothèse basse",
    high_label: str = "hypothèse haute",
) -> str:
    """Graphique « tornade » : influence des hypothèses sur l'écart de coût.

    ``items`` : (libellé, effet à la baisse, effet à la hausse) en dirhams,
    écarts signés par rapport au scénario de base.
    """
    if not items:
        return ""
    row_height = 34
    height = len(items) * row_height + 46
    center_x = width / 2
    half = width / 2 - 130
    max_abs = max([abs(to_decimal(low) or Decimal("0")) for _, low, _ in items] +
                  [abs(to_decimal(high) or Decimal("0")) for _, _, high in items] + [Decimal("1")])

    def scale(value: Decimal) -> float:
        return float(value / max_abs) * half

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;height:auto" '
        f'role="img" aria-label="{html.escape(aria_label)}" class="chart">'
    ]
    parts.append(
        f'<line x1="{center_x:.1f}" y1="8" x2="{center_x:.1f}" y2="{height - 34:.1f}" '
        f'stroke="{AXIS}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{center_x + 6:.1f}" y="{height - 18:.1f}" font-size="10.5" fill="{MUTED}">écart de coût : '
        f"0 = scénario de base</text>"
    )
    for index, (label, low, high) in enumerate(items):
        y = 14 + index * row_height
        low_value = to_decimal(low) or Decimal("0")
        high_value = to_decimal(high) or Decimal("0")
        low_len = scale(low_value)
        high_len = scale(high_value)
        text = label if len(label) <= 26 else label[:25] + "…"
        parts.append(
            f'<text x="{center_x - half - 16:.1f}" y="{y + 15}" text-anchor="end" font-size="11.5" '
            f'fill="{TEXT}">{html.escape(text)}</text>'
        )
        for value, length, color, direction in (
            (low_value, low_len, "#172B4D", "négatif"),
            (high_value, high_len, "#F4B942", "positif"),
        ):
            if length == 0:
                continue
            x = center_x if length > 0 else center_x + length
            parts.append(
                f'<rect x="{x:.1f}" y="{y + 4}" width="{abs(length):.1f}" height="16" rx="3" fill="{color}">'
                f"<title>{html.escape(text)} — {direction} : {html.escape(value_fmt(value))}</title></rect>"
            )
        label_x = center_x + max(high_len, 0) + 8 if high_len > 0 else center_x + 8
        if low_len < 0:
            label_x = max(label_x, center_x + 8)
        parts.append(
            f'<text x="{min(label_x, width - 8):.1f}" y="{y + 16}" font-size="10.5" fill="{MUTED}">'
            f"{html.escape(value_fmt(high_value))} / {html.escape(value_fmt(low_value))}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)
