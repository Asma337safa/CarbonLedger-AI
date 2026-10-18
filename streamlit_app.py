"""CarbonLedger AI — vitrine Streamlit (lecture seule).

Démonstration du produit pour Streamlit Community Cloud : tableau de bord,
dépenses, comptabilité carbone, **comparateur de décisions** (cœur du produit)
et simulations de scénarios.

Principe : **aucun chiffre n'est recalculé à la main ici**. L'application
réutilise le moteur de calcul de l'application complète (dossier ``app/`` :
``app.calc`` et ``app.services``) appliqué à la base de démonstration embarquée
``streamlit_demo.db`` (25 dépenses, 18 enregistrements carbone, 3 projets).

Lancement local : ``streamlit run streamlit_app.py``
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calc.dashboard import (  # noqa: E402
    category_breakdown,
    emissions_breakdown,
    resolve_period,
    summarize_expenses,
)
from app.calc.decision import ZERO, OptionInput  # noqa: E402
from app.calc.formatting import fmt_date, fmt_money, fmt_number, fmt_tco2e  # noqa: E402
from app.enums import (  # noqa: E402
    CARBON_STATUSES,
    EMISSION_METHODS,
    EXPENSE_CATEGORIES,
    PRIORITIES,
    SCOPES,
    VERIFICATION_STATUSES,
)
from app.errors import ValidationError  # noqa: E402
from app.models import CarbonRecord, DecisionProject, Expense  # noqa: E402
from app.services.compute import analyze, key_figures  # noqa: E402
from app.services.project_service import analyze_project  # noqa: E402

DEMO_DB = ROOT / "streamlit_demo.db"
GITHUB_URL = "https://github.com/Asma337safa/CarbonLedger-AI"
PAGES = [
    "Tableau de bord",
    "Dépenses",
    "Comptabilité carbone",
    "Comparateur de décisions",
    "Simulations",
    "À propos",
]

st.set_page_config(
    page_title="CarbonLedger AI — démo",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Accès aux données (lecture seule)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_engine():
    """Base de démonstration embarquée, ou base réelle via les secrets Streamlit."""
    url = ""
    try:
        url = st.secrets.get("CARBONLEDGER_DATABASE_URL", "") or ""
    except Exception:  # pas de fichier de secrets : mode démonstration embarqué
        url = ""
    if url:
        from app.db import _normalize_url

        return create_engine(_normalize_url(url), pool_pre_ping=True)
    return create_engine(f"sqlite:///{DEMO_DB.as_posix()}")


@st.cache_data(show_spinner=False)
def load_overview(period_key: str) -> dict:
    """Agrégats dépenses + carbone de la période, calculés par le moteur CarbonLedger."""
    engine = get_engine()
    resolved = resolve_period(period_key, today=date.today())
    with Session(engine) as db:
        expenses = (
            db.execute(
                select(Expense)
                .where(
                    Expense.expense_date >= resolved.start,
                    Expense.expense_date <= resolved.end,
                )
                .order_by(Expense.expense_date.desc(), Expense.id.desc())
            )
            .scalars()
            .all()
        )
        records = (
            db.execute(
                select(CarbonRecord)
                .options(selectinload(CarbonRecord.emission_factor))
                .where(
                    CarbonRecord.period_start <= resolved.end,
                    CarbonRecord.period_end >= resolved.start,
                )
            )
            .scalars()
            .all()
        )
        project_count = len(db.execute(select(DecisionProject.id)).scalars().all())

    expense_summary = summarize_expenses(expenses)
    emission_summary, emission_rows = emissions_breakdown(records)
    spend_rows = category_breakdown(expenses)
    recent = [
        {
            "Date": fmt_date(expense.expense_date),
            "Fournisseur": expense.supplier or "—",
            "Catégorie": EXPENSE_CATEGORIES.get(expense.category, expense.category),
            "Montant HT": fmt_money(expense.amount_ht),
            "Statut": VERIFICATION_STATUSES.get(expense.verification_status, expense.verification_status),
        }
        for expense in expenses[:6]
    ]
    return {
        "period_label": resolved.label,
        "period_bounds": (
            "toutes les données enregistrées"
            if resolved.key == "tout"
            else f"{fmt_date(resolved.start)} → {fmt_date(resolved.end)}"
        ),
        "expense_summary": expense_summary,
        "emission_summary": emission_summary,
        "spend_rows": spend_rows,
        "emission_rows": emission_rows,
        "recent": recent,
        "project_count": project_count,
        "expenses_count": len(expenses),
        "records_count": len(records),
    }


@st.cache_data(show_spinner=False)
def load_expenses() -> pd.DataFrame:
    engine = get_engine()
    with Session(engine) as db:
        expenses = (
            db.execute(select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc()))
            .scalars()
            .all()
        )
    rows = [
        {
            "_date": expense.expense_date,
            "Date": fmt_date(expense.expense_date),
            "Fournisseur": expense.supplier or "—",
            "Catégorie": EXPENSE_CATEGORIES.get(expense.category, expense.category),
            "Description": expense.description or "",
            "Montant HT": fmt_money(expense.amount_ht),
            "TVA": fmt_money(expense.vat_amount),
            "Montant TTC": fmt_money(expense.amount_ttc),
            "Statut": VERIFICATION_STATUSES.get(expense.verification_status, expense.verification_status),
            "Facteur d'émission": "oui" if expense.emission_factor_id else "non",
            "_ht": expense.amount_ht or Decimal("0"),
        }
        for expense in expenses
    ]
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_carbon() -> dict:
    engine = get_engine()
    with Session(engine) as db:
        records = (
            db.execute(
                select(CarbonRecord)
                .options(selectinload(CarbonRecord.emission_factor))
                .order_by(CarbonRecord.period_start.desc(), CarbonRecord.id.desc())
            )
            .scalars()
            .all()
        )
    summary, category_rows = emissions_breakdown(records)
    by_scope: dict[str, Decimal] = {}
    by_status: dict[str, Decimal] = {}
    rows = []
    for record in records:
        factor = record.emission_factor
        scope = factor.scope if factor else ""
        by_scope[scope] = by_scope.get(scope, ZERO) + (record.kgco2e or ZERO)
        status = record.status or "calcule"
        by_status[status] = by_status.get(status, ZERO) + (record.kgco2e or ZERO)
        rows.append(
            {
                "Période": f"{fmt_date(record.period_start)} → {fmt_date(record.period_end)}",
                "Catégorie": EXPENSE_CATEGORIES.get(record.category, record.category),
                "Activité": f"{fmt_number(record.activity_quantity)} {record.activity_unit}",
                "Facteur": factor.label if factor else "—",
                "kg CO₂e": fmt_number(record.kgco2e, 1),
                "Méthode": EMISSION_METHODS.get(record.method, record.method),
                "Statut": CARBON_STATUSES.get(status, status),
                "Source": (factor.source_name if factor else "") or "—",
            }
        )
    return {
        "summary": summary,
        "category_rows": category_rows,
        "by_scope": by_scope,
        "by_status": by_status,
        "rows": rows,
        "count": len(records),
    }


@st.cache_data(show_spinner=False)
def load_projects() -> list[dict]:
    engine = get_engine()
    with Session(engine) as db:
        projects = (
            db.execute(
                select(DecisionProject)
                .options(selectinload(DecisionProject.options))
                .order_by(DecisionProject.id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": project.id,
                "title": project.title,
                "horizon": project.horizon_years,
                "option_count": len(project.options),
                "priority": project.priority,
                "carbon_price": str(project.internal_carbon_price),
                "is_demo": bool(project.is_demo),
            }
            for project in projects
        ]


@st.cache_data(show_spinner="Analyse du projet…")
def analyze_project_by_id(project_id: int, priority: str, with_scenarios: bool):
    """Analyse complète d'un projet : comparaison, arbitrage, sensibilité ou scénarios."""
    engine = get_engine()
    with Session(engine) as db:
        project = (
            db.execute(
                select(DecisionProject)
                .options(selectinload(DecisionProject.options))
                .where(DecisionProject.id == project_id)
            )
            .scalar_one()
        )
        return analyze_project(
            project,
            priority=priority,
            with_scenarios=with_scenarios,
            with_sensitivity=not with_scenarios,
            with_charts=True,
        )


