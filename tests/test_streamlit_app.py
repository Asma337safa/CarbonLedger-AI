"""Vitrine Streamlit : le script se lance et chaque page s'affiche sans erreur.

Le harnais officiel ``streamlit.testing.v1.AppTest`` exécute ``streamlit_app.py``
en mémoire (sans serveur HTTP) sur la base de démonstration embarquée
``streamlit_demo.db``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "streamlit_app.py"

PAGES = [
    "Dépenses",
    "Comptabilité carbone",
    "Comparateur de décisions",
    "Simulations",
    "À propos",
]


@pytest.fixture()
def app_test() -> AppTest:
    instance = AppTest.from_file(str(APP), default_timeout=120)
    instance.run()
    assert not instance.exception, f"Erreur au démarrage : {instance.exception}"
    return instance


def _markdown_text(instance: AppTest) -> str:
    """Texte de tous les blocs affichés : markdown, titres, en-têtes, sous-en-têtes."""
    chunks: list[str] = []
    for name in ("markdown", "title", "header", "subheader"):
        elements = getattr(instance, name, None) or []
        chunks.extend(element.value for element in elements)
    return " ".join(chunks)


def test_le_tableau_de_bord_affiche_les_totaux_du_moteur(app_test: AppTest) -> None:
    text = _markdown_text(app_test)
    assert "Tableau de bord" in text
    # Totaux du jeu de démonstration, produits par le moteur de calcul partagé.
    assert "136" in text  # dépenses HT de l'année
    assert "74" in text  # émissions totales en tonnes de CO₂e


def test_le_comparateur_reproduit_l_exemple_du_cahier_des_charges(app_test: AppTest) -> None:
    app_test.sidebar.radio[0].set_value("Comparateur de décisions").run()
    assert not app_test.exception, f"Erreur sur le comparateur : {app_test.exception}"
    text = _markdown_text(app_test)
    assert "200" in text  # option A : 200 000 DH sur 5 ans
    assert "180" in text  # option B : 180 000 DH sur 5 ans
    assert "800" in text  # 800 DH économisés par tonne de CO₂e évitée (gain double)
    assert "25" in text  # 25 t CO₂e évitées


def test_toutes_les_pages_s_affichent_sans_exception(app_test: AppTest) -> None:
    for page in PAGES:
        app_test.sidebar.radio[0].set_value(page).run()
        assert not app_test.exception, f"Page en erreur : {page}"
