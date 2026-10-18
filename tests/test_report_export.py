"""Rapports et exports : génération PDF (période, projet) et Excel via HTTP.

La logique d'assemblage vit dans ``app.services.report_build`` (partagée entre
l'interface FastAPI et l'application Streamlit) : ces tests verrouillent le
comportement des routes et le contenu produit.
"""

from __future__ import annotations

from app.models import Report
from tests import helpers


def _csrf(client) -> dict[str, str]:
    return {"csrf_token": helpers.token_for(client, "/reports")}


def test_rapport_de_gestion_pdf(client, demo_company, db):
    response = client.post(
        "/reports/generate",
        data={"scope": "periode", "period": "annee", "output": "pdf", **_csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text[:300]
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content[:5] == b"%PDF-"
    assert db.query(Report).filter(Report.scope == "periode").count() >= 1


def test_rapport_de_gestion_excel(client, demo_company):
    response = client.post(
        "/reports/generate",
        data={"scope": "periode", "period": "tout", "output": "xlsx", **_csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text[:300]
    assert response.content[:2] == b"PK"  # archive zip du classeur openpyxl
    assert ".xlsx" in response.headers.get("content-disposition", "")


def test_rapport_de_projet_pdf(client, company, db):
    project_id = helpers.create_decision(client, title="Projet rapport PDF")
    response = client.post(
        "/reports/generate",
        data={"scope": "projet", "project_id": str(project_id), "output": "pdf", **_csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text[:300]
    assert response.content[:5] == b"%PDF-"
    assert db.query(Report).filter(Report.scope == "projet").count() >= 1