# ---------------------------------------------------------------------------
# Petits blocs d'interface (style CarbonLedger)
# ---------------------------------------------------------------------------
def _kpi(column, title: str, value: str, subtitle: str = "") -> None:
    sub = f"<div style='color:#64748B;font-size:0.82rem'>{subtitle}</div>" if subtitle else ""
    column.markdown(
        f"<div style='color:#64748B;font-size:0.82rem'>{title}</div>"
        f"<div style='font-size:1.5rem;font-weight:700;color:#172B4D'>{value}</div>{sub}",
        unsafe_allow_html=True,
    )


def priority_selector(key: str, default: str = "equilibre") -> str:
    labels = list(PRIORITIES.values())
    label_by_code = {code: label for code, label in PRIORITIES.items()}
    chosen = st.radio(
        "Priorité de décision",
        labels,
        index=labels.index(label_by_code[default]),
        key=key,
    )
    return {label: code for label, code in zip(labels, PRIORITIES.keys())}[chosen]


def _svg(markup: str) -> None:
    if markup:
        st.markdown(markup, unsafe_allow_html=True)


def _delta_money(value, is_base: bool) -> str:
    if is_base or value is None:
        return "—"
    return fmt_money(value, sign=True)


def _delta_t(value, is_base: bool) -> str:
    if is_base or value is None:
        return "—"
    return f"{fmt_number(value, 2)} t"


