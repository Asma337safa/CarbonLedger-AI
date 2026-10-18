"""Génération des rapports PDF (reportlab).

Les rapports sont présentés comme des **rapports de gestion internes** :
ils reprennent les chiffres affichés dans l'application, rappellent les
hypothèses, les sources et les limites des données. Ils ne constituent pas
un document de conformité réglementaire.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..calc.arbitration import ArbitrationResult
from ..calc.decision import ComparisonResult
from ..calc.formatting import fmt_date_long, fmt_money, fmt_number, fmt_tco2e
from .compute import ProjectAnalysis

BRAND = colors.HexColor("#176B4D")
BRAND_LIGHT = colors.HexColor("#DDF3E4")
NAVY = colors.HexColor("#172B4D")
SLATE = colors.HexColor("#64748B")
BORDER = colors.HexColor("#E2E8F0")
AMBER = colors.HexColor("#F4B942")
PAPER = colors.HexColor("#F8FAF9")
CHART_COLORS = ["#176B4D", "#172B4D", "#64748B", "#F4B942", "#0E7490", "#7C3AED"]

_REPLACEMENTS = {
    "\u202f": " ",
    "\u00a0": " ",
    "₂": "2",
    "−": "-",
    "→": "->",
    "≈": "~",
    "≤": "<=",
    "≥": ">=",
}


def _t(text: Any) -> str:
    """Texte compatible WinAnsi pour les polices standard de reportlab."""
    value = "" if text is None else str(text)
    for source, target in _REPLACEMENTS.items():
        value = value.replace(source, target)
    return value


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("cl_title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, textColor=NAVY, alignment=0, spaceAfter=2),
        "subtitle": ParagraphStyle("cl_subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=10.5, textColor=SLATE, spaceAfter=10),
        "h2": ParagraphStyle("cl_h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=BRAND, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("cl_body", parent=base["BodyText"], fontName="Helvetica", fontSize=10, textColor=NAVY, leading=14.5),
        "small": ParagraphStyle("cl_small", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, textColor=SLATE, leading=12),
        "bullet": ParagraphStyle("cl_bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=10, textColor=NAVY, leading=14, leftIndent=10, bulletIndent=0),
    }


def _kpi_strip(items: Sequence[tuple[str, str]], width: float = 170 * mm) -> Table:
    cells = []
    for label, value in items:
        cells.append(Paragraph(f'<font size="8" color="#64748B">{_t(label)}</font><br/><font size="12" color="#172B4D"><b>{_t(value)}</b></font>', _styles()["body"]))
    table = Table([cells], colWidths=[width / len(items)] * len(items))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _data_table(header: Sequence[str], rows: Sequence[Sequence[Any]], col_widths: Sequence[float] | None = None) -> Table:
    data = [[Paragraph(f"<b>{_t(cell)}</b>", _styles()["small"]) for cell in header]]
    for row in rows:
        data.append([Paragraph(_t(cell), _styles()["small"]) for cell in row])
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
    ]))
    return table


def _line_chart(
    x_labels: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[float]]],
    *,
    width: float = 170 * mm,
    height: float = 130,
    value_fmt,
) -> Drawing:
    drawing = Drawing(width, height)
    pad_left, pad_right, pad_top, pad_bottom = 46, 10, 10, 24
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    all_values = [value for _, _, values in series for value in values] or [1]
    y_max = max(all_values)
    if y_max <= 0:
        y_max = 1

    drawing.add(Rect(0, 0, width, height, fillColor=colors.white, strokeColor=None))
    for index in range(5):
        value = y_max * index / 4
        y = pad_top + plot_height * index / 4
        drawing.add(Line(pad_left, y, width - pad_right, y, strokeColor=BORDER, strokeWidth=0.5))
        drawing.add(String(4, y - 3, _t(value_fmt(value)), fontSize=7, fillColor=SLATE))

    def px(i: int) -> float:
        if len(x_labels) == 1:
            return pad_left + plot_width / 2
        return pad_left + plot_width * i / (len(x_labels) - 1)

    def py(value: float) -> float:
        return pad_top + plot_height * (value / y_max if y_max else 0)

    for name, color_hex, values in series:
        points = [(px(i), py(value)) for i, value in enumerate(values)]
        flat: list[float] = []
        for x, y in points:
            flat.extend([x, y])
        drawing.add(PolyLine(flat, strokeColor=colors.HexColor(color_hex), strokeWidth=1.6))
        drawing.add(String(pad_left, height - 8, _t(name), fontSize=7.5, fillColor=colors.HexColor(color_hex)))

    step = max(1, len(x_labels) // 8)
    for index, label in enumerate(x_labels):
        if index % step and index != len(x_labels) - 1:
            continue
        drawing.add(String(px(index) - 10, 8, _t(label), fontSize=7, fillColor=SLATE))
    return drawing


def _grouped_bars(
    categories: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[float]]],
    *,
    width: float = 170 * mm,
    height: float = 120,
    value_fmt,
) -> Drawing:
    drawing = Drawing(width, height)
    pad_left, pad_right, pad_top, pad_bottom = 46, 10, 14, 22
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    all_values = [value for _, _, values in series for value in values] or [1]
    y_max = max(all_values) or 1
    drawing.add(Rect(0, 0, width, height, fillColor=colors.white, strokeColor=None))
    for index in range(5):
        value = y_max * index / 4
        y = pad_top + plot_height * index / 4
        drawing.add(Line(pad_left, y, width - pad_right, y, strokeColor=BORDER, strokeWidth=0.5))
        drawing.add(String(4, y - 3, _t(value_fmt(value)), fontSize=7, fillColor=SLATE))

    group_width = plot_width / max(1, len(categories))
    bar_width = min(26.0, group_width * 0.6 / max(1, len(series)))
    for cat_index, category in enumerate(categories):
        group_x = pad_left + cat_index * group_width
        start_x = group_x + (group_width - bar_width * len(series)) / 2
        for ser_index, (name, color_hex, values) in enumerate(series):
            value = values[cat_index] if cat_index < len(values) else 0
            bar_height = plot_height * (value / y_max if y_max else 0)
            x = start_x + ser_index * bar_width
            drawing.add(Rect(x, pad_top, bar_width - 3, bar_height, fillColor=colors.HexColor(color_hex), strokeColor=None))
        drawing.add(String(group_x + group_width / 2 - len(category) * 2.4, 8, _t(category), fontSize=7, fillColor=SLATE))
    legend_x = pad_left
    for name, color_hex, _ in series:
        drawing.add(Rect(legend_x, height - 10, 7, 7, fillColor=colors.HexColor(legend_color := color_hex), strokeColor=None))
        drawing.add(String(legend_x + 10, height - 9, _t(name), fontSize=7, fillColor=SLATE))
        legend_x += 16 + len(name) * 3.6
    return drawing


def _header_footer(organization_name: str, document_title: str):
    def draw(canvas, doc):  # pragma: no cover - rendu PDF
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - 10 * mm, A4[0], 10 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(SLATE)
        canvas.drawString(20 * mm, A4[1] - 14 * mm, _t(f"CarbonLedger AI — Rapport de gestion interne — {document_title}"))
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 14 * mm, _t(organization_name))
        canvas.drawString(20 * mm, 10 * mm, _t("Document interne d'aide à la décision — ne constitue pas un rapport de conformité réglementaire certifié."))
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def generate_decision_pdf(
    path: Path,
    *,
    organization_name: str,
    project_title: str,
    project_category: str,
    horizon_years: int,
    priority_label: str,
    carbon_price: Decimal,
    analysis: ProjectAnalysis,
    author_name: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Rapport PDF d'une décision comparée. Retourne l'instantané des chiffres clés."""
    comparison: ComparisonResult = analysis.comparison
    arbitration: ArbitrationResult = analysis.arbitration
    styles = _styles()
    story: list[Any] = []
    today = date.today()

    story.append(Paragraph(_t("Rapport de comparaison de décision"), styles["title"]))
    story.append(Paragraph(
        _t(f"{project_title} — {organization_name} — généré le {fmt_date_long(today)} par {author_name}"),
        styles["subtitle"],
    ))

    story.append(_kpi_strip([
        ("Période commune", f"{horizon_years} ans"),
        ("Options comparées", str(len(comparison.results))),
        ("Priorité retenue", priority_label),
        ("Prix interne du carbone", f"{fmt_money(carbon_price, decimals=0)}/tCO2e" if carbon_price else "non défini"),
    ]))

    # 1. Résumé exécutif
    story.append(Paragraph("1. Résumé exécutif", styles["h2"]))
    story.append(Paragraph(_t(arbitration.recommendation_title), styles["body"]))
    for paragraph in arbitration.recommendation_paragraphs:
        story.append(Paragraph(_t(paragraph), styles["body"]))
        story.append(Spacer(1, 3))

    # 2. Hypothèses
    story.append(Paragraph("2. Hypothèses et méthode", styles["h2"]))
    story.append(Paragraph(
        _t(
            f"Comparaison sur {horizon_years} ans, période commune à toutes les options. "
            f"Catégorie du projet : {project_category}. "
            + ("Actualisation activée selon le taux saisi." if analysis.params.discount_rate_pct else "Résultats hors actualisation (taux nul).")
        ),
        styles["body"],
    ))
    story.append(Paragraph(_t(arbitration.method_note), styles["small"]))
    for option in comparison.results:
        for assumption in option.assumptions:
            story.append(Paragraph(_t(f"• {option.name} : {assumption}"), styles["small"]))
    story.append(Spacer(1, 6))

    # 3. Indicateurs financiers
    story.append(Paragraph("3. Indicateurs financiers", styles["h2"]))
    header = ["Option", "Mise de fonds initiale", "Coût total sur la période", "Économies cumulées", "Coût annuel moyen"]
    rows = []
    for result in comparison.results:
        annual_avg = (result.total_cost - result.initial_outlay) / max(1, result.horizon_years)
        rows.append([
            result.name,
            fmt_money(result.initial_outlay),
            fmt_money(result.total_cost),
            fmt_money(result.total_savings),
            fmt_money(annual_avg),
        ])
    story.append(_data_table(header, rows, col_widths=[46 * mm, 32 * mm, 32 * mm, 30 * mm, 30 * mm]))

    # 4. Indicateurs carbone
    story.append(Paragraph("4. Indicateurs carbone", styles["h2"]))
    header = ["Option", "Émissions annuelles", "Émissions cumulées", "Base", "Confiance", "Source / note"]
    rows = []
    for result in comparison.results:
        rows.append([
            result.name,
            fmt_tco2e(result.annual_emissions_t) if result.annual_emissions_t is not None else "non renseignées",
            fmt_tco2e(result.total_emissions_t) if result.total_emissions_t is not None else "indisponibles",
            result.option.emissions_basis or "—",
            result.option.confidence,
            result.option.emissions_source_note or "—",
        ])
    story.append(_data_table(header, rows, col_widths=[40 * mm, 26 * mm, 26 * mm, 18 * mm, 20 * mm, 40 * mm]))

    if comparison.pairs:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Comparaisons deux à deux", styles["h3"] if "h3" in styles else styles["h2"]))
        rows = []
        for pair in comparison.pairs:
            rows.append([
                f"{pair.a_name} vs {pair.b_name}",
                fmt_money(pair.cost_delta),
                fmt_number(pair.emissions_delta_t, 2) if pair.emissions_delta_t is not None else "—",
                fmt_money(pair.cost_per_tonne_avoided) if pair.cost_per_tonne_avoided is not None else "non pertinent",
            ])
        story.append(_data_table(
            ["Comparaison", "Écart de coût (A−B)", "Écart d'émissions (t CO2e)", "Coût / tonne évitée"],
            rows,
            col_widths=[62 * mm, 32 * mm, 38 * mm, 38 * mm],
        ))
        story.append(Spacer(1, 4))
        for pair in comparison.pairs:
            for part in pair.interpretation_parts:
                story.append(Paragraph(_t(f"• {part}"), styles["small"]))

    # 5. Graphiques
    story.append(PageBreak())
    story.append(Paragraph("5. Graphiques", styles["h2"]))
    year_labels = [f"Annee {index}" for index in range(comparison.horizon_years + 1)]
    cost_series = [
        (result.name, CHART_COLORS[index % len(CHART_COLORS)], [float(value) for value in result.cost_curve])
        for index, result in enumerate(comparison.results)
    ]
    story.append(Paragraph("Coûts cumulés (DH)", styles["body"]))
    story.append(_line_chart(year_labels, cost_series, value_fmt=lambda v: fmt_money(v, decimals=0)))
    story.append(Spacer(1, 8))

    emissions_series = [
        (result.name, CHART_COLORS[index % len(CHART_COLORS)], [float(value) for value in result.emissions_curve_t])
        for index, result in enumerate(comparison.results)
        if result.emissions_curve_t is not None
    ]
    if emissions_series:
        story.append(Paragraph("Émissions cumulées (t CO2e)", styles["body"]))
        story.append(_line_chart(year_labels, emissions_series, value_fmt=lambda v: fmt_number(v, 1)))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Coût total et mise de fonds initiale (DH)", styles["body"]))
    story.append(_grouped_bars(
        [result.name for result in comparison.results],
        [
            ("Mise de fonds", "#172B4D", [float(result.initial_outlay) for result in comparison.results]),
            ("Coût total", "#176B4D", [float(result.total_cost) for result in comparison.results]),
        ],
        value_fmt=lambda v: fmt_money(v, decimals=0),
    ))

    # 6. Analyse de sensibilité
    if analysis.sensitivity:
        story.append(Paragraph("6. Sensibilité aux hypothèses", styles["h2"]))
        rows = [
            [
                item.label,
                f"{item.low_case} / {item.high_case}",
                fmt_money(item.cost_swing),
                fmt_number(item.emissions_swing, 2) if item.emissions_swing is not None else "—",
                "oui" if item.can_flip_ranking else "non",
            ]
            for item in analysis.sensitivity[:6]
        ]
        story.append(_data_table(
            ["Hypothèse", "Variation testée", "Effet max sur l'écart de coût", "Effet max sur l'écart carbone (t)", "Inverse le classement"],
            rows,
            col_widths=[40 * mm, 30 * mm, 36 * mm, 40 * mm, 24 * mm],
        ))
        for line in analysis.sensitivity_lines:
            story.append(Paragraph(_t(f"• {line}"), styles["small"]))

    # 7. Recommandation et limites
    story.append(Paragraph("7. Recommandation et limites", styles["h2"]))
    for assessment in arbitration.ranking:
        story.append(Paragraph(_t(f"<b>{assessment.name}</b> — avantages : " + (" ; ".join(assessment.advantages) or "aucun avantage chiffré identifié")), styles["small"]))
        if assessment.disadvantages:
            story.append(Paragraph(_t("Inconvénients / points de vigilance : " + " ; ".join(assessment.disadvantages)), styles["small"]))
        story.append(Spacer(1, 3))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Limites des données et sources</b>", styles["body"]))
    if analysis.missing_data:
        for check in analysis.missing_data:
            story.append(Paragraph(_t(f"• [{check['level']}] {check['message']} {check.get('hint', '')}"), styles["small"]))
    for note in arbitration.caveats:
        story.append(Paragraph(_t(f"• {note}"), styles["small"]))
    for note in (notes or []):
        story.append(Paragraph(_t(f"• {note}"), styles["small"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=_t(f"Rapport de décision — {project_title}"),
        author="CarbonLedger AI",
    )
    document.build(story, onFirstPage=_header_footer(organization_name, project_title), onLaterPages=_header_footer(organization_name, project_title))

    return {
        "options": [
            {
                "name": result.name,
                "total_cost": str(result.total_cost),
                "initial_outlay": str(result.initial_outlay),
                "total_emissions_t": str(result.total_emissions_t) if result.total_emissions_t is not None else None,
                "confidence": result.option.confidence,
            }
            for result in comparison.results
        ],
        "recommendation_title": arbitration.recommendation_title,
        "horizon_years": horizon_years,
        "priority": arbitration.priority,
        "carbon_price": str(carbon_price),
    }


def generate_period_pdf(
    path: Path,
    *,
    organization_name: str,
    period_label: str,
    expense_summary,
    category_rows: Sequence[dict[str, Any]],
    emission_summary,
    emission_rows: Sequence[dict[str, Any]],
    projects_rows: Sequence[dict[str, Any]],
    factor_sources: Sequence[str],
    notes: Sequence[str],
    author_name: str,
) -> dict[str, Any]:
    """Rapport PDF de gestion sur une période (dépenses + émissions)."""
    styles = _styles()
    story: list[Any] = []
    today = date.today()

    story.append(Paragraph(_t("Rapport de gestion — dépenses et émissions"), styles["title"]))
    story.append(Paragraph(
        _t(f"{organization_name} — {period_label} — généré le {fmt_date_long(today)} par {author_name}"),
        styles["subtitle"],
    ))

    story.append(_kpi_strip([
        ("Dépenses HT", fmt_money(expense_summary.total_ht, decimals=0)),
        ("TVA", fmt_money(expense_summary.total_vat, decimals=0)),
        ("Émissions estimées", fmt_tco2e(emission_summary.total_t)),
        ("Part estimée", f"{fmt_number(emission_summary.estimated_share_pct, 1)} %"),
    ]))

    story.append(Paragraph("1. Dépenses par catégorie", styles["h2"]))
    rows = [[row["label"], fmt_money(row["ht"]), f"{fmt_number(row['share_pct'], 1)} %", str(row["count"])] for row in category_rows]
    story.append(_data_table(["Catégorie", "Montant HT", "Part", "Lignes"], rows, col_widths=[70 * mm, 34 * mm, 24 * mm, 22 * mm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        _t(
            f"Total HT : {fmt_money(expense_summary.total_ht)} — Total TTC : {fmt_money(expense_summary.total_ttc)}. "
            f"{expense_summary.unverified_count} ligne(s) restent à vérifier ; "
            f"{expense_summary.without_factor_count} ligne(s) sans facteur d'émission "
            f"({fmt_money(expense_summary.without_factor_amount)} HT) : carbone non estimé pour celles-ci."
        ),
        styles["small"],
    ))

    story.append(Paragraph("2. Émissions par catégorie", styles["h2"]))
    if emission_rows:
        rows = [[row["label"], fmt_tco2e(row["kg"] / 1000), f"{fmt_number(row['share_pct'], 1)} %"] for row in emission_rows]
        story.append(_data_table(["Catégorie", "Émissions cumulées", "Part"], rows, col_widths=[80 * mm, 40 * mm, 30 * mm]))
    else:
        story.append(Paragraph("Aucun enregistrement carbone sur la période : importez des données ou liez des facteurs d'émission.", styles["body"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        _t(
            "Répartition par méthode : "
            f"mesuré {fmt_tco2e(emission_summary.measured_kg / 1000)}, "
            f"calculé {fmt_tco2e(emission_summary.calculated_kg / 1000)}, "
            f"estimé {fmt_tco2e(emission_summary.estimated_kg / 1000)} "
            f"(dont estimé à partir de montants : {fmt_tco2e(emission_summary.monetary_kg / 1000)}). "
            "Les estimations monétaires sont approximatives et signalées comme telles."
        ),
        styles["small"],
    ))

    if projects_rows:
        story.append(Paragraph("3. Décisions comparées", styles["h2"]))
        rows = [[row.get("title", ""), row.get("status", ""), row.get("summary", "")[:220]] for row in projects_rows]
        story.append(_data_table(["Projet", "Statut", "Synthèse"], rows, col_widths=[50 * mm, 22 * mm, 78 * mm]))

    story.append(Paragraph("4. Sources des facteurs d'émission utilisés", styles["h2"]))
    if factor_sources:
        for source in factor_sources[:20]:
            story.append(Paragraph(_t(f"• {source}"), styles["small"]))
    else:
        story.append(Paragraph("Aucun facteur d'émission utilisé sur la période.", styles["small"]))

    story.append(Paragraph("5. Limites", styles["h2"]))
    for note in notes:
        story.append(Paragraph(_t(f"• {note}"), styles["small"]))
    story.append(Paragraph(
        _t(
            "• Ce rapport est un document de gestion interne destiné au pilotage de l'entreprise. "
            "Il ne constitue pas un bilan d'émissions réglementaire certifié ni un document comptable officiel."
        ),
        styles["small"],
    ))

    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=_t(f"Rapport de gestion — {organization_name}"),
        author="CarbonLedger AI",
    )
    document.build(story, onFirstPage=_header_footer(organization_name, period_label), onLaterPages=_header_footer(organization_name, period_label))

    return {
        "total_ht": str(expense_summary.total_ht),
        "total_ttc": str(expense_summary.total_ttc),
        "total_emissions_kg": str(emission_summary.total_kg),
        "estimated_share_pct": str(emission_summary.estimated_share_pct),
        "period_label": period_label,
    }
