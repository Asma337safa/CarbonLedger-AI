"""Helpers de test : comptes, jetons CSRF, envoi de formulaires multi-valeurs."""

from __future__ import annotations

import re
from urllib.parse import urlencode

DEFAULT_PASSWORD = "MotDePasse!2026"
FIRST_EMAIL = "salma@atlas-agro.ma"

_CSRF_META = re.compile(r'name="csrf-token" content="([^"]*)"')
_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]*)"')
_counter = {"value": 0}


def next_email(prefix: str = "test") -> str:
    """Adresse e-mail unique (les tests partagent la même base)."""
    _counter["value"] += 1
    return f"{prefix}{_counter['value']}@exemple.ma"


def csrf_meta(response) -> str:
    match = _CSRF_META.search(response.text)
    return match.group(1) if match else ""


def csrf_field(response) -> str:
    match = _CSRF_FIELD.search(response.text)
    return match.group(1) if match else ""


def register_company(
    client,
    *,
    email: str | None = None,
    company: str = "PME Test SARL",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Utilisateur Test",
    ice: str = "001234567000012",
    sector: str = "agroalimentaire",
    size: str = "45",
) -> dict[str, str]:
    """Crée un compte : renvoie les identifiants utilisés."""
    email = email or next_email()
    page = client.get("/register")
    token = client.cookies.get("cl_csrf") or csrf_field(page)
    response = client.post(
        "/register",
        data={
            "full_name": full_name,
            "company_name": company,
            "ice": ice,
            "sector": sector,
            "company_size": size,
            "email": email,
            "password": password,
            "password_confirm": password,
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]
    return {"email": email, "password": password, "company": company}


def load_demo_data(client, sector: str = "agroalimentaire", size: str = "45"):
    """Charge le jeu de démonstration depuis l'assistant d'accueil."""
    page = client.get("/onboarding")
    token = csrf_field(page) or client.cookies.get("cl_csrf")
    response = client.post(
        "/onboarding",
        data={"sector": sector, "company_size": size, "action": "demo", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]
    return response


def token_for(client, path: str = "/") -> str:
    """Jeton CSRF courant (métadonnée de page ou champ de formulaire)."""
    page = client.get(path)
    return csrf_meta(page) or csrf_field(page) or client.cookies.get("cl_csrf") or ""


def post_fields(client, path: str, fields, **kwargs):
    """POST ``application/x-www-form-urlencoded`` en préservant les clés répétées.

    httpx traite une liste de tuples comme un corps *streamé* (sans en-tête de
    type) : on encode donc nous-mêmes, exactement comme le fait un navigateur.
    """
    body = urlencode(list(fields)).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))}
    headers.update(kwargs.pop("headers", {}))
    return client.post(path, content=body, headers=headers, **kwargs)


def create_decision(client, options=None, **project_fields):
    """Crée un projet de décision via le formulaire et renvoie l'identifiant."""
    options = options or [
        {"name": "Option A", "purchase_cost": "80000", "annual_opex": "24000", "annual_emissions_kg": "45000"},
        {"name": "Option B", "purchase_cost": "95000", "annual_opex": "17000", "annual_emissions_kg": "40000"},
    ]
    page = client.get("/decisions/new")
    fields: list[tuple[str, str]] = [
        ("csrf_token", csrf_field(page)),
        ("title", project_fields.get("title", "Projet de test")),
        ("description", project_fields.get("description", "Description de test")),
        ("category", project_fields.get("category", "energie")),
        ("horizon_years", str(project_fields.get("horizon_years", 5))),
        ("discount_rate_pct", str(project_fields.get("discount_rate_pct", 0))),
        ("internal_carbon_price", str(project_fields.get("internal_carbon_price", 0))),
        ("priority", project_fields.get("priority", "equilibre")),
    ]
    for option in options:
        fields.extend(
            [
                ("option_key", option.get("key", "")),
                ("option_name", option.get("name", "Option")),
                ("option_supplier", option.get("supplier", "")),
                ("option_purchase_cost", option.get("purchase_cost", "0")),
                ("option_transport_cost", option.get("transport_cost", "0")),
                ("option_annual_opex", option.get("annual_opex", "0")),
                ("option_annual_energy_share_pct", option.get("annual_energy_share_pct", "")),
                ("option_annual_maintenance", option.get("annual_maintenance", "0")),
                ("option_annual_savings", option.get("annual_savings", "0")),
                ("option_useful_life_years", option.get("useful_life_years", "")),
                ("option_annual_emissions_kg", option.get("annual_emissions_kg", "")),
                ("option_emissions_basis", option.get("emissions_basis", "")),
                ("option_emissions_source_note", option.get("emissions_source_note", "")),
                ("option_confidence", option.get("confidence", "moyenne")),
                ("option_notes", option.get("notes", "")),
            ]
        )
    response = post_fields(client, "/decisions", fields, follow_redirects=False)
    assert response.status_code == 303, response.text[:400]
    location = response.headers.get("location", "")
    digits = re.sub(r"\D", "", location)
    assert digits, f"Identifiant de projet introuvable dans « {location} »"
    return int(digits)


def factor_id(client, code: str = "ELEC-RESEAU-MA") -> int:
    """Identifiant d'un facteur du catalogue global (page /carbon/new)."""
    page = client.get("/carbon/new")
    match = re.search(rf'<option value="(\d+)"[^>]*data-code="{re.escape(code)}"', page.text, re.S)
    assert match, f"Facteur « {code} » introuvable dans le catalogue."
    return int(match.group(1))