def render_analysis(analysis) -> None:
    """Affichage commun d'une analyse : chiffres clés, tableau, arbitrage, graphiques."""
    comparison = analysis.comparison
    arbitration = analysis.arbitration
    figures = key_figures(analysis)

    cols = st.columns(4)
    _kpi(
        cols[0],
        "Coût total le plus faible",
        fmt_money(figures["cheapest_cost"]) if figures["cheapest_cost"] else "—",
        f"« {figures['cheapest_name']} »" if figures["cheapest_name"] else "",
    )
    _kpi(
        cols[1],
        "Émissions cumulées les plus faibles",
        fmt_tco2e(figures["greenest_emissions_t"]) if figures["greenest_emissions_t"] else "non renseignées",
        f"« {figures['greenest_name']} »" if figures["greenest_name"] else "",
    )
    if figures["cost_per_tonne_avoided"] is not None:
        suffix = "économisés (gain double)" if figures["double_gain"] else "de surcoût"
        subtitle = f"{fmt_tco2e(figures['avoided_t'])} évitées" if figures["avoided_t"] else ""
        _kpi(
            cols[2],
            "Coût par tonne évitée",
            f"{fmt_money(abs(Decimal(figures['cost_per_tonne_avoided'])))} /t",
            f"{suffix} · {subtitle}" if subtitle else suffix,
        )
    else:
        _kpi(cols[2], "Coût par tonne évitée", "non disponible", "émissions manquantes")
    if figures["break_even_years"]:
        _kpi(
            cols[3],
            "Délai de rattrapage",
            f"≈ {fmt_number(figures['break_even_years'], 1)} ans",
            "surcoût initial compensé par les coûts annuels",
        )
    else:
        _kpi(cols[3], "Horizon de comparaison", f"{comparison.horizon_years} ans", "")

    st.caption(f"Règle de calcul — {analysis.formula}")

    table = pd.DataFrame(
        [
            {
                "Option": result.name,
                "Mise de fonds": fmt_money(result.initial_outlay),
                f"Coût total ({comparison.horizon_years} ans)": fmt_money(result.total_cost),
                "Émissions cumulées": fmt_tco2e(result.total_emissions_t)
                if result.total_emissions_t is not None
                else "non renseignées",
                "Économies déclarées": fmt_money(result.total_savings),
            }
            for result in comparison.results
        ]
    )
    st.dataframe(table)

    left, right = st.columns(2)
    with left:
        st.markdown("**Coût total et mise de fonds par option**")
        _svg(analysis.charts.get("cost_totals", ""))
        st.markdown("**Coûts cumulés année par année**")
        _svg(analysis.charts.get("cost_curve", ""))
    with right:
        st.markdown("**Émissions cumulées par option**")
        _svg(analysis.charts.get("emissions_totals", ""))
        st.markdown("**Émissions cumulées année par année**")
        _svg(analysis.charts.get("emissions_curve", ""))

    st.markdown(f"### {arbitration.recommendation_title}")
    for paragraph in arbitration.recommendation_paragraphs:
        st.markdown(paragraph)
    st.caption(arbitration.method_note)

    with st.expander("Évaluation détaillée par option"):
        for assessment in arbitration.ranking:
            st.markdown(f"**{assessment.rank}. {assessment.name}**")
            for advantage in assessment.advantages:
                st.markdown(f"- ✅ {advantage}")
            for drawback in assessment.disadvantages:
                st.markdown(f"- ⚠️ {drawback}")
            for fact in assessment.facts:
                st.markdown(f"- {fact}")

    if analysis.sensitivity_lines:
        with st.expander("Sensibilité aux hypothèses (± 10 %, une à la fois)"):
            for line in analysis.sensitivity_lines:
                st.markdown(f"- {line}")

    if arbitration.caveats:
        with st.expander("Limites et avertissements"):
            for caveat in arbitration.caveats:
                st.markdown(f"- {caveat}")

    for check in analysis.missing_data:
        if check["level"] == "attention":
            st.warning(check["message"])
        else:
            st.info(check["message"])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_dashboard() -> None:
    st.title("Tableau de bord")
    period_label = st.radio(
        "Période analysée",
        ["Année en cours", "Tout l'historique"],
        horizontal=True,
        key="dash_period",
    )
    data = load_overview("annee" if period_label.startswith("Année") else "tout")
    expense_summary = data["expense_summary"]
    emission_summary = data["emission_summary"]

    st.caption(f"{data['period_label']} — {data['period_bounds']}")

    cols = st.columns(4)
    _kpi(cols[0], "Dépenses HT", fmt_money(expense_summary.total_ht), f"{data['expenses_count']} ligne(s)")
    _kpi(cols[1], "TVA", fmt_money(expense_summary.total_vat), f"TTC : {fmt_money(expense_summary.total_ttc)}")
    _kpi(
        cols[2],
        "Émissions",
        fmt_tco2e(emission_summary.total_t),
        f"{data['records_count']} enregistrement(s) · estimé : {fmt_number(emission_summary.estimated_share_pct, 1)} %",
    )
    _kpi(cols[3], "Projets de décision", str(data["project_count"]), "comparateur disponible")

    qual = st.columns(3)
    _kpi(qual[0], "Dépenses à vérifier", str(expense_summary.unverified_count), f"part vérifiée : {fmt_number(expense_summary.verified_share_pct, 1)} %")
    _kpi(
        qual[1],
        "Lignes sans facteur d'émission",
        str(expense_summary.without_factor_count),
        f"{fmt_money(expense_summary.without_factor_amount)} non estimés",
    )
    scope_parts = [
        f"Scope {scope} : {fmt_tco2e(emission_summary.by_scope[scope] / 1000)}"
        for scope in ("1", "2", "3")
        if scope in emission_summary.by_scope
    ]
    _kpi(qual[2], "Répartition par scope", " · ".join(scope_parts) if scope_parts else "—", "")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("**Dépenses par catégorie (HT)**")
        if data["spend_rows"]:
            chart = pd.DataFrame(
                {
                    "Catégorie": [row["label"] for row in data["spend_rows"]],
                    "DH": [float(row["ht"]) for row in data["spend_rows"]],
                }
            ).set_index("Catégorie")
            st.bar_chart(chart)
        else:
            st.info("Aucune dépense sur la période.")
    with right:
        st.markdown("**Émissions par catégorie (kg CO₂e)**")
        if data["emission_rows"]:
            chart = pd.DataFrame(
                {
                    "Catégorie": [row["label"] for row in data["emission_rows"]],
                    "kg CO₂e": [float(row["kg"]) for row in data["emission_rows"]],
                }
            ).set_index("Catégorie")
            st.bar_chart(chart)
        else:
            st.info("Aucun enregistrement carbone sur la période.")

    st.markdown("**Derniers enregistrements**")
    st.dataframe(pd.DataFrame(data["recent"]))


