"""Contrats entre les fichiers JavaScript statiques et les gabarits Jinja2.

Le JavaScript ne s'exécute qu'à partir d'ancres connues (``#identifiant``).
Un renommage dans un gabarit casse silencieusement l'interactivité : ces tests
vérifient que chaque sélecteur ``#id`` du dossier ``static/js`` possède bien une
cible dans au moins un gabarit, et contrôlent l'assistant d'importation rendu.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "app" / "static" / "js"
TEMPLATES_DIR = ROOT / "app" / "templates"

# Sélecteurs du type qs(document, "#cible") ou qsa(document, "#cible").
SELECTEUR_ID = re.compile(r'[qQ]sa?\([^,]+,\s*"#([A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*)"')
ID_GABARIT = re.compile(r'id="([^"]+)"')


def _identifiants_des_gabarits() -> set[str]:
    identifiants: set[str] = set()
    for chemin in TEMPLATES_DIR.rglob("*.html"):
        identifiants.update(ID_GABARIT.findall(chemin.read_text(encoding="utf-8")))
    return identifiants


def test_selecteurs_javascript_presents_dans_les_gabarits():
    """Aucun fichier JS ne doit viser un identifiant absent des gabarits."""
    identifiants = _identifiants_des_gabarits()
    manquants: dict[str, list[str]] = {}
    for chemin in sorted(JS_DIR.glob("*.js")):
        utilises = set(SELECTEUR_ID.findall(chemin.read_text(encoding="utf-8")))
        absents = sorted(cible for cible in utilises if cible not in identifiants)
        if absents:
            manquants[chemin.name] = absents
    assert manquants == {}, f"Sélecteurs sans cible dans les gabarits : {manquants}"


def test_page_import_expose_le_contrat_du_wizard(client, company):
    """L'assistant d'importation doit fournir les ancres attendues par import.js."""
    page = client.get("/imports")
    assert page.status_code == 200
    assert 'id="import-wizard"' in page.text
    assert 'id="import-meta"' in page.text

    correspondance = re.search(r'id="import-meta"[^>]*data-app-fields="([^"]*)"', page.text)
    assert correspondance, "Le bloc #import-meta doit porter les champs attendus."
    champs = json.loads(html.unescape(correspondance.group(1)))
    assert "date" in champs
    assert champs["date"]["required"] is True
    assert champs["date"]["label"]
