"""Comparateur de décisions : projet, options, résultats, arbitrage, scénarios."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.arbitration import arbitrate
from ..calc.decision import compare_options
from ..calc.formatting import fmt_money, to_decimal
from ..config import settings
from ..db import get_db
from ..deps import flash, get_scoped, require_context, require_write
from ..enums import EXPENSE_CATEGORIES, PRIORITIES, PROJECT_STATUSES
from ..errors import ValidationError
from ..models import DecisionOption, DecisionProject, Report, Scenario
from ..services import audit
from ..services.compute import analysis_to_dict, key_figures
from ..services.project_service import analyze_project, options_from_form, project_inputs
from ..services.report_pdf import generate_decision_pdf
from ..web import page_context, render

router = APIRouter(prefix="/decisions")


def _validate_priority(value: str) -> str:
    return value if value in PRIORITIES else "equilibre"


def _form_fields(raw) -> dict:
    """Convertit un formulaire multidict en dict simple.

    Les champs répétés (``option_name``, ``option_supplier``…) conservent la
    liste complète des valeurs : ``dict(request.form())`` ne garderait que la
    dernière et ferait perdre des options.
    """
    data: dict = {}
    for key in raw.keys():
        values = raw.getlist(key)
        data[key] = values if len(values) > 1 else values[0]
    return data


def _validate_status(value: str) -> str:
    return value if value in PROJECT_STATUSES else "brouillon"


def _validate_horizon(value) -> int:
    try:
        years = int(to_decimal(value) or Decimal("5"))
    except (TypeError, ValueError):
        years = 5
    return max(1, min(30, years))


def _project_meta_from_form(form: dict) -> dict:
    title = (form.get("title") or "").strip()
    if not title:
        raise ValidationError("Le titre du projet est obligatoire.")
    category = form.get("category") or "equipements"
    if category not in EXPENSE_CATEGORIES:
        category = "equipements"
    carbon_price = to_decimal(form.get("internal_carbon_price")) or Decimal("0")
    discount = to_decimal(form.get("discount_rate_pct")) or Decimal("0")
    if carbon_price < 0 or discount < 0:
        raise ValidationError("Le prix interne du carbone et le taux d'actualisation doivent être positifs.")
    return {
        "title": title[:200],
        "description": (form.get("description") or "").strip(),
        "category": category,
        "horizon_years": _validate_horizon(form.get("horizon_years")),
        "discount_rate_pct": discount,
        "priority": _validate_priority(form.get("priority") or "equilibre"),
        "internal_carbon_price": carbon_price,
    }


def _persist_options(db: OrmSession, project: DecisionProject, options) -> None:
    existing = {option.id: option for option in project.options}
    keep_ids: list[int] = []
    for index, option_input in enumerate(options):
        option_id = None
        raw_key = option_input.key or ""
        if raw_key.startswith("o") and raw_key[1:].isdigit():
            option_id = int(raw_key[1:])
        option = existing.get(option_id) if option_id else None
        if option is None:
            option = DecisionOption(project_id=project.id)
            db.add(option)
        option.name = option_input.name[:200]
        option.supplier = option_input.supplier[:200]
        option.purchase_cost = option_input.purchase_cost
        option.transport_cost = option_input.transport_cost
        option.annual_opex = option_input.annual_opex
        option.annual_energy_share_pct = option_input.annual_energy_share_pct
        option.annual_maintenance = option_input.annual_maintenance
        option.annual_savings = option_input.annual_savings
        option.useful_life_years = option_input.useful_life_years
        option.annual_emissions_kg = option_input.annual_emissions_kg
        option.emissions_basis = option_input.emissions_basis
        option.emissions_source_note = option_input.emissions_source_note
        option.confidence = option_input.confidence
        option.notes = option_input.notes
        option.sort_order = index
        db.flush()
        keep_ids.append(option.id)
    for option_id, option in existing.items():
        if option_id not in keep_ids:
            db.delete(option)


@router.get("")
def list_projects(request: Request, db: OrmSession = Depends(get_db), status: str = ""):
    context = require_context(request, db)
    query = select(DecisionProject).where(DecisionProject.organization_id == context.organization.id)
    if status in PROJECT_STATUSES:
        query = query.where(DecisionProject.status == status)
    projects = db.execute(query.order_by(DecisionProject.updated_at.desc())).scalars().all()

    cards = []
    for project in projects:
        inputs = project_inputs(project)
        card = {"project": project, "figures": None, "error": None, "options_count": len(inputs)}
        if len(inputs) >= 2:
            try:
                comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
                result = arbitrate(comparison, project.priority)
                card["figures"] = {
                    "cheapest": comparison.cheapest.name if comparison.cheapest else None,
                    "cheapest_cost": comparison.cheapest.total_cost if comparison.cheapest else None,
                    "greenest": comparison.greenest.name if comparison.greenest else None,
                    "greenest_emissions": comparison.greenest.total_emissions_t if comparison.greenest else None,
                    "frontier": len(comparison.frontier),
                    "headline": result.recommendation_title,
                }
            except ValidationError as exc:
                card["error"] = exc.message
        else:
            card["error"] = "Ajoutez au moins deux options pour comparer."
        cards.append(card)

    return render(
        request,
        "decisions/list.html",
        page_context(
            request,
            db,
            context,
            "decisions",
            {"cards": cards, "status_filter": status, "count": len(projects)},
        ),
    )


@router.get("/new")
def new_project(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    return render(
        request,
        "decisions/form.html",
        page_context(
            request,
            db,
            context,
            "decisions",
            {"project": None, "options": [], "form": {}, "default_carbon_price": context.organization.internal_carbon_price},
        ),
    )


@router.post("")
async def create_project(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    form = _form_fields(await request.form())
    try:
        meta = _project_meta_from_form(form)
        options = options_from_form(form)
        if len(options) < 2:
            raise ValidationError("Ajoutez au moins deux options à comparer.")
        comparison = compare_options(options, meta["horizon_years"], carbon_price=meta["internal_carbon_price"])
        if len(comparison.results) < 2:
            raise ValidationError("Deux options valides sont nécessaires.")
    except ValidationError as exc:
        flash(db, context, "danger", exc.message)
        return render(
            request,
            "decisions/form.html",
            page_context(
                request,
                db,
                context,
                "decisions",
                {"project": None, "options": [], "form": form, "default_carbon_price": context.organization.internal_carbon_price},
            ),
            status_code=400,
        )

    project = DecisionProject(
        organization_id=context.organization.id,
        is_demo=False,
        created_by_id=context.user.id,
        status="brouillon",
        **meta,
    )
    db.add(project)
    db.flush()
    _persist_options(db, project, options)
    audit.log(
        db,
        action="decision_created",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="decision_project",
        entity_id=project.id,
        details={"titre": project.title, "options": len(options), "horizon": project.horizon_years},
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Projet créé. Vérifiez les résultats, testez les scénarios puis enregistrez votre décision.")
    return RedirectResponse(f"/decisions/{project.id}", status_code=303)


@router.get("/{project_id}")
def project_detail(
    project_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    priority: str = "",
    tab: str = "resultats",
):
    context = require_context(request, db)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    inputs = project_inputs(project)
    if len(inputs) < 2:
        flash(db, context, "warning", "Ce projet comporte moins de deux options : ajoutez une option pour lancer la comparaison.")
        return RedirectResponse(f"/decisions/{project.id}/edit", status_code=303)

    preview_priority = _validate_priority(priority) if priority else project.priority
    analysis = analyze_project(project, priority=preview_priority)
    scenarios_saved = project.scenarios
    figures = key_figures(analysis)
    latest_recommendation = project.recommendations[-1] if project.recommendations else None

    return render(
        request,
        "decisions/detail.html",
        page_context(
            request,
            db,
            context,
            "decisions",
            {
                "project": project,
                "analysis": analysis,
                "analysis_json": analysis_to_dict(analysis),
                "figures": figures,
                "priority": preview_priority,
                "tab": tab if tab in {"resultats", "arbitrage", "scenarios", "sensibilite"} else "resultats",
                "scenarios_saved": scenarios_saved,
                "latest_recommendation": latest_recommendation,
                "options_json": [input_option.__dict__ | {"key": input_option.key, "name": input_option.name} for input_option in []],
            },
        ),
    )


@router.get("/{project_id}/edit")
def edit_project(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    return render(
        request,
        "decisions/form.html",
        page_context(
            request,
            db,
            context,
            "decisions",
            {
                "project": project,
                "options": project.options,
                "form": {},
                "default_carbon_price": project.internal_carbon_price,
            },
        ),
    )


@router.post("/{project_id}")
async def update_project(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    form = _form_fields(await request.form())
    try:
        meta = _project_meta_from_form(form)
        options = options_from_form(form)
        if len(options) < 2:
            raise ValidationError("Ajoutez au moins deux options à comparer.")
        compare_options(options, meta["horizon_years"], carbon_price=meta["internal_carbon_price"])
    except ValidationError as exc:
        flash(db, context, "danger", exc.message)
        return RedirectResponse(f"/decisions/{project.id}/edit", status_code=303)

    for key, value in meta.items():
        setattr(project, key, value)
    _persist_options(db, project, options)
    audit.log(
        db,
        action="decision_updated",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="decision_project",
        entity_id=project.id,
        details={"titre": project.title, "options": len(options)},
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Projet mis à jour : les résultats sont recalculés automatiquement.")
    return RedirectResponse(f"/decisions/{project.id}", status_code=303)


@router.post("/{project_id}/save")
async def save_decision(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    """Enregistre la décision : statut, priorité, prix du carbone et recommandation."""
    context = require_context(request, db)
    require_write(context)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    form = dict(await request.form())
    priority = _validate_priority(form.get("priority") or project.priority)
    carbon_price = to_decimal(form.get("internal_carbon_price"))
    if carbon_price is not None and carbon_price >= 0:
        project.internal_carbon_price = carbon_price
    project.priority = priority
    project.status = _validate_status(form.get("status") or "enregistree")

    inputs = project_inputs(project)
    if len(inputs) < 2:
        flash(db, context, "danger", "Deux options minimum sont nécessaires pour enregistrer une comparaison.")
        return RedirectResponse(f"/decisions/{project.id}", status_code=303)

    comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
    result = arbitrate(comparison, priority)
    chosen_key = (form.get("chosen_option") or "").strip()
    chosen_option = next((option for option in project.options if option.name == chosen_key), None)
    project.chosen_option_id = chosen_option.id if chosen_option else project.chosen_option_id

    from ..models import Recommendation

    db.add(
        Recommendation(
            project_id=project.id,
            priority=priority,
            carbon_price=project.internal_carbon_price,
            summary=result.recommendation_title + " " + " ".join(result.recommendation_paragraphs),
            details=result.to_dict(),
            chosen_option_id=project.chosen_option_id,
            created_by_id=context.user.id,
        )
    )
    audit.log(
        db,
        action="decision_saved",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="decision_project",
        entity_id=project.id,
        details={
            "priorite": priority,
            "option_retenue": chosen_option.name if chosen_option else None,
            "prix_carbone": str(project.internal_carbon_price),
        },
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Décision enregistrée : la recommandation et les hypothèses sont historisées.")
    return RedirectResponse(f"/decisions/{project.id}?tab=arbitrage", status_code=303)


@router.post("/{project_id}/scenario")
async def save_scenario(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    form = dict(await request.form())
    name = (form.get("name") or "").strip() or "Scénario personnalisé"
    parameters = {
        "label": name,
        "energy_price_delta_pct": to_decimal(form.get("energy_price_delta_pct")) or Decimal("0"),
        "transport_delta_pct": to_decimal(form.get("transport_delta_pct")) or Decimal("0"),
        "savings_delta_pct": to_decimal(form.get("savings_delta_pct")) or Decimal("0"),
        "activity_volume_delta_pct": to_decimal(form.get("activity_volume_delta_pct")) or Decimal("0"),
        "emission_factor_delta_pct": to_decimal(form.get("emission_factor_delta_pct")) or Decimal("0"),
        "lifetime_delta_years": to_decimal(form.get("lifetime_delta_years")) or Decimal("0"),
    }
    scenario = Scenario(
        project_id=project.id,
        name=name[:120],
        kind="personnalise",
        parameters={key: float(value) if isinstance(value, Decimal) else value for key, value in parameters.items()},
        notes=(form.get("notes") or "").strip(),
        created_by_id=context.user.id,
    )
    db.add(scenario)
    audit.log(
        db,
        action="scenario_saved",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="scenario",
        entity_id=scenario.id,
        details={"projet": project.title, "parametres": scenario.parameters},
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Scénario enregistré pour ce projet.")
    return RedirectResponse(f"/decisions/{project.id}?tab=scenarios", status_code=303)


@router.post("/{project_id}/scenario/{scenario_id}/delete")
def delete_scenario(project_id: int, scenario_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    scenario = get_scoped(db, Scenario, scenario_id, context.organization.id)
    if scenario.project_id != project.id:
        raise ValidationError("Scénario introuvable pour ce projet.")
    db.delete(scenario)
    db.commit()
    flash(db, context, "success", "Scénario supprimé.")
    return RedirectResponse(f"/decisions/{project.id}?tab=scenarios", status_code=303)


@router.post("/{project_id}/delete")
def delete_project(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    audit.log(
        db,
        action="decision_deleted",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="decision_project",
        entity_id=project.id,
        details={"titre": project.title},
        request=request,
    )
    db.delete(project)
    db.commit()
    flash(db, context, "success", "Projet supprimé.")
    return RedirectResponse("/decisions", status_code=303)


@router.get("/{project_id}/export.csv")
def export_project_csv(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    inputs = project_inputs(project)
    if len(inputs) < 2:
        raise ValidationError("Deux options minimum sont nécessaires pour exporter la comparaison.")
    comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow([f"Projet : {project.title}", f"Horizon : {project.horizon_years} ans",
                     f"Prix interne carbone : {project.internal_carbon_price} DH/tCO2e"])
    writer.writerow([])
    writer.writerow([
        "option", "fournisseur", "cout_acquisition", "transport", "cout_fonctionnement_annuel", "maintenance_annuelle",
        "economies_annuelles", "mise_de_fonds_initiale", "cout_total_periode", "economies_cumulees",
        "emissions_annuelles_t", "emissions_cumulees_t", "cout_actualise_net", "confiance",
    ])
    for result in comparison.results:
        writer.writerow([
            result.name, result.option.supplier, f"{result.purchase_cost:.2f}", f"{result.transport_cost:.2f}",
            f"{result.annual_opex:.2f}", f"{result.annual_maintenance:.2f}", f"{result.annual_savings:.2f}",
            f"{result.initial_outlay:.2f}", f"{result.total_cost:.2f}", f"{result.total_savings:.2f}",
            f"{result.annual_emissions_t:.3f}" if result.annual_emissions_t is not None else "",
            f"{result.total_emissions_t:.3f}" if result.total_emissions_t is not None else "",
            f"{result.npv:.2f}" if result.npv is not None else "",
            result.option.confidence,
        ])
    writer.writerow([])
    writer.writerow(["comparaison", "ecart_cout_a_moins_b", "ecart_emissions_t", "cout_par_tonne_evitee", "interpretation"])
    for pair in comparison.pairs:
        writer.writerow([
            f"{pair.a_name} vs {pair.b_name}",
            f"{pair.cost_delta:.2f}",
            f"{pair.emissions_delta_t:.3f}" if pair.emissions_delta_t is not None else "",
            f"{pair.cost_per_tonne_avoided:.2f}" if pair.cost_per_tonne_avoided is not None else "",
            " ".join(pair.interpretation_parts),
        ])
    audit.log(
        db,
        action="decision_exported_csv",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="decision_project",
        entity_id=project.id,
        request=request,
        commit=True,
    )
    buffer.seek(0)
    return StreamingResponse(
        iter(["\ufeff" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="comparaison_decision_{project.id}.csv"'},
    )


@router.get("/{project_id}/report.pdf")
def export_project_pdf(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    inputs = project_inputs(project)
    if len(inputs) < 2:
        raise ValidationError("Deux options minimum sont nécessaires pour générer le rapport.")
    analysis = analyze_project(project)

    reports_dir = settings.reports_dir / str(context.organization.id)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report = Report(
        organization_id=context.organization.id,
        project_id=project.id,
        kind="pdf",
        scope="projet",
        title=f"Rapport de décision — {project.title}",
        created_by_id=context.user.id,
    )
    db.add(report)
    db.flush()
    path = reports_dir / f"decision_{project.id}_{report.id}.pdf"
    payload = generate_decision_pdf(
        path,
        organization_name=context.organization.name,
        project_title=project.title,
        project_category=EXPENSE_CATEGORIES.get(project.category, project.category),
        horizon_years=project.horizon_years,
        priority_label=PRIORITIES.get(project.priority, project.priority),
        carbon_price=project.internal_carbon_price,
        analysis=analysis,
        author_name=context.user.full_name or context.user.email,
        notes=[
            f"Priorité retenue lors de l'enregistrement : {PRIORITIES.get(project.priority, project.priority)}.",
            "Rapport produit par CarbonLedger AI à partir des données saisies dans l'application.",
        ],
    )
    report.file_path = str(path)
    report.payload = payload
    audit.log(
        db,
        action="report_generated",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="report",
        entity_id=report.id,
        details={"type": "pdf", "projet": project.title},
        request=request,
    )
    db.commit()
    flash(db, context, "success", f"Rapport PDF généré : {report.title}.")
    return FileResponse(path, media_type="application/pdf", filename=f"rapport_decision_{project.id}.pdf")