def page_expenses() -> None:
    st.title("Dépenses")
    frame = load_expenses()
    period_label = st.radio(
        "Période",
        ["Année en cours", "Tout l'historique"],
        horizontal=True,
        key="dep_period",
    )
    resolved = resolve_period("annee" if period_label.startswith("Année") else "tout", today=date.today())
    subset = frame[(frame["_date"] >= resolved.start) & (frame["_date"] <= resolved.end)]

    filter_cols = st.columns([2, 2, 3])
    categories = sorted(subset["Catégorie"].unique().tolist())
    chosen_categories = filter_cols[0].multiselect("Catégorie", categories)
    chosen_status = filter_cols[1].selectbox("Statut", ["Tous"] + list(VERIFICATION_STATUSES.values()))
    search = filter_cols[2].text_input("Recherche (fournisseur, description)")

    if chosen_categories:
        subset = subset[subset["Catégorie"].isin(chosen_categories)]
    if chosen_status != "Tous":
        subset = subset[subset["Statut"] == chosen_status]
    if search.strip():
        needle = search.strip().lower()
        mask = subset["Fournisseur"].str.lower().str.contains(needle, regex=False) | subset[
            "Description"
        ].str.lower().str.contains(needle, regex=False)
        subset = subset[mask]

    totals = st.columns(2)
    _kpi(totals[0], "Lignes affichées", str(len(subset)), f"sur {len(frame)} au total")
    _kpi(totals[1], "Total HT (sélection)", fmt_money(subset["_ht"].sum() if len(subset) else Decimal("0")))

    st.dataframe(
        subset[
            [
                "Date",
                "Fournisseur",
                "Catégorie",
                "Description",
                "Montant HT",
                "TVA",
                "Montant TTC",
                "Statut",
                "Facteur d'émission",
            ]
        ]
    )
    st.caption(
        "La colonne « Facteur d'émission » indique si une estimation carbone documentée est rattachée "
        "à la ligne (aucun facteur n'est attribué automatiquement)."
    )


