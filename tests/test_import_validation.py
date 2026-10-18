"""Tests de la validation des imports (aucun montant repris sans contrôle)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import ValidationError
from app.services.import_service import (
    ParsedFile,
    parse_file,
    suggest_mapping,
    validate_rows,
)

CSV_VALIDE = """Date;Fournisseur;Description;Catégorie;Montant HT;TVA;Unité;Quantité;Code facteur
04/03/2026;Taqa Énergie;Facture électricité mars;Énergie;18000;3600;kWh;22000;ELEC-RESEAU-MA
12/03/2026;Transporteur Atlas;Livraison Kénitra;Transport;4500;900;km;600;
"""

CSV_DOUBLON = """Date;Fournisseur;Description;Montant HT;TVA
04/03/2026;Taqa Énergie;Facture électricité mars;18000;3600
04/03/2026;Taqa Énergie;Facture électricité mars (copie);18000;3600
"""

CSV_AVEC_ERREURS = """Date;Fournisseur;Description;Catégorie;Montant HT;TVA
;Fournisseur sans date;Ligne sans date;Énergie;1000;200
04/03/2026;Fournisseur négatif;Avoir;Inconnue;-5000;100
04/03/2026;Sans montant;Description seule;Transport;;200
"""


@pytest.fixture
def csv_file(tmp_path: Path):
    def write(content: str, name: str = "depenses.csv") -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return write


@pytest.fixture
def facteur_elec():
    """Facteur documenté (objet attendu par le service : attributs, pas dictionnaire)."""
    return SimpleNamespace(
        id=1,
        code="ELEC-RESEAU-MA",
        unit="kWh",
        kgco2e_per_unit=Decimal("0.0811"),
        method="calcule",
        confidence="moyenne",
        source_name="ADEME Base Empreinte (indicatif) — à confirmer",
    )


def test_analyse_csv_et_encodage(csv_file):
    parsed = parse_file(csv_file(CSV_VALIDE), "depenses.csv")
    assert parsed.total_rows == 2
    assert "Date" in parsed.columns
    assert "Code facteur" in parsed.columns
    assert parsed.rows[0]["__ligne__"] == 2  # numéro de ligne réel dans le fichier


def test_analyse_refuse_un_format_non_pris_en_charge(csv_file):
    path = csv_file("contenu", name="donnees.txt")
    with pytest.raises(ValidationError):
        parse_file(path, "donnees.txt")


def test_suggestion_de_correspondance_des_colonnes():
    mapping = suggest_mapping(["Date", "Fournisseur", "Description", "Montant HT", "TVA", "Unité", "Quantité"])
    assert mapping["date"] == "Date"
    assert mapping["supplier"] == "Fournisseur"
    assert mapping["amount_ht"] == "Montant HT"
    assert "amount_ttc" not in mapping  # aucune colonne TTC ici


def test_validation_dun_fichier_valide(csv_file):
    parsed = parse_file(csv_file(CSV_VALIDE), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    report = validate_rows(parsed, mapping, {}, set())

    assert len(report.rows) == 2
    assert report.errors() == []
    premiere = report.rows[0]
    assert premiere["amount_ht"] == Decimal("18000.00")
    assert premiere["amount_ttc"] == Decimal("21600.00")  # HT + TVA
    assert premiere["category"] == "energie"
    assert premiere["expense_date"].isoformat() == "2026-03-04"
    # Sans catalogue de facteurs fourni : aucun carbone inventé
    assert premiere["carbon_kg"] is None
    assert premiere["factor_code"] == ""
    assert report.stats["errors"] == 0
    assert report.stats["valid"] == 2
    assert report.stats["with_carbon"] == 0


def test_carbone_calcule_seulement_si_facteur_documente(csv_file, facteur_elec):
    parsed = parse_file(csv_file(CSV_VALIDE), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    report = validate_rows(parsed, mapping, {"ELEC-RESEAU-MA": facteur_elec}, set())

    premiere = report.rows[0]
    # 22 000 kWh × 0,0811 = 1 784,2 kg CO₂e
    assert premiere["carbon_kg"] == Decimal("1784.200")
    assert premiere["carbon_status"] == "calcule"
    assert premiere["carbon_source"] == facteur_elec.source_name
    assert report.stats["with_carbon"] == 1
    # La seconde ligne n'a pas de facteur : toujours aucune estimation inventée
    assert report.rows[1]["carbon_kg"] is None
    assert report.stats["without_carbon"] == 1


def test_unite_incompatible_refusee(csv_file, facteur_elec):
    contenu = "Date;Fournisseur;Montant HT;Unité;Quantité;Code facteur\n04/03/2026;Fournisseur;1000;kg;500;ELEC-RESEAU-MA\n"
    parsed = parse_file(csv_file(contenu), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    report = validate_rows(parsed, mapping, {"ELEC-RESEAU-MA": facteur_elec}, set())
    assert report.rows[0]["carbon_kg"] is None
    assert any("incompatible" in issue.message for issue in report.warnings())


def test_facteur_inconnu_signale(csv_file):
    contenu = "Date;Fournisseur;Montant HT;Unité;Quantité;Code facteur\n04/03/2026;Fournisseur;1000;kWh;500;FACTEUR-INEXISTANT\n"
    parsed = parse_file(csv_file(contenu), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    report = validate_rows(parsed, mapping, {}, set())
    assert any("introuvable dans le catalogue" in issue.message for issue in report.warnings())
    assert report.rows[0]["carbon_kg"] is None


def test_dates_et_montants_invalides_signales(csv_file):
    parsed = parse_file(csv_file(CSV_AVEC_ERREURS), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    report = validate_rows(parsed, mapping, {}, set())

    messages = [issue.message for issue in report.errors()]
    assert any("Date illisible ou manquante" in message for message in messages)
    assert any("Montant HT négatif" in message for message in messages)
    assert any("Aucun montant exploitable" in message for message in messages)

    # Une catégorie inconnue est un avertissement (reclassée), pas un blocage
    warnings = [issue.message for issue in report.warnings()]
    assert any("non reconnue" in message for message in warnings)
    assert report.stats["errors"] >= 3
    assert report.stats["valid"] <= 1


def test_controle_des_doublons(csv_file):
    parsed = parse_file(csv_file(CSV_DOUBLON), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)

    report = validate_rows(parsed, mapping, {}, set())
    assert report.stats["duplicates"] == 1
    statuts = [row["status"] for row in report.preview]
    assert "doublon" in statuts
    assert len(report.rows) == 1  # le doublon est écarté par défaut

    avec_doublons = validate_rows(parsed, mapping, {}, set(), include_duplicates=True)
    assert len(avec_doublons.rows) == 2
    assert avec_doublons.stats["duplicates"] == 1


def test_doublon_avec_lexistant_ecarte(csv_file):
    """Un doublon déjà présent en base (clé fournie) est signalé et écarté."""
    parsed = parse_file(csv_file(CSV_VALIDE), "depenses.csv")
    mapping = suggest_mapping(parsed.columns)
    premiere = validate_rows(parsed, mapping, {}, set())
    ligne = premiere.rows[0]
    cle = f"{ligne['expense_date'].isoformat()}|{ligne['supplier'].lower()}|{ligne['amount_ht']}"

    second = validate_rows(parsed, mapping, {}, {cle})
    assert len(second.rows) == 1  # la ligne déjà connue est ignorée
    assert second.stats["duplicates"] == 1


def test_colonnes_obligatoires_manquantes():
    parsed = ParsedFile(columns=["Fournisseur", "Montant HT"], rows=[], total_rows=0)
    with pytest.raises(ValidationError):
        validate_rows(parsed, {"supplier": "Fournisseur", "amount_ht": "Montant HT"}, {}, set())
    with pytest.raises(ValidationError):
        validate_rows(parsed, {"date": "Fournisseur"}, {}, set())
