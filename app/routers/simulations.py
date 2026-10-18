"""Simulations : tester des scénarios avant de décider."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.decision import ScenarioParams
from ..calc.formatting import to_decimal
from ..db import get_db
from ..deps import require_api_context, require_context
from ..errors import AppError
from ..models import DecisionProject
from ..services.compute import analysis_to_dict, key_figures
from ..services.project_service import analyze_project
from ..web import page_context, render

router = APIRouter(prefix="/simulations")


@router.get("")
def simulations_page(
    request: Request,
    db: OrmSession = Depends(get_db),
    project_id: str = "",
    priority: str = "",
):
    context = require_context(request, db)
    projects = (
        db.execute(
            select(DecisionProject)
            .where(DecisionProject.organization_id == context.organization.id)
            .order_by(DecisionProject.updated_at.desc())
        )
        .scalars()
        .all()
    )
    selectable = [project for project in projects if len(project.options) >= 2]
    selected = None
    if project_id.isdigit():
        selected = next((project for project in selectable if project.id == int(project_id)), None)
    if selected is None and selectable:
        selected = selectable[0]

    analysis = None
    analysis_json = None
    figures = None
    error = ""
    if selected is not None:
        try:
            analysis = analyze_project(selected, priority=(priority or selected.priority))
            analysis_json = analysis_to_dict(analysis)
            figures = key_figures(analysis)
        except AppError as exc:
            error = exc.message

    return render(
        request,
        "simulations/index.html",
        page_context(
            request,
            db,
            context,
            "simulations",
            {
                "projects": projects,
                "selectable": selectable,
                "selected": selected,
                "analysis": analysis,
                "analysis_json": analysis_json,
                "figures": figures,
                "error": error,
            },
        ),
    )


@router.post("/{project_id}/simulate")
async def simulate(request: Request, project_id: int, db: OrmSession = Depends(get_db)):
    """Calcule les conséquences d'un jeu d'hypothèses personnalisées (sans enregistrer)."""
    context = require_api_context(request, db)
    from ..deps import get_scoped

    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    try:
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        payload = {}
    params = ScenarioParams.from_dict({**payload, "label": payload.get("label") or "Scénario personnalisé"})
    try:
        analysis = analyze_project(
            project,
            priority=payload.get("priority") or project.priority,
            params=params,
            with_sensitivity=bool(payload.get("with_sensitivity", True)),
            with_charts=bool(payload.get("with_charts", False)),
        )
    except AppError as exc:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=400)
    return {"ok": True, "analysis": analysis_to_dict(analysis), "params": params.to_dict(), "params_description": params.description()}