def page_carbon() -> None:
    st.title("Comptabilité carbone")
    data = load_carbon()
    summary = data["summary"]

    cols = st.columns(4)
    _kpi(cols[0], "Émissions totales", fmt_tco2e(summary.total_t), f"{data['count']} enregistrement(s)")
    _kpi(
        cols[1],
        "Mesuré",
        fmt_tco2e(summary.measured_kg / 1000),
        f"{summary.measured_count} enregistrement(s)",
    )
    _kpi(cols[2], "Calculé (facteurs documentés)", fmt_tco2e(summary.calculated_kg / 1000), "")
    _kpi(
        cols[3],
        "Estimé",
        fmt_tco2e(summary.estimated_kg / 1000),
        f"{fmt_number(summary.estimated_share_pct, 1)} % du total",
    )

    scope_cols = st.columns(3)
    for index, scope in enumerate(("1", "2", "3")):
        total_kg = data["by_scope"].get(scope, ZERO) / 1000
        _kpi(scope_cols[index], SCOPES[scope], fmt_tco2e(total_kg))

    st.divider()
    st.markdown("**Émissions par catégorie (kg CO₂e)**")
    if data["category_rows"]:
        chart = pd.DataFrame(
            {
                "Catégorie": [row["label"] for row in data["category_rows"]],
                "kg CO₂e": [float(row["kg"]) for row in data["category_rows"]],
            }
        ).set_index("Catégorie")
        st.bar_chart(chart)
    else:
        st.info("Aucun enregistrement.")

    st.markdown("**Registre des activités**")
    st.dataframe(pd.DataFrame(data["rows"]))
    st.caption(
        "Formule : émissions = quantité d'activité × facteur d'émission documenté. "
        "Les facteurs indicatifs doivent être remplacés par vos valeurs documentées avant tout usage contractuel."
    )


