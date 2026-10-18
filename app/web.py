"""Rendu des pages (Jinja2) : filtres, contexte commun et helpers."""

from __future__ import annotations

import html
import re
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as OrmSession

from . import __version__
from .calc import formatting
from .config import BASE_DIR, settings
from .deps import Context, pop_flash
from .enums import (
    CARBON_CATEGORIES,
    CARBON_STATUSES,
    CONFIDENCE_LEVELS,
    EMISSION_METHODS,
    EXPENSE_CATEGORIES,
    MEMBER_ROLES,
    PERIOD_PRESETS,
    PRIORITIES,
    PROJECT_STATUSES,
    SCENARIO_KINDS,
    SCOPES,
    UNITS,
    VERIFICATION_STATUSES,
)
from .services.notifications import build_notifications

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

NAV_ITEMS = [
    ("dashboard", "Tableau de bord", "◆"),
    ("expenses", "Dépenses", "▤"),
    ("carbon", "Comptabilité carbone", "◍"),
    ("decisions", "Comparateur de décisions", "⇄"),
    ("simulations", "Simulations", "∿"),
    ("reports", "Rapports", "▣"),
    ("copilot", "Assistant IA", "✳"),
    ("settings", "Paramètres", "⛭"),
]

BADGE_CLASSES = {
    "verifiee": "badge--success",
    "a_verifier": "badge--warning",
    "rejetee": "badge--danger",
    "mesure": "badge--success",
    "calcule": "badge--info",
    "estime": "badge--warning",
    "monetaire": "badge--warning",
    "haute": "badge--success",
    "moyenne": "badge--info",
    "faible": "badge--warning",
    "brouillon": "badge--info",
    "enregistree": "badge--success",
    "archivee": "badge--muted",
    "attention": "badge--warning",
    "info": "badge--info",
    "success": "badge--success",
    "danger": "badge--danger",
}


def badge_class(value: str | None) -> str:
    return BADGE_CLASSES.get((value or "").strip().lower(), "badge--muted")


def mdlite(text: str | None) -> str:
    """Convertit un texte Markdown simple (**gras**, listes « • ») en HTML sûr."""
    if not text:
        return ""
    parts: list[str] = []
    in_list = False
    for raw_line in str(text).split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        escaped = html.escape(stripped)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        if stripped.startswith("•"):
            if not in_list:
                parts.append('<ul class="copilot-list">')
                in_list = True
            parts.append(f"<li>{escaped.lstrip('•').strip()}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            if stripped.startswith("→"):
                parts.append(f'<p class="copilot-note">{escaped.lstrip("→").strip()}</p>')
            else:
                parts.append(f"<p>{escaped}</p>")
    if in_list:
        parts.append("</ul>")
    return "".join(parts)


# --- filtres Jinja ---------------------------------------------------------
templates.env.filters["mad"] = lambda value, decimals=2: formatting.fmt_money(value, decimals=decimals)
templates.env.filters["money_compact"] = formatting.fmt_money_compact
templates.env.filters["num"] = formatting.fmt_number
templates.env.filters["tco2e"] = formatting.fmt_tco2e
templates.env.filters["kg"] = lambda value: formatting.fmt_kg(value)
templates.env.filters["pct"] = formatting.fmt_pct
templates.env.filters["datefr"] = formatting.fmt_date
templates.env.filters["datelong"] = formatting.fmt_date_long
templates.env.filters["period"] = formatting.fmt_period
templates.env.filters["datetimefr"] = formatting.fmt_datetime
templates.env.filters["qty"] = formatting.fmt_quantity
templates.env.filters["mdlite"] = mdlite
templates.env.filters["badgeclass"] = badge_class
templates.env.filters["decimal"] = formatting.to_decimal

templates.env.globals.update(
    app_name=settings.app_name,
    app_version=__version__,
    ai_configured=settings.ai_configured,
    nav_items=NAV_ITEMS,
    expense_categories=EXPENSE_CATEGORIES,
    carbon_categories=CARBON_CATEGORIES,
    verification_statuses=VERIFICATION_STATUSES,
    carbon_statuses=CARBON_STATUSES,
    emission_methods=EMISSION_METHODS,
    confidence_levels=CONFIDENCE_LEVELS,
    project_statuses=PROJECT_STATUSES,
    priorities=PRIORITIES,
    member_roles=MEMBER_ROLES,
    scenario_kinds=SCENARIO_KINDS,
    units=UNITS,
    scopes=SCOPES,
    period_presets=PERIOD_PRESETS,
)


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    payload = dict(context or {})
    payload.setdefault("request", request)
    return templates.TemplateResponse(request, template, payload, status_code=status_code)


def page_context(
    request: Request,
    db: OrmSession,
    context: Context | None,
    active: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Contexte commun à toutes les pages authentifiées."""
    payload: dict[str, Any] = {
        "ctx": context,
        "active": active,
        "flash_messages": pop_flash(db, context),
        "notifications": build_notifications(db, context.organization) if context else [],
        "csrf_token": context.csrf_token if context else request.cookies.get("cl_csrf", ""),
        "period_label": None,
    }
    payload.update(extra or {})
    return payload
