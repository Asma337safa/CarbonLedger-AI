"""Application Streamlit : accueil, inscription, connexion et espace isolé.

Le harnais officiel ``streamlit.testing.v1.AppTest`` exécute ``streamlit_app.py``
en mémoire (sans serveur HTTP) sur la base de test de la suite. Scénarios
couverts :

- l'accueil propose la création de compte et la connexion, sans aucune donnée
  de démonstration affichée ;
- l'inscription crée un espace **vide** (pas de chargement automatique) ;
- deux comptes vivent dans des espaces isolés, et les données restent
  enregistrées d'une connexion à l'autre ;
- la démonstration ne se charge que sur action volontaire depuis les
  paramètres ;
- le comparateur reproduit l'exemple du cahier des charges ;
- l'import d'un fichier CSV suit les quatre étapes (analyse, correspondance,
  vérification, confirmation) et crée les dépenses ;
- les rapports se génèrent en PDF (période et projet) et en Excel ;
- l'assistant IA répond en mode démonstration, à partir des données réelles ;
- toutes les pages s'affichent sans exception.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "streamlit_app.py"

PAGES = [
    "Tableau de bord",
    "Dépenses",
    "Imports",
    "Comptabilité carbone",
    "Comparateur de décisions",
    "Simulations",
    "Rapports",
    "Assistant IA",
    "Paramètres",
]

MOT_DE_PASSE = "MotDePasse1"


def _spawn() -> AppTest:
    instance = AppTest.from_file(str(APP), default_timeout=180)
    instance.run()
    assert not instance.exception, f"Erreur au démarrage : {instance.exception}"
    return instance


def _suffixe() -> str:
    return uuid.uuid4().hex[:10]


def _texte(instance: AppTest) -> str:
    """Tout le texte affiché (markdown, titres, messages, tableaux), NBSP normalisées."""
    chunks: list[str] = []
    for name in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "text",
        "info",
        "success",
        "warning",
        "error",
    ):
        for element in getattr(instance, name, None) or []:
            value = getattr(element, "value", "")
            if isinstance(value, str):
                chunks.append(value)
    for element in getattr(instance, "dataframe", None) or []:
        value = getattr(element, "value", None)
        if isinstance(value, pd.DataFrame):
            chunks.append(value.to_string())
    for element in getattr(instance, "button", None) or []:
        label = getattr(element, "label", "")
        if isinstance(label, str):
            chunks.append(label)
    return "\n".join(chunks).replace("\u202f", " ").replace("\u00a0", " ")


def _inscrire(
    instance: AppTest,
    suffixe: str,
    nom: str = "Compte Test",
    entreprise: str | None = None,
) -> str:
    """Depuis l'accueil : ouvre l'inscription, remplit le formulaire, valide."""
    email = f"st.{suffixe}@carbonledger.ma"
    instance.button(key="go_register").click().run()
    assert not instance.exception, f"Erreur sur l'inscription : {instance.exception}"
    instance.text_input(key="reg_name").set_value(nom)
    instance.text_input(key="reg_company").set_value(entreprise or f"Entreprise {suffixe}")
    instance.text_input(key="reg_email").set_value(email)
    instance.text_input(key="reg_password").set_value(MOT_DE_PASSE)
    instance.text_input(key="reg_password2").set_value(MOT_DE_PASSE)
    instance.button(key="reg_submit").click().run()
    assert not instance.exception, f"Erreur après validation : {instance.exception}"
    return email


def _connexion(instance: AppTest, email: str, mot_de_passe: str = MOT_DE_PASSE) -> None:
    """Depuis l'accueil : ouvre la connexion et se connecte."""
    instance.button(key="go_login").click().run()
    assert not instance.exception, f"Erreur sur la connexion : {instance.exception}"
    instance.text_input(key="log_email").set_value(email)
    instance.text_input(key="log_password").set_value(mot_de_passe)
    instance.button(key="log_submit").click().run()
    assert not instance.exception, f"Erreur après connexion : {instance.exception}"


def _aller_a(instance: AppTest, page: str) -> None:
    instance.radio(key="nav").set_value(page).run()
    assert not instance.exception, f"Page en erreur : {page} — {instance.exception}"


