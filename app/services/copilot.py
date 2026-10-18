"""CarbonLedger Copilot — assistant optionnel.

Deux modes :
- **mode démonstration** (par défaut, sans clé API) : réponses déterministes
  construites uniquement à partir des données enregistrées par l'entreprise ;
- **mode IA** (si ``CARBONLEDGER_AI_API_KEY`` est configurée) : le modèle
  reçoit un contexte JSON calculé par l'application et des règles strictes
  (ne jamais inventer de chiffres, distinguer faits / estimations / recommandations,
  signaler les données manquantes).

Dans tous les cas, les calculs financiers et carbone sont réalisés par le
moteur déterministe de l'application — jamais par le modèle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.arbitration import arbitrate
from ..calc.dashboard import category_breakdown, emissions_breakdown, summarize_expenses, top_savings_opportunities
from ..calc.decision import compare_options
from ..calc.formatting import fmt_money, fmt_number, fmt_tco2e
from ..calc.sensitivity import sensitivity_analysis, sensitivity_summary
from ..config import settings
from ..enums import CARBON_CATEGORIES, EXPENSE_CATEGORIES, PRIORITIES
from ..models import CarbonRecord, DecisionProject, EmissionFactor, Expense, Organization
from .project_service import project_inputs

SUGGESTED_QUESTIONS = [
    "Quelle option est la plus économique sur la période comparée ?",
    "Quel est le principal facteur de mes émissions ?",
    "Quels paramètres influencent le plus cette comparaison ?",
    "Comment puis-je réduire mes coûts énergétiques ?",
    "Quelles informations me manquent pour comparer ces fournisseurs ?",
]


@dataclass
class CopilotAnswer:
    answer: str
    mode: str  # "ia" | "demonstration"
    data_used: list[str] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "mode": self.mode,
            "data_used": self.data_used,
            "disclaimers": self.disclaimers,
            "suggested_questions": self.suggested_questions,
            "error": self.error,
        }


def _q(value) -> Decimal:
    return Decimal(str(value or 0))


def organization_snapshot(db: OrmSession, organization: Organization, *, months: int = 12) -> dict[str, Any]:
    """Instantané des données réelles de l'organisation (utilisé par le Copilot)."""
    since = date.today() - timedelta(days=30 * months)
    expenses = (
        db.execute(
            select(Expense).where(Expense.organization_id == organization.id, Expense.expense_date >= since)
        )
        .scalars()
        .all()
    )
    records = (
        db.execute(
            select(CarbonRecord).where(
                CarbonRecord.organization_id == organization.id, CarbonRecord.period_start >= since
            )
        )
        .scalars()
        .all()
    )
    projects = (
        db.execute(
            select(DecisionProject)
            .where(DecisionProject.organization_id == organization.id)
            .order_by(DecisionProject.updated_at.desc())
        )
        .scalars()
        .all()
    )
    factors = (
        db.execute(
            select(EmissionFactor).where(
                (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == organization.id)
            )
        )
        .scalars()
        .all()
    )

    expense_summary = summarize_expenses(expenses)
    emission_summary, emission_rows = emissions_breakdown(records)
    category_rows = category_breakdown(expenses)

    suppliers: dict[str, dict[str, Any]] = {}
    for expense in expenses:
        bucket = suppliers.setdefault(expense.supplier or "(sans fournisseur)", {"ht": Decimal("0"), "kg": Decimal("0"), "count": 0})
        bucket["ht"] += _q(expense.amount_ht)
        bucket["count"] += 1
    for record in records:
        supplier = ""
        if record.expense is not None:
            supplier = record.expense.supplier or ""
        if supplier:
            suppliers.setdefault(supplier, {"ht": Decimal("0"), "kg": Decimal("0"), "count": 0})["kg"] += _q(record.kgco2e)
    top_suppliers = sorted(suppliers.items(), key=lambda item: item[1]["ht"], reverse=True)[:8]

    decisions: list[dict[str, Any]] = []
    missing: list[str] = []
    for project in projects[:6]:
        inputs = project_inputs(project)
        if len(inputs) < 2:
            missing.append(f"Projet « {project.title} » : moins de deux options, comparaison impossible.")
            continue
        comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
        pair = comparison.pairs[0]
        entry = {
            "id": project.id,
            "titre": project.title,
            "statut": project.status,
            "horizon_ans": project.horizon_years,
            "priorite": PRIORITIES.get(project.priority, project.priority),
            "prix_interne_carbone": str(project.internal_carbon_price),
            "options": [
                {
                    "nom": result.name,
                    "fournisseur": result.option.supplier,
                    "cout_total": str(result.total_cost),
                    "mise_de_fonds": str(result.initial_outlay),
                    "emissions_cumulees_t": str(result.total_emissions_t) if result.total_emissions_t is not None else None,
                    "emissions_annuelles_t": str(result.annual_emissions_t) if result.annual_emissions_t is not None else None,
                    "confiance": result.option.confidence,
                    "base_emissions": result.option.emissions_basis,
                    "economies_annuelles": str(result.annual_savings),
                }
                for result in comparison.results
            ],
            "moins_cher": comparison.cheapest.name if comparison.cheapest else None,
            "moins_emetteur": comparison.greenest.name if comparison.greenest else None,
            "ecart_cout": str(pair.cost_delta),
            "ecart_emissions_t": str(pair.emissions_delta_t) if pair.emissions_delta_t is not None else None,
            "cout_par_tonne_evitee": str(pair.cost_per_tonne_avoided)
            if pair.cost_per_tonne_avoided is not None
            else None,
        }
        sensitivity = sensitivity_analysis(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
        entry["sensibilite"] = [
            {
                "hypothese": item.label,
                "variation": f"{item.low_case} à {item.high_case}",
                "effet_cout": str(item.cost_swing),
                "inverse_classement": item.can_flip_ranking,
            }
            for item in sensitivity[:3]
        ]
        entry["sensibilite_resume"] = sensitivity_summary(sensitivity, project.horizon_years, limit=2)
        decisions.append(entry)

        for result in comparison.results:
            if result.total_emissions_t is None:
                missing.append(f"Projet « {project.title} » : émissions non renseignées pour l'option « {result.name} ».")
            if result.option.annual_energy_share_pct is None:
                missing.append(f"Projet « {project.title} » : part d'énergie non renseignée pour « {result.name} ».")

    if expense_summary.without_factor_count:
        missing.append(
            f"{expense_summary.without_factor_count} dépense(s) sans facteur d'émission "
            f"({fmt_money(expense_summary.without_factor_amount)}) : émissions non estimées."
        )
    for expense in expenses:
        if not expense.supplier:
            missing.append("Certaines dépenses n'ont pas de fournisseur renseigné (traçabilité incomplète).")

    return {
        "entreprise": {
            "nom": organization.name,
            "secteur": organization.sector,
            "devise": "MAD (DH)",
            "prix_interne_carbone_par_defaut": str(organization.internal_carbon_price),
            "donnees_demonstration_chargees": organization.demo_data_loaded,
        },
        "periode_analyse": f"{months} derniers mois",
        "depenses": {
            "total_ht": str(expense_summary.total_ht),
            "total_ttc": str(expense_summary.total_ttc),
            "nombre_lignes": expense_summary.count,
            "a_verifier": expense_summary.unverified_count,
            "sans_facteur": expense_summary.without_factor_count,
            "par_categorie": [
                {"categorie": row["label"], "ht": str(row["ht"]), "part_pct": str(row["share_pct"])}
                for row in category_rows[:8]
            ],
            "top_fournisseurs": [
                {
                    "fournisseur": name,
                    "ht": str(bucket["ht"]),
                    "emissions_kg_estimees": str(bucket["kg"]) if bucket["kg"] > 0 else None,
                    "nombre_lignes": bucket["count"],
                }
                for name, bucket in top_suppliers
            ],
            "opportunites_economies_declarees": [
                {
                    "projet": row["project_title"],
                    "option": row["option_name"],
                    "economies_annuelles": str(row["annual_savings"]),
                }
                for row in top_savings_opportunities(projects, limit=5)
            ],
        },
        "carbone": {
            "total_kg": str(emission_summary.total_kg),
            "total_t": str(emission_summary.total_t),
            "par_categorie": [
                {"categorie": row["label"], "kg": str(row["kg"]), "part_pct": str(row["share_pct"])}
                for row in emission_rows
            ],
            "par_methode_kg": {
                "mesure": str(emission_summary.measured_kg),
                "calcule": str(emission_summary.calculated_kg),
                "estime": str(emission_summary.estimated_kg),
                "dont_monetaire": str(emission_summary.monetary_kg),
            },
            "part_estimee_pct": str(emission_summary.estimated_share_pct),
            "nombre_enregistrements": emission_summary.record_count,
        },
        "decisions": decisions,
        "facteurs_emission_disponibles": [
            {
                "code": factor.code,
                "libelle": factor.label,
                "unite": factor.unit,
                "valeur_kgco2e": str(factor.kgco2e_per_unit),
                "source": factor.source_name,
                "confiance": factor.confidence,
                "methode": factor.method,
            }
            for factor in factors
        ],
        "donnees_manquantes": list(dict.fromkeys(missing))[:12],
    }


DISCLAIMERS_DEMO = [
    "Mode démonstration sans IA : cette réponse est produite par des règles déterministes à partir de vos données enregistrées.",
    "Les calculs financiers et carbone sont réalisés par le moteur de calcul de l'application, jamais par le modèle de langage.",
]

DISCLAIMERS_IA = [
    "Les chiffres cités proviennent du moteur de calcul de l'application ; l'IA ne réalise aucun calcul financier ou carbone.",
    "Les conseils de l'assistant sont des pistes d'analyse, pas des recommandations professionnelles engageantes.",
]


def _answer_demo(question: str, snapshot: dict[str, Any]) -> CopilotAnswer:
    text = question.lower()
    depenses = snapshot["depenses"]
    carbone = snapshot["carbone"]
    decisions = snapshot["decisions"]
    lines: list[str] = []
    data_used: list[str] = []

    def has(*keywords: str) -> bool:
        return any(keyword in text for keyword in keywords)

    if has("option", "économique", "economique", "moins cher", "comparaison", "décision", "decision"):
        if decisions:
            lines.append("**Comparaisons enregistrées** (chiffres calculés par le moteur, hors actualisation sauf mention) :")
            for entry in decisions[:3]:
                options_txt = " ; ".join(
                    f"« {opt['nom']} » : {fmt_money(_q(opt['cout_total']))} sur {entry['horizon_ans']} ans"
                    + (f", {fmt_tco2e(_q(opt['emissions_cumulees_t']))}" if opt["emissions_cumulees_t"] else ", émissions non renseignées")
                    for opt in entry["options"]
                )
                lines.append(f"• {entry['titre']} ({entry['statut']}) — {options_txt}.")
                if entry["moins_cher"]:
                    lines.append(f"  → Option la plus économique : « {entry['moins_cher']} ».")
                if entry["cout_par_tonne_evitee"] is not None and entry["ecart_emissions_t"] not in (None, "0"):
                    lines.append(
                        f"  → Coût par tonne de CO₂e évitée (paire principale) : {fmt_money(_q(entry['cout_par_tonne_evitee']))}."
                    )
            data_used.append(f"{len(decisions)} projet(s) de décision comparés sur la période")
        else:
            lines.append(
                "Aucun projet de décision n'est encore enregistré. Créez un projet dans « Comparateur de décisions », "
                "ajoutez au moins deux options, puis l'application calculera les coûts cumulés, les émissions et le "
                "coût par tonne de CO₂e évitée."
            )

    elif has("émission", "emission", "carbone", "principal facteur", "pollue"):
        if carbone["nombre_enregistrements"]:
            lines.append(
                f"**Émissions sur les {snapshot['periode_analyse']}** : {fmt_tco2e(_q(carbone['total_t']))} "
                f"({carbone['nombre_enregistrements']} enregistrement(s))."
            )
            for row in carbone["par_categorie"][:4]:
                lines.append(f"• {row['categorie']} : {fmt_tco2e(_q(row['kg']) / 1000)} ({fmt_number(_q(row['part_pct']), 1)} % du total).")
            lines.append(
                f"• Méthodes : mesuré {fmt_tco2e(_q(carbone['par_methode_kg']['mesure']) / 1000)}, "
                f"calculé {fmt_tco2e(_q(carbone['par_methode_kg']['calcule']) / 1000)}, "
                f"estimé {fmt_tco2e(_q(carbone['par_methode_kg']['estime']) / 1000)} "
                f"(dont estimations monétaires : {fmt_tco2e(_q(carbone['par_methode_kg']['dont_monetaire']) / 1000)})."
            )
            if _q(carbone["part_estimee_pct"]) > 0:
                lines.append(
                    f"Attention : {fmt_number(_q(carbone['part_estimee_pct']), 1)} % du total est estimé "
                    "(et non mesuré). Précisez les facteurs d'émission pour fiabiliser le résultat."
                )
            data_used.append("registre carbone de la période")
        else:
            lines.append(
                "Aucun enregistrement carbone sur la période. Deux chemins : lier un facteur d'émission à vos dépenses "
                "(quantité + unité requises) ou saisir directement des lignes dans « Comptabilité carbone »."
            )
            lines.append(
                "Rappel : l'application n'attribue jamais automatiquement un facteur d'émission précis ; "
                "l'estimation monétaire reste approximative et signalée comme telle."
            )

    elif has("paramètre", "parametre", "influence", "sensibilité", "sensibilite", "hypothèse", "hypothese"):
        if decisions and decisions[0]["sensibilite"]:
            entry = decisions[0]
            lines.append(f"**Hypothèses les plus influentes** pour « {entry['titre']} » (écart entre les deux premières options) :")
            for item in entry["sensibilite"]:
                flip = " ⚠ peut inverser le classement" if item["inverse_classement"] else ""
                lines.append(f"• {item['hypothese']} ({item['variation']}) : effet maximal sur l'écart de coût {fmt_money(_q(item['effet_cout']))}{flip}.")
            for line in entry["sensibilite_resume"]:
                lines.append(f"• {line}")
            data_used.append("analyse de sensibilité du projet le plus récent")
        else:
            lines.append(
                "L'analyse de sensibilité nécessite un projet comportant au moins deux options. "
                "Elle est calculée en faisant varier chaque hypothèse (±10 %) et en mesurant l'effet sur l'écart de coût "
                "et l'écart d'émissions entre les options."
            )

    elif has("réduire", "reduire", "économiser", "economiser", "coût", "cout", "énergie", "energie", "dépense"):
        lines.append(f"**Dépenses sur les {snapshot['periode_analyse']}** : {fmt_money(_q(depenses['total_ht']))} HT.")
        for row in depenses["par_categorie"][:4]:
            lines.append(f"• {row['categorie']} : {fmt_money(_q(row['ht']))} ({fmt_number(_q(row['part_pct']), 1)} %).")
        if depenses["opportunites_economies_declarees"]:
            lines.append("**Économies annuelles déclarées dans vos décisions** (à confirmer par le réalisé) :")
            for row in depenses["opportunites_economies_declarees"][:3]:
                lines.append(f"• {row['option']} ({row['projet']}) : {fmt_money(_q(row['economies_annuelles']))} par an.")
        if depenses["a_verifier"]:
            lines.append(
                f"• {depenses['a_verifier']} dépense(s) restent « à vérifier » : fiabiliser ces lignes avant de conclure."
            )
        lignes_energie = [row for row in depenses["par_categorie"] if "nergie" in row["categorie"]]
        if lignes_energie:
            lines.append(
                "Piste d'analyse : pour l'énergie, renseignez la part d'énergie dans les coûts de fonctionnement des "
                "options du comparateur afin d'activer le scénario « hausse du prix de l'énergie »."
            )
        data_used.append("dépenses et catégories de la période")

    elif has("manquant", "manque", "incomplet", "informations", "fournisseur"):
        if snapshot["donnees_manquantes"]:
            lines.append("**Informations manquantes identifiées :**")
            for item in snapshot["donnees_manquantes"]:
                lines.append(f"• {item}")
        else:
            lines.append("Aucune donnée manquante critique n'a été détectée pour les analyses en cours.")
        if depenses["top_fournisseurs"]:
            lines.append("**Fournisseurs les plus significatifs (montants HT)** :")
            for row in depenses["top_fournisseurs"][:5]:
                emissions = (
                    f", émissions rattachées {fmt_tco2e(_q(row['emissions_kg_estimees']) / 1000)}"
                    if row["emissions_kg_estimees"]
                    else ", émissions non rattachées"
                )
                lines.append(f"• {row['fournisseur']} : {fmt_money(_q(row['ht']))}{emissions}.")
            lines.append(
                "Les émissions par fournisseur ne couvrent que les lignes disposant d'un facteur d'émission : "
                "elles ne constituent pas un bilan complet du fournisseur."
            )
        data_used.append("contrôles de complétude et fournisseurs")

    else:
        lines.append(
            "Je peux analyser vos données enregistrées : comparaisons de décisions, dépenses par catégorie, "
            "émissions par catégorie et par méthode, hypothèses les plus influentes et informations manquantes."
        )
        lines.append(
            f"État actuel : {depenses['nombre_lignes']} dépense(s) sur la période, "
            f"{carbone['nombre_enregistrements']} enregistrement(s) carbone, {len(decisions)} décision(s) comparée(s)."
        )
        if snapshot["donnees_manquantes"]:
            lines.append(f"Premier point à traiter : {snapshot['donnees_manquantes'][0]}")
        data_used.append("synthèse générale")

    answer = "\n".join(lines)
    return CopilotAnswer(
        answer=answer,
        mode="demonstration",
        data_used=data_used,
        disclaimers=DISCLAIMERS_DEMO + [
            "Les données de démonstration, si présentes, sont signalées par un badge « Démonstration ».",
        ],
        suggested_questions=SUGGESTED_QUESTIONS,
    )


def _ask_ai(question: str, snapshot: dict[str, Any], history: list[dict[str, str]] | None) -> str:
    system_prompt = (
        "Tu es « CarbonLedger Copilot », l'assistant d'une application de pilotage financier et carbone pour PME "
        "marocaines (devise : dirham, DH). Règles strictes, à respecter sans exception :\n"
        "1. N'utilise QUE les données du contexte JSON fourni. N'invente jamais de chiffre, de fournisseur, de "
        "facteur d'émission, de source ou de règle réglementaire.\n"
        "2. Si une donnée est absente du contexte, dis-le explicitement et indique où la saisir.\n"
        "3. Distingue clairement : fait (calculé à partir des données), estimation (approximative), recommandation "
        "(aide à la décision).\n"
        "4. Ne présente jamais une réduction d'émissions comme une économie financière automatique.\n"
        "5. Réponds en français, en 5 à 12 lignes maximum, avec les unités de l'application (DH, kg CO2e, t CO2e).\n"
        "6. Termine par une question de clarification uniquement si elle est indispensable.\n\n"
        "Contexte JSON (données réelles de l'organisation, calculées par le moteur déterministe) :\n"
        + json.dumps(snapshot, ensure_ascii=False, default=str)
    )
    messages = [{"role": "system", "content": system_prompt}]
    for entry in (history or [])[-6:]:
        role = entry.get("role") if entry.get("role") in {"user", "assistant"} else "user"
        messages.append({"role": role, "content": str(entry.get("content", ""))[:2000]})
    messages.append({"role": "user", "content": question[:2000]})

    url = settings.ai_base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"},
        json={"model": settings.ai_model, "messages": messages, "temperature": 0.2, "max_tokens": 800},
        timeout=45.0,
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload["choices"][0]["message"]["content"]).strip()


def ask(
    db: OrmSession,
    organization: Organization,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> CopilotAnswer:
    """Répond à une question en s'appuyant sur les données réelles de l'organisation."""
    question = (question or "").strip()
    if not question:
        return CopilotAnswer(
            answer="Posez votre question sur vos dépenses, vos émissions ou vos comparaisons de décisions.",
            mode="demonstration",
            disclaimers=DISCLAIMERS_DEMO,
            suggested_questions=SUGGESTED_QUESTIONS,
        )

    snapshot = organization_snapshot(db, organization)
    if settings.ai_configured:
        try:
            answer_text = _ask_ai(question, snapshot, history)
            return CopilotAnswer(
                answer=answer_text,
                mode="ia",
                data_used=["instantané des données de l'organisation transmis au modèle"],
                disclaimers=DISCLAIMERS_IA,
                suggested_questions=SUGGESTED_QUESTIONS,
            )
        except Exception as exc:  # pragma: no cover - dépend du réseau
            demo = _answer_demo(question, snapshot)
            demo.error = (
                "L'assistant IA est configuré mais n'a pas pu répondre "
                f"({type(exc).__name__}). Réponse fournie en mode démonstration."
            )
            return demo

    return _answer_demo(question, snapshot)
