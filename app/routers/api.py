"""Points d'API JSON : recalcul en direct, aperçu carbone, facteurs."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.decision import OptionInput, ScenarioParams
from ..calc.emissions import compute_emissions_kg
from ..calc.formatting import to_decimal
from ..calc.units import are_compatible, canonical_unit, convert
from ..db import get_db
from ..deps import require_api_context
from ..errors import AppError, ValidationError
from ..models import EmissionFactor
from ..services.compute import analysis_to_dict, analyze
from ..web import badge_class

router = APIRouter(prefix="/api")


def _json_error(message: str, status_code: int = 400, fields: dict | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, "fields": fields or {}}, status_code=status_code)


@router.post("/projects/compute")
async def compute_project(request: Request, db: OrmSession = Depends(get_db)):
    """Recalcule une comparaison à partir des options transmises (y compris non enregistrées)."""
    context = require_api_context(request, db)
    try:
        payload = await request.json()
    except Exception:
        return _json_error("Corps JSON invalide.")

    raw_options = payload.get("options") or []
    if len(raw_options) < 2:
        return _json_error("Ajoutez au moins deux options pour lancer la comparaison.")
    try:
        options: list[OptionInput] = []
        for index, raw in enumerate(raw_options):
            options.append(OptionInput.from_dict(raw, key=str(raw.get("key") or f"option_{index + 1}"), index=index))
        analysis = analyze(
            options,
            payload.get("horizon_years") or 5,
            priority=(payload.get("priority") or "equilibre"),
            carbon_price=to_decimal(payload.get("internal_carbon_price")) or Decimal("0"),
            discount_rate_pct=to_decimal(payload.get("discount_rate_pct")) or Decimal("0"),
            params=ScenarioParams.from_dict(payload.get("params")) if payload.get("params") else None,
            custom_scenarios=payload.get("custom_scenarios") or None,
            with_scenarios=bool(payload.get("with_scenarios", True)),
            with_sensitivity=bool(payload.get("with_sensitivity", True)),
            with_charts=bool(payload.get("with_charts", True)),
        )
    except ValidationError as exc:
        return _json_error(exc.message, 422, exc.fields)
    except AppError as exc:
        return _json_error(exc.message, 400)

    return {"ok": True, "analysis": analysis_to_dict(analysis)}


@router.post("/decisions/{project_id}/compute")
async def compute_saved_project(project_id: int, request: Request, db: OrmSession = Depends(get_db)):
    """Recalcule un projet enregistré : params de scénario + priorité, sans modifier la base."""
    context = require_api_context(request, db)
    from ..deps import get_scoped
    from ..models import DecisionProject
    from ..services.project_service import analyze_project

    project = get_scoped(db, DecisionProject, project_id, context.organization.id)
    try:
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        payload = {}
    params = ScenarioParams.from_dict(payload.get("params")) if payload.get("params") else None
    try:
        analysis = analyze_project(
            project,
            priority=(payload.get("priority") or project.priority),
            with_scenarios=bool(payload.get("with_scenarios", True)),
            with_sensitivity=bool(payload.get("with_sensitivity", True)),
            with_charts=bool(payload.get("with_charts", False)),
            params=params,
        )
    except AppError as exc:
        return _json_error(exc.message, 400)
    return {
        "ok": True,
        "analysis": analysis_to_dict(analysis),
        "project": {"id": project.id, "title": project.title, "horizon_years": project.horizon_years},
    }


@router.post("/emissions/preview")
async def emissions_preview(request: Request, db: OrmSession = Depends(get_db)):
    """Aperçu des émissions : quantité x facteur (formule générale)."""
    context = require_api_context(request, db)
    try:
        payload = await request.json()
    except Exception:
        return _json_error("Corps JSON invalide.")
    quantity = to_decimal(payload.get("quantity"))
    unit = canonical_unit(payload.get("unit")) or None
    factor_id = payload.get("factor_id")
    if quantity is None or quantity <= 0:
        return _json_error("Saisissez une quantité d'activité positive.")
    factor: EmissionFactor | None = None
    if factor_id not in (None, "", "0"):
        factor = db.get(EmissionFactor, int(factor_id))
        if factor is None or factor.organization_id not in (None, context.organization.id):
            return _json_error("Facteur d'émission introuvable.")
    else:
        factor_code = (payload.get("factor_code") or "").strip()
        if not factor_code:
            return _json_error("Sélectionnez un facteur d'émission documenté.")
        factor = db.execute(
            select(EmissionFactor).where(
                EmissionFactor.code == factor_code,
                (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == context.organization.id),
            )
        ).scalars().first()
        if factor is None:
            return _json_error(f"Facteur « {factor_code} » introuvable dans le catalogue.")

    if not unit:
        return _json_error("Précisez l'unité de la quantité.")
    if not are_compatible(unit, factor.unit):
        return _json_error(
            f"Unité « {unit} » incompatible avec le facteur {factor.code} ({factor.unit}) : aucune estimation produite."
        )
    base_quantity = convert(quantity, unit, factor.unit)
    kg = compute_emissions_kg(base_quantity, factor.kgco2e_per_unit)
    return {
        "ok": True,
        "kgco2e": str(kg),
        "tonnes": str((kg / 1000).quantize(Decimal("0.001"))),
        "converted_quantity": str(base_quantity),
        "converted_unit": factor.unit,
        "factor": {
            "code": factor.code,
            "label": factor.label,
            "unit": factor.unit,
            "value": str(factor.kgco2e_per_unit),
            "source": factor.source_name,
            "scope": factor.scope,
            "method": factor.method,
            "confidence": factor.confidence,
            "valid_from": factor.valid_from.isoformat() if factor.valid_from else None,
            "valid_until": factor.valid_until.isoformat() if factor.valid_until else None,
            "calculation_note": factor.calculation_note,
            "badge": badge_class(factor.method),
        },
        "formula": f"Émissions = {base_quantity.normalize()} {factor.unit} x {factor.kgco2e_per_unit} kgCO₂e/{factor.unit} = {kg} kgCO₂e",
    }


@router.get("/factors")
def list_factors(request: Request, db: OrmSession = Depends(get_db)):
    context = require_api_context(request, db)
    factors = (
        db.execute(
            select(EmissionFactor)
            .where((EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == context.organization.id))
            .order_by(EmissionFactor.label)
        )
        .scalars()
        .all()
    )
    return {
        "ok": True,
        "factors": [
            {
                "id": factor.id,
                "code": factor.code,
                "label": factor.label,
                "unit": factor.unit,
                "value": str(factor.kgco2e_per_unit),
                "scope": factor.scope,
                "method": factor.method,
                "confidence": factor.confidence,
                "source": factor.source_name,
                "custom": factor.organization_id is not None,
            }
            for factor in factors
        ],
    }