def test_l_accueil_propose_inscription_et_connexion() -> None:
    instance = _spawn()
    text = _texte(instance)
    assert "CarbonLedger AI" in text
    assert "Créer un compte entreprise" in text
    assert "Se connecter" in text
    # Aucune donnée de démonstration ne doit s'afficher avant connexion.
    assert "136" not in text  # total HT du jeu de démonstration
    assert "74,58" not in text  # émissions du jeu de démonstration
    assert len(instance.radio) == 0  # pas encore d'espace de travail

    instance.button(key="go_register").click().run()
    assert not instance.exception
    assert "Créer votre compte entreprise" in _texte(instance)

    instance.button(key="reg_home").click().run()
    instance.button(key="go_login").click().run()
    assert "Connexion" in _texte(instance)


def test_l_inscription_cree_un_espace_vide() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe(), entreprise="Espace vide SARL")
    text = _texte(instance)
    assert "Votre espace est vide" in text  # aucun chargement automatique
    assert "136" not in text  # pas de chiffres de démonstration
    assert "Bienvenue" in text  # message de confirmation de l'inscription
    assert "Espace vide SARL" in text  # l'organisation de l'utilisateur


def test_isolation_et_persistance_entre_deux_comptes() -> None:
    instance = _spawn()
    suffixe_a = _suffixe()
    email_a = _inscrire(instance, suffixe_a, nom="Compte A")

    # A enregistre une dépense dans son espace.
    _aller_a(instance, "Dépenses")
    instance.text_input(key="exp_ht").set_value("1500")
    instance.text_input(key="exp_vat").set_value("300")
    instance.button(key="exp_save").click().run()
    assert not instance.exception, f"Erreur à l'enregistrement : {instance.exception}"
    assert "1 500,00" in _texte(instance)  # total HT de l'espace de A

    # A se déconnecte ; B crée son compte : son espace est vide.
    instance.sidebar.button(key="logout").click().run()
    assert not instance.exception
    email_b = _inscrire(instance, _suffixe(), nom="Compte B")
    _aller_a(instance, "Dépenses")
    text_b = _texte(instance)
    assert "Aucune dépense enregistrée" in text_b
    assert "1 500,00" not in text_b  # les données de A restent invisibles

    # A se reconnecte : sa dépense a bien été conservée.
    instance.sidebar.button(key="logout").click().run()
    _connexion(instance, email_a)
    _aller_a(instance, "Dépenses")
    assert "1 500,00" in _texte(instance)
    assert email_a != email_b


def test_le_chargement_de_la_demonstration_est_volontaire() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    text = _texte(instance)
    assert "Votre espace est vide" in text

    _aller_a(instance, "Paramètres")
    assert "25 dépenses" in _texte(instance)  # l'offre de chargement est décrite
    instance.button(key="settings_load_demo").click().run()
    assert not instance.exception, f"Erreur au chargement : {instance.exception}"
    assert "Jeu de démonstration chargé" in _texte(instance)

    _aller_a(instance, "Tableau de bord")
    instance.radio(key="dash_period").set_value("Tout l'historique").run()
    text = _texte(instance)
    assert "136" in text  # dépenses HT du jeu de démonstration
    assert "74" in text  # émissions totales en tonnes de CO₂e


def test_le_comparateur_reproduit_l_exemple_du_cahier_des_charges() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    _aller_a(instance, "Comparateur de décisions")
    text = _texte(instance)
    assert "200" in text  # option A : 200 000 DH sur 5 ans
    assert "180" in text  # option B : 180 000 DH sur 5 ans
    assert "800" in text  # 800 DH économisés par tonne de CO₂e évitée (gain double)
    assert "25" in text  # 25 t CO₂e évitées


def test_toutes_les_pages_s_affichent_sans_exception() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    for page in PAGES:
        _aller_a(instance, page)
        assert not instance.exception, f"Page en erreur : {page}"