def page_comparator() -> None:
    st.title("Comparateur de décisions")
    st.caption(
        "Le cœur du produit : coût complet et émissions cumulées sur un horizon commun, "
        "frontière de compromis et arbitrage expliqué — sans jamais inventer de chiffre."
    )
    projects = load_projects()
    tab_demo, tab_calc = st.tabs(["Projets de démonstration", "Calculateur libre"])

    with tab_demo:
        if not projects:
            st.info("Aucun projet dans la base de démonstration.")
        else:
            titles = [
                f"{project['title']} — {project['option_count']} options, horizon {project['horizon']} ans"
                for project in projects
            ]
            chosen = st.selectbox("Projet", titles, index=0)
            project = projects[titles.index(chosen)]
            priority = priority_selector("priority_demo", default=project["priority"] or "equilibre")
            try:
                analysis = analyze_project_by_id(project["id"], priority, False)
            except ValidationError as error:
                st.error(str(error))
            else:
                render_analysis(analysis)

    with tab_calc:
        st.caption(
            "Comparez librement deux options. Les valeurs par défaut reproduisent l'exemple du cahier "
            "des charges : 200 000 DH contre 180 000 DH sur 5 ans, 25 t CO₂e évitées, −800 DH par tonne évitée."
        )
        horizon = st.slider("Horizon de comparaison (années)", 1, 30, 5)
        carbon_price = st.number_input(
            "Prix interne du carbone (DH / t CO₂e — 0 = non appliqué)",
            min_value=0.0,
            max_value=2000.0,
            value=0.0,
            step=50.0,
        )
        priority = priority_selector("priority_calc")

        column_a, column_b = st.columns(2)
        with column_a:
            st.markdown("**Option A**")
            name_a = st.text_input("Nom (A)", "Option A — rénover la presse")
            purchase_a = st.number_input("Acquisition (DH) (A)", min_value=0.0, value=80000.0, step=1000.0)
            transport_a = st.number_input("Transport (DH) (A)", min_value=0.0, value=0.0, step=500.0)
            opex_a = st.number_input("Fonctionnement annuel (DH) (A)", min_value=0.0, value=24000.0, step=1000.0)
            maintenance_a = st.number_input("Maintenance annuelle (DH) (A)", min_value=0.0, value=0.0, step=500.0)
            savings_a = st.number_input("Économies annuelles déclarées (DH) (A)", min_value=0.0, value=0.0, step=500.0)
            emissions_a = st.number_input("Émissions annuelles (kg CO₂e) (A)", min_value=0.0, value=12000.0, step=100.0)
        with column_b:
            st.markdown("**Option B**")
            name_b = st.text_input("Nom (B)", "Option B — remplacer la presse")
            purchase_b = st.number_input("Acquisition (DH) (B)", min_value=0.0, value=95000.0, step=1000.0)
            transport_b = st.number_input("Transport (DH) (B)", min_value=0.0, value=0.0, step=500.0)
            opex_b = st.number_input("Fonctionnement annuel (DH) (B)", min_value=0.0, value=17000.0, step=1000.0)
            maintenance_b = st.number_input("Maintenance annuelle (DH) (B)", min_value=0.0, value=0.0, step=500.0)
            savings_b = st.number_input("Économies annuelles déclarées (DH) (B)", min_value=0.0, value=0.0, step=500.0)
            emissions_b = st.number_input("Émissions annuelles (kg CO₂e) (B)", min_value=0.0, value=7000.0, step=100.0)

        options = [
            OptionInput.from_dict(
                {
                    "name": name_a or "Option A",
                    "purchase_cost": str(purchase_a),
                    "transport_cost": str(transport_a),
                    "annual_opex": str(opex_a),
                    "annual_maintenance": str(maintenance_a),
                    "annual_savings": str(savings_a),
                    "annual_emissions_kg": str(emissions_a),
                    "confidence": "haute",
                },
                key="a",
            ),
            OptionInput.from_dict(
                {
                    "name": name_b or "Option B",
                    "purchase_cost": str(purchase_b),
                    "transport_cost": str(transport_b),
                    "annual_opex": str(opex_b),
                    "annual_maintenance": str(maintenance_b),
                    "annual_savings": str(savings_b),
                    "annual_emissions_kg": str(emissions_b),
                    "confidence": "haute",
                },
                key="b",
            ),
        ]
        try:
            analysis = analyze(
                options,
                horizon,
                priority=priority,
                carbon_price=str(carbon_price),
                with_scenarios=False,
                with_sensitivity=False,
                with_charts=True,
            )
        except ValidationError as error:
            st.error(str(error))
        else:
            render_analysis(analysis)


