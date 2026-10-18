"""Paramètres : entreprise, membres, facteurs d'émission, IA, données, audit."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import parse_date
from ..calc.formatting import to_decimal
from ..config import settings as app_settings
from ..db import get_db
from ..deps import flash, get_scoped, require_admin, require_context, require_write
from ..enums import CARBON_CATEGORIES, CONFIDENCE_LEVELS, EMISSION_METHODS, MEMBER_ROLES, SCOPES
from ..errors import ValidationError
from ..models import (
    AuditLog,
    CarbonRecord,
    DecisionProject,
    EmissionFactor,
    Expense,
    Invitation,
    Organization,
    OrganizationMember,
    Report,
    utcnow,
)
from ..security import new_token, token_hash
from ..services import audit
from ..services.demo_data import delete_demo_data, load_demo_data
from ..web import page_context, render

router_public = APIRouter()          # actions (POST) et export
router = APIRouter(prefix="/settings")


@router.get("")
def settings_page(request: Request, db: OrmSession = Depends(get_db), tab: str = "entreprise"):
    context = require_context(request, db)
    organization = context.organization
    members = (
        db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization.id)
            .order_by(OrganizationMember.id)
        )
        .scalars()
        .all()
    )
    factors = (
        db.execute(
            select(EmissionFactor)
            .where(
                (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == organization.id)
            )
            .order_by(EmissionFactor.organization_id.is_(None), EmissionFactor.label)
        )
        .scalars()
        .all()
    )
    invitations = (
        db.execute(
            select(Invitation)
            .where(Invitation.organization_id == organization.id, Invitation.accepted_at.is_(None))
            .order_by(Invitation.created_at.desc())
        )
        .scalars()
        .all()
    )
    audit_logs = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization.id)
            .order_by(AuditLog.created_at.desc())
            .limit(60)
        )
        .scalars()
        .all()
    )
    counts = {
        "expenses": db.execute(select(Expense).where(Expense.organization_id == organization.id)).scalars().all().__len__(),
        "carbon": db.execute(select(CarbonRecord).where(CarbonRecord.organization_id == organization.id)).scalars().all().__len__(),
        "projects": db.execute(select(DecisionProject).where(DecisionProject.organization_id == organization.id)).scalars().all().__len__(),
        "reports": db.execute(select(Report).where(Report.organization_id == organization.id)).scalars().all().__len__(),
    }
    return render(
        request,
        "settings/index.html",
        page_context(
            request,
            db,
            context,
            "settings",
            {
                "tab": tab if tab in {"entreprise", "membres", "facteurs", "ia", "donnees", "audit"} else "entreprise",
                "members": members,
                "factors": factors,
                "invitations": invitations,
                "audit_logs": audit_logs,
                "counts": counts,
                "ai_configured": app_settings.ai_configured,
                "ai_model": app_settings.ai_model,
                "ai_base_url": app_settings.ai_base_url,
            },
        ),
    )


@router.post("/organization")
async def update_organization(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_admin(context)
    form = dict(await request.form())
    organization = context.organization
    name = (form.get("name") or "").strip()
    if not name:
        flash(db, context, "danger", "Le nom de l'entreprise est obligatoire.")
        return RedirectResponse("/settings", status_code=303)
    organization.name = name[:160]
    organization.ice = (form.get("ice") or "").strip()[:20]
    organization.sector = (form.get("sector") or "").strip()[:80]
    organization.company_size = (form.get("company_size") or "").strip()[:40]
    carbon_price = to_decimal(form.get("internal_carbon_price"))
    if carbon_price is not None and carbon_price >= 0:
        organization.internal_carbon_price = carbon_price
    audit.log(
        db,
        action="organization_updated",
        organization_id=organization.id,
        user_id=context.user.id,
        entity_type="organization",
        entity_id=organization.id,
        details={"nom": organization.name},
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Informations de l'entreprise mises à jour.")
    return RedirectResponse("/settings", status_code=303)


@router.post("/members/invite")
async def invite_member(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_admin(context)
    form = dict(await request.form())
    email = (form.get("email") or "").strip().lower()
    role = form.get("role") or "membre"
    if role not in MEMBER_ROLES:
        role = "membre"
    if "@" not in email or len(email) < 5:
        flash(db, context, "danger", "Adresse e-mail invalide.")
        return RedirectResponse("/settings?tab=membres", status_code=303)
    existing = db.execute(
        select(OrganizationMember)
        .join(OrganizationMember.user)
        .where(OrganizationMember.organization_id == context.organization.id)
    ).scalars().all()
    from ..models import User

    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if user is not None and any(member.user_id == user.id for member in existing):
        flash(db, context, "warning", "Cette personne fait déjà partie de votre organisation.")
        return RedirectResponse("/settings?tab=membres", status_code=303)

    token = new_token()
    invitation = Invitation(
        organization_id=context.organization.id,
        email=email,
        role=role,
        token_hash=token_hash(token),
        expires_at=utcnow() + timedelta(days=7),
        created_by_id=context.user.id,
    )
    db.add(invitation)
    audit.log(
        db,
        action="member_invited",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="invitation",
        entity_id=invitation.id,
        details={"email": email, "role": role},
        request=request,
    )
    db.commit()
    link = f"{app_settings.base_url}/invite/{token}"
    flash(
        db,
        context,
        "success",
        f"Invitation créée pour {email} (rôle : {MEMBER_ROLES[role]}). "
        "L'envoi d'e-mails n'est pas configuré : transmettez ce lien sécurisé (valide 7 jours) — "
        f"{link}",
    )
    return RedirectResponse("/settings?tab=membres", status_code=303)


@router.post("/members/{member_id}/role")
async def update_member_role(member_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_admin(context)
    member = get_scoped(db, OrganizationMember, member_id, context.organization.id)
    form = dict(await request.form())
    role = form.get("role") or ""
    if role not in MEMBER_ROLES:
        raise ValidationError("Rôle inconnu.")
    if member.role == "proprietaire" and role != "proprietaire":
        owners = [
            entry
            for entry in db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == context.organization.id,
                    OrganizationMember.role == "proprietaire",
                )
            ).scalars().all()
        ]
        if len(owners) <= 1:
            flash(db, context, "danger", "Impossible de retirer le dernier propriétaire de l'organisation.")
            return RedirectResponse("/settings?tab=membres", status_code=303)
    member.role = role
    audit.log(
        db,
        action="member_role_updated",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="member",
        entity_id=member.id,
        details={"role": role},
        request=request,
    )
    db.commit()
    flash(db, context, "success", "Rôle mis à jour.")
    return RedirectResponse("/settings?tab=membres", status_code=303)


@router.post("/members/{member_id}/remove")
def remove_member(member_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_admin(context)
    member = get_scoped(db, OrganizationMember, member_id, context.organization.id)
    if member.user_id == context.user.id:
        flash(db, context, "danger", "Vous ne pouvez pas retirer votre propre accès.")
        return RedirectResponse("/settings?tab=membres", status_code=303)
    if member.role == "proprietaire":
        owners = db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == context.organization.id,
                OrganizationMember.role == "proprietaire",
            )
        ).scalars().all()
        if len(owners) <= 1:
            flash(db, context, "danger", "Impossible de retirer le dernier propriétaire.")
            return RedirectResponse("/settings?tab=membres", status_code=303)
    audit.log(
        db,
        action="member_removed",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="member",
        entity_id=member.id,
        details={"utilisateur": member.user_id},
        request=request,
        commit=True,
    )
    db.delete(member)
    db.commit()
    flash(db, context, "success", "Accès retiré.")
    return RedirectResponse("/settings?tab=membres", status_code=303)


@router.post("/factors")
async def create_factor(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    form = dict(await request.form())
    code = (form.get("code") or "").strip().upper()
    label = (form.get("label") or "").strip()
    unit = (form.get("unit") or "").strip()
    value = to_decimal(form.get("kgco2e_per_unit"))
    source_name = (form.get("source_name") or "").strip()
    if not code or not label or not unit or value is None:
        flash(db, context, "danger", "Code, libellé, unité et valeur du facteur sont obligatoires.")
        return RedirectResponse("/settings?tab=facteurs", status_code=303)
    if value < 0:
        flash(db, context, "danger", "La valeur du facteur ne peut pas être négative.")
        return RedirectResponse("/settings?tab=facteurs", status_code=303)
    if not source_name:
        flash(db, context, "danger", "La source du facteur est obligatoire : indiquez la référence utilisée.")
        return RedirectResponse("/settings?tab=facteurs", status_code=303)

    exists = db.execute(
        select(EmissionFactor).where(
            EmissionFactor.organization_id == context.organization.id, EmissionFactor.code == code
        )
    ).scalars().first()
    if exists is not None:
        flash(db, context, "danger", f"Le code « {code} » existe déjà dans vos facteurs personnalisés.")
        return RedirectResponse("/settings?tab=facteurs", status_code=303)

    method = form.get("method") if form.get("method") in EMISSION_METHODS else "calcule"
    scope = form.get("scope") if form.get("scope") in SCOPES else "3"
    confidence = form.get("confidence") if form.get("confidence") in CONFIDENCE_LEVELS else "moyenne"
    factor = EmissionFactor(
        organization_id=context.organization.id,
        code=code[:60],
        label=label[:200],
        category=form.get("category") if form.get("category") in CARBON_CATEGORIES else "autres",
        unit=unit[:24],
        scope=scope,
        method=method,
        kgco2e_per_unit=value,
        source_name=source_name[:200],
        source_url=(form.get("source_url") or "").strip()[:400],
        source_version=(form.get("source_version") or "").strip()[:60],
        geography=(form.get("geography") or "").strip()[:16],
        valid_from=parse_date(form.get("valid_from")),
        valid_until=parse_date(form.get("valid_until")),
        confidence=confidence,
        calculation_note=(form.get("calculation_note") or "").strip(),
    )
    db.add(factor)
    audit.log(
        db,
        action="factor_created",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="emission_factor",
        entity_id=factor.id,
        details={"code": code, "valeur": str(value), "source": source_name},
        request=request,
    )
    db.commit()
    flash(db, context, "success", f"Facteur {code} ajouté à votre organisation.")
    return RedirectResponse("/settings?tab=facteurs", status_code=303)


@router.post("/factors/{factor_id}/delete")
def delete_factor(factor_id: int, request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_write(context)
    factor = db.get(EmissionFactor, factor_id)
    if factor is None or factor.organization_id != context.organization.id:
        flash(db, context, "danger", "Seuls vos facteurs personnalisés peuvent être supprimés.")
        return RedirectResponse("/settings?tab=facteurs", status_code=303)
    used = db.execute(select(CarbonRecord).where(CarbonRecord.emission_factor_id == factor.id)).scalars().first()
    if used is not None:
        flash(
            db,
            context,
            "warning",
            "Ce facteur est utilisé par des enregistrements carbone existants : "
            "il ne peut pas être supprimé (l'historique doit rester traçable).",
        )
        return RedirectResponse("/settings?tab=facteurs", status_code=303)
    audit.log(
        db,
        action="factor_deleted",
        organization_id=context.organization.id,
        user_id=context.user.id,
        entity_type="emission_factor",
        entity_id=factor.id,
        details={"code": factor.code},
        request=request,
        commit=True,
    )
    db.delete(factor)
    db.commit()
    flash(db, context, "success", "Facteur personnalisé supprimé.")
    return RedirectResponse("/settings?tab=facteurs", status_code=303)


@router.post("/ai/test")
def test_ai(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    require_admin(context)
    if not app_settings.ai_configured:
        flash(
            db,
            context,
            "warning",
            "Aucune clé API n'est configurée : le Copilot fonctionne en mode démonstration déterministe. "
            "Renseignez CARBONLEDGER_AI_API_KEY dans le fichier .env puis redémarrez l'application.",
        )
        return RedirectResponse("/settings?tab=ia", status_code=303)
    try:
        from ..services.copilot import _ask_ai

        response = _ask_ai(
            "Test de connexion : réponds uniquement par « Connexion établie ».",
            {"test": True, "donnees": "aucune"},
            None,
        )
        audit.log(
            db,
            action="ai_test_success",
            organization_id=context.organization.id,
            user_id=context.user.id,
            details={"modele": app_settings.ai_model},
            request=request,
            commit=True,
        )
        flash(db, context, "success", f"Connexion à l'assistant IA établie (modèle {app_settings.ai_model}). Réponse : {response[:120]}")
    except Exception as exc:
        flash(
            db,
            context,
            "danger",
            f"Échec de connexion à l'assistant IA ({type(exc).__name__}). "
            "Vérifiez la clé API, l'URL de base et votre connexion réseau.",
        )
    return RedirectResponse("/settings?tab=ia", status_code=303)


@router.post("/demo-data")
def manage_demo_data(request: Request, db: OrmSession = Depends(get_db), action: str = Form("load")):
    context = require_context(request, db)
    require_write(context)
    organization = context.organization
    if action == "delete":
        counts = delete_demo_data(db, organization)
        audit.log(
            db,
            action="demo_data_deleted",
            organization_id=organization.id,
            user_id=context.user.id,
            details=counts,
            request=request,
        )
        db.commit()
        flash(
            db,
            context,
            "success",
            f"Données de démonstration supprimées ({counts['expenses']} dépenses, "
            f"{counts['carbon_records']} enregistrements carbone, {counts['projects']} projets).",
        )
    else:
        summary = load_demo_data(db, organization, context.user.id)
        audit.log(
            db,
            action="demo_data_loaded",
            organization_id=organization.id,
            user_id=context.user.id,
            details=summary,
            request=request,
        )
        db.commit()
        flash(
            db,
            context,
            "success",
            f"Données de démonstration chargées : {summary['expenses']} dépenses, "
            f"{summary['carbon_records']} enregistrements carbone, {summary['projects']} projets de décision.",
        )
    return RedirectResponse("/settings?tab=donnees", status_code=303)


@router.get("/export.json")
def export_json(request: Request, db: OrmSession = Depends(get_db)):
    """Export complet des données de l'organisation (droit d'accès et de portabilité)."""
    context = require_context(request, db)
    organization = context.organization
    expenses = db.execute(select(Expense).where(Expense.organization_id == organization.id)).scalars().all()
    records = db.execute(select(CarbonRecord).where(CarbonRecord.organization_id == organization.id)).scalars().all()
    projects = db.execute(select(DecisionProject).where(DecisionProject.organization_id == organization.id)).scalars().all()
    factors = db.execute(
        select(EmissionFactor).where(
            (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == organization.id)
        )
    ).scalars().all()

    def factor_row(factor):
        return {
            "code": factor.code,
            "libelle": factor.label,
            "unite": factor.unit,
            "valeur_kgco2e_par_unite": str(factor.kgco2e_per_unit),
            "source": factor.source_name,
            "version": factor.source_version,
            "perimetre": SCOPES.get(factor.scope, factor.scope),
            "methode": EMISSION_METHODS.get(factor.method, factor.method),
            "confiance": factor.confidence,
            "valide_du": factor.valid_from.isoformat() if factor.valid_from else None,
            "valide_au": factor.valid_until.isoformat() if factor.valid_until else None,
        }

    payload = {
        "application": "CarbonLedger AI",
        "genere_le": utcnow().isoformat(),
        "entreprise": {
            "nom": organization.name,
            "ice": organization.ice,
            "secteur": organization.sector,
            "taille": organization.company_size,
            "devise": organization.currency,
            "prix_interne_carbone": str(organization.internal_carbon_price),
        },
        "depenses": [
            {
                "date": expense.expense_date.isoformat(),
                "categorie": expense.category,
                "fournisseur": expense.supplier,
                "description": expense.description,
                "montant_ht": str(expense.amount_ht),
                "tva": str(expense.vat_amount),
                "montant_ttc": str(expense.amount_ttc),
                "quantite": str(expense.quantity) if expense.quantity is not None else None,
                "unite": expense.unit,
                "facteur": expense.emission_factor.code if expense.emission_factor else None,
                "source_carbone": expense.carbon_source_note,
                "statut_verification": expense.verification_status,
                "demonstration": expense.is_demo,
            }
            for expense in expenses
        ],
        "registre_carbone": [
            {
                "debut": record.period_start.isoformat(),
                "fin": record.period_end.isoformat(),
                "categorie": record.category,
                "quantite_activite": str(record.activity_quantity),
                "unite": record.activity_unit,
                "facteur": record.emission_factor.code if record.emission_factor else None,
                "source_facteur": record.emission_factor.source_name if record.emission_factor else None,
                "methode": EMISSION_METHODS.get(record.method, record.method),
                "statut": record.status,
                "confiance": record.confidence,
                "kg_co2e": str(record.kgco2e),
                "demonstration": record.is_demo,
            }
            for record in records
        ],
        "decisions": [
            {
                "titre": project.title,
                "description": project.description,
                "horizon_ans": project.horizon_years,
                "priorite": project.priority,
                "prix_interne_carbone": str(project.internal_carbon_price),
                "statut": project.status,
                "demonstration": project.is_demo,
                "options": [
                    {
                        "nom": option.name,
                        "fournisseur": option.supplier,
                        "cout_acquisition": str(option.purchase_cost),
                        "transport": str(option.transport_cost),
                        "cout_fonctionnement_annuel": str(option.annual_opex),
                        "part_energie_pct": str(option.annual_energy_share_pct) if option.annual_energy_share_pct is not None else None,
                        "maintenance_annuelle": str(option.annual_maintenance),
                        "economies_annuelles": str(option.annual_savings),
                        "duree_utilisation_ans": str(option.useful_life_years) if option.useful_life_years is not None else None,
                        "emissions_annuelles_kg": str(option.annual_emissions_kg) if option.annual_emissions_kg is not None else None,
                        "base_emissions": option.emissions_basis,
                        "source_emissions": option.emissions_source_note,
                        "confiance": option.confidence,
                    }
                    for option in project.options
                ],
            }
            for project in projects
        ],
        "facteurs_utilises": [factor_row(factor) for factor in factors],
    }
    audit.log(
        db,
        action="data_exported",
        organization_id=organization.id,
        user_id=context.user.id,
        details={"format": "json"},
        request=request,
        commit=True,
    )
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="carbonledger_export_{organization.id}.json"'},
    )


@router.post("/organization/delete")
async def delete_organization(request: Request, db: OrmSession = Depends(get_db)):
    """Suppression de l'organisation (action irréversible, confirmation exigée)."""
    context = require_context(request, db)
    require_admin(context)
    form = dict(await request.form())
    confirmation = (form.get("confirmation") or "").strip().upper()
    if confirmation != "SUPPRIMER":
        flash(db, context, "danger", "Saisissez exactement SUPPRIMER pour confirmer la suppression.")
        return RedirectResponse("/settings?tab=donnees", status_code=303)
    organization = context.organization
    audit.log(
        db,
        action="organization_deleted",
        organization_id=None,
        user_id=context.user.id,
        entity_type="organization",
        entity_id=organization.id,
        details={"nom": organization.name, "ice": organization.ice},
        request=request,
        commit=True,
    )
    db.delete(organization)
    db.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("cl_session")
    return response
