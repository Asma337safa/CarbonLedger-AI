"""Notifications internes (calculées à partir des données, jamais inventées)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..models import CarbonRecord, DecisionProject, Expense, Organization, Report


def build_notifications(db: OrmSession, organization: Organization) -> list[dict[str, Any]]:
    """Liste de notifications utiles : elles pointent vers des actions concrètes."""
    notifications: list[dict[str, Any]] = []

    unverified = db.execute(
        select(func.count(Expense.id)).where(
            Expense.organization_id == organization.id, Expense.verification_status != "verifiee"
        )
    ).scalar_one()
    if unverified:
        notifications.append(
            {
                "level": "attention",
                "title": f"{unverified} dépense(s) à vérifier",
                "message": "Des lignes ne sont pas encore confirmées : vérifiez-les pour fiabiliser les analyses.",
                "href": "/expenses?status=a_verifier",
            }
        )

    without_factor = db.execute(
        select(func.count(Expense.id)).where(
            Expense.organization_id == organization.id, Expense.emission_factor_id.is_(None)
        )
    ).scalar_one()
    if without_factor:
        notifications.append(
            {
                "level": "info",
                "title": f"{without_factor} dépense(s) sans facteur d'émission",
                "message": "Leur carbone n'est pas estimé : liez une quantité, une unité et un facteur documenté.",
                "href": "/expenses",
            }
        )

    recent_carbon = db.execute(
        select(func.count(CarbonRecord.id)).where(
            CarbonRecord.organization_id == organization.id,
            CarbonRecord.period_start >= date.today() - timedelta(days=90),
        )
    ).scalar_one()
    if recent_carbon == 0:
        notifications.append(
            {
                "level": "info",
                "title": "Aucune donnée carbone récente",
                "message": "Aucun enregistrement carbone sur les 90 derniers jours.",
                "href": "/carbon/new",
            }
        )

    draft_projects = db.execute(
        select(DecisionProject).where(
            DecisionProject.organization_id == organization.id, DecisionProject.status == "brouillon"
        )
    ).scalars().all()
    for project in draft_projects[:3]:
        notifications.append(
            {
                "level": "info",
                "title": f"Décision en brouillon : {project.title}",
                "message": "Complétez les options puis enregistrez la décision pour historiser la recommandation.",
                "href": f"/decisions/{project.id}",
            }
        )

    reports = db.execute(
        select(Report)
        .where(Report.organization_id == organization.id)
        .order_by(Report.created_at.desc())
        .limit(1)
    ).scalars().all()
    if reports:
        report = reports[0]
        notifications.append(
            {
                "level": "success",
                "title": f"Dernier rapport : {report.title}",
                "message": "Votre rapport est disponible dans la section Rapports.",
                "href": "/reports",
            }
        )

    if organization.demo_data_loaded:
        notifications.append(
            {
                "level": "attention",
                "title": "Données de démonstration chargées",
                "message": "Les données marquées « Démonstration » sont fictives ; supprimez-les avant un usage réel.",
                "href": "/settings#donnees",
            }
        )
    return notifications[:6]