def page_simulations() -> None:
    st.title("Simulations")
    st.caption(
        "Scénarios prédéfinis (base, optimiste, défavorable) sur un projet de démonstration : "
        "mêmes moteurs que le comparateur, en lecture seule, aucun chiffre modifié en base."
    )
    projects = load_projects()
    if not projects:
        st.info("Aucun projet dans la base de démonstration.")
        return
    titles = [f"{project['title']} — horizon {project['horizon']} ans" for project in projects]
    chosen = st.selectbox("Projet", titles, key="sim_project")
    project = projects[titles.index(chosen)]
    try:
        analysis = analyze_project_by_id(project["id"], "equilibre", True)
    except ValidationError as error:
        st.error(str(error))
        return

    for outcome in analysis.scenarios:
        is_base = outcome.kind == "base"
        with st.expander(outcome.label, expanded=is_base):
            st.markdown(outcome.description)
            rows = [
                {
                    "Option": result.name,
                    "Coût total": fmt_money(result.total_cost),
                    "Δ vs base": _delta_money(outcome.cost_deltas.get(result.key), is_base),
                    "Émissions cumulées": fmt_tco2e(result.total_emissions_t)
                    if result.total_emissions_t is not None
                    else "non renseignées",
                    "Δ émissions": _delta_t(outcome.emissions_deltas.get(result.key), is_base),
                }
                for result in outcome.comparison.results
            ]
            st.dataframe(pd.DataFrame(rows))
            for line in outcome.summary_lines:
                st.markdown(f"- {line}")


def page_about() -> None:
    st.title("À propos de cette démonstration")
    st.markdown(
        """
**CarbonLedger AI** — plateforme de décision financière **et** carbone pour les PME marocaines
(devise : MAD). Cette vitrine **Streamlit** (lecture seule) montre le cœur du produit :

- **Tableau de bord** et **dépenses** : pilotage des coûts de la période ;
- **Comptabilité carbone** : registre d'activités `quantité × facteur documenté`, scopes 1/2/3,
  statut mesuré / calculé / estimé ;
- **Comparateur de décisions** : coût total, coût par tonne de CO₂e évitée, trésorerie année
  par année, frontière de compromis et **arbitrage expliqué** selon votre priorité ;
- **Simulations** : scénarios optimiste / défavorable pour tester la robustesse d'une décision.

Les chiffres proviennent du **même moteur de calcul** que l'application complète
(`app/calc`, `app/services`), appliqué au jeu de démonstration embarqué
(`streamlit_demo.db`) : 25 dépenses, 18 enregistrements carbone, 3 projets — dont
l'exemple du cahier des charges (200 000 DH / 180 000 DH, 25 t CO₂e évitées, −800 DH/t).
        """
    )
    st.markdown(
        f"**Application complète** (comptes et rôles, import CSV/Excel, rapports PDF/Excel, "
        f"copilot, journal d'audit) : [dépôt GitHub]({GITHUB_URL}) — déployable en FastAPI + PostgreSQL "
        "(voir `DEPLOYMENT.md`)."
    )
    st.markdown(
        "**Limites de cette vitrine** : lecture seule, sans authentification ni écriture en base — "
        "c'est une démonstration de la couche de calcul et de décision."
    )
    st.markdown(
        "**Rigueur** : facteurs d'émission indicatifs et documentés (à remplacer par vos valeurs avant "
        "usage contractuel) ; aucune donnée absente n'est remplacée par une estimation silencieuse."
    )


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
def main() -> None:
    st.sidebar.markdown(
        "<div style='font-size:1.15rem;font-weight:700;color:#176B4D'>CarbonLedger AI</div>"
        "<div style='color:#64748B;font-size:0.82rem'>Démonstration — décision coûts &amp; carbone "
        "pour PME marocaines</div>",
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio("Navigation", PAGES, key="nav")
    st.sidebar.divider()
    st.sidebar.caption("Données de démonstration · montants en MAD (DH) · lecture seule")

    pages = {
        "Tableau de bord": page_dashboard,
        "Dépenses": page_expenses,
        "Comptabilité carbone": page_carbon,
        "Comparateur de décisions": page_comparator,
        "Simulations": page_simulations,
        "À propos": page_about,
    }
    pages[page]()


main()