def test_import_csv_de_bout_en_bout() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    _aller_a(instance, "Imports")
    assert "Imports de fichiers" in _texte(instance)

    contenu = (
        "Date;Fournisseur;Description;Montant HT;TVA\n"
        "15/03/2026;Fournil Atlas;Farine et emballages;1000;200\n"
        "10/04/2026;Energie Casa;Electricite atelier;2500;500\n"
    )
    instance.file_uploader(key="imp_file").set_value(
        ("depenses_test.csv", contenu.encode("utf-8"), "text/csv")
    ).run()
    assert not instance.exception, f"Erreur à l'analyse du fichier : {instance.exception}"
    text = _texte(instance)
    assert "Fichier analysé" in text
    assert "2 ligne(s) détectée(s)" in text
    assert "Correspondance des colonnes" in text

    instance.button(key="imp_validate").click().run()
    assert not instance.exception, f"Erreur à la vérification : {instance.exception}"
    assert "Prêtes à importer" in _texte(instance)

    instance.button(key="imp_confirm").click().run()
    assert not instance.exception, f"Erreur à la confirmation : {instance.exception}"
    assert "Importation terminée" in _texte(instance)

    # Les deux lignes confirmées apparaissent dans les dépenses de l'espace.
    _aller_a(instance, "Dépenses")
    text = _texte(instance)
    assert "1 000,00" in text
    assert "2 500,00" in text
    assert "3 500,00" in text  # total HT des lignes importées


def test_rapports_pdf_excel_et_projet() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    instance.button(key="dash_load_demo").click().run()
    assert not instance.exception, f"Erreur au chargement de la démo : {instance.exception}"

    _aller_a(instance, "Rapports")
    text = _texte(instance)
    assert "Rapports et exports" in text
    assert "136" in text  # aperçu du contenu : total HT du jeu de démonstration

    # Rapport PDF de gestion sur l'année en cours.
    instance.button(key="rep_generate").click().run()
    assert not instance.exception, f"Erreur à la génération du PDF : {instance.exception}"
    telechargement = instance.session_state["rep_download"]
    assert telechargement["data"][:4] == b"%PDF"
    assert telechargement["name"].endswith(".pdf")
    assert instance.download_button, "le bouton de téléchargement doit être proposé"

    # Export Excel (trois feuilles) de tout l'historique.
    instance.radio(key="rep_output").set_value("Excel (export des données)").run()
    assert not instance.exception
    instance.button(key="rep_generate").click().run()
    assert not instance.exception, f"Erreur à l'export Excel : {instance.exception}"
    telechargement = instance.session_state["rep_download"]
    assert telechargement["data"][:2] == b"PK"  # classeur openpyxl (archive zip)
    assert telechargement["name"].endswith(".xlsx")

    # Rapport PDF d'un projet de décision (le premier projet de démonstration).
    instance.radio(key="rep_scope").set_value("Projet de décision").run()
    assert not instance.exception
    instance.button(key="rep_generate_project").click().run()
    assert not instance.exception, f"Erreur au rapport de projet : {instance.exception}"
    telechargement = instance.session_state["rep_download"]
    assert telechargement["data"][:4] == b"%PDF"
    assert "Rapport de décision" in telechargement["label"]


def test_assistant_ia_en_mode_demonstration() -> None:
    instance = _spawn()
    _inscrire(instance, _suffixe())
    _aller_a(instance, "Assistant IA")
    text = _texte(instance)
    assert "Mode démonstration" in text
    assert "Questions suggérées" in text

    # Espace vide : l'assistant répond sans inventer de chiffre.
    instance.chat_input(key="cop_input").set_value("Quel est le total de mes dépenses ?").run()
    assert not instance.exception, f"Erreur de l'assistant : {instance.exception}"
    historique = instance.session_state["cop_history"]
    assert len(historique) == 2
    assert historique[0]["role"] == "user"
    assert historique[1]["role"] == "assistant"
    assert "Mode démonstration" in historique[1]["meta"]
    assert "DH" in historique[1]["content"]

    # Avec le jeu de démonstration, la réponse cite les montants réels.
    _aller_a(instance, "Tableau de bord")
    instance.button(key="dash_load_demo").click().run()
    assert not instance.exception
    _aller_a(instance, "Assistant IA")
    instance.chat_input(key="cop_input").set_value("Quel est le total de mes dépenses ?").run()
    assert not instance.exception
    historique = instance.session_state["cop_history"]
    assert len(historique) == 4
    assert "136" in historique[3]["content"]  # 136 560,00 DH HT du jeu de démonstration
