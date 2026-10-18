"""Import de dépenses (CSV / Excel) en quatre étapes.

1. Import du fichier (contrôles d'extension et de taille).
2. Prévisualisation des lignes.
3. Correspondance des colonnes vers les champs de l'application.
4. Vérification des données (erreurs, avertissements, doublons) puis
   confirmation.

Règle carbone : aucun facteur d'émission n'est attribué automatiquement.
Une estimation n'est produite que si le fichier fournit une quantité, une
unité compatible avec le facteur reconnu et, le cas échéant, son code.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.dashboard import parse_date
from ..calc.emissions import compute_emissions_kg, status_from_method
from ..calc.formatting import to_decimal
from ..calc.units import are_compatible, canonical_unit, convert
from ..enums import EXPENSE_CATEGORIES, VERIFICATION_STATUSES
from ..errors import ValidationError
from ..models import CarbonRecord, EmissionFactor, Expense

# Champ de l'application -> (libellé, obligatoire, aide)
APP_FIELDS: dict[str, tuple[str, bool, str]] = {
    "date": ("Date", True, "Formats acceptés : JJ/MM/AAAA, AAAA-MM-JJ, JJ-MM-AAAA."),
    "category": ("Catégorie de dépense", False, "Sinon : « Autres dépenses » avec avertissement."),
    "supplier": ("Fournisseur", False, ""),
    "description": ("Description", False, ""),
    "amount_ht": ("Montant HT", False, "Montant hors taxes."),
    "vat_amount": ("Montant de TVA", False, ""),
    "amount_ttc": ("Montant TTC", False, "Utilisé si le HT est absent (avec avertissement)."),
    "quantity": ("Quantité ou unité d'activité", False, "Nécessaire pour estimer les émissions."),
    "unit": ("Unité de la quantité", False, "kWh, L, km, kg, t, m3, t.km…"),
    "factor_code": ("Code du facteur d'émission", False, "Doit correspondre à un facteur du catalogue ou de votre organisation."),
    "emission_factor_value": ("Facteur du fichier (kg CO₂e par unité)", False, "Donnée fournie par vous : signalée comme estimée, source « fichier importé »."),
    "emissions_source": ("Source de la donnée carbone", False, ""),
    "verification_status": ("Statut de vérification", False, "À vérifier / Vérifiée / Rejetée."),
}

# Synonymes de colonnes pour la détection automatique
COLUMN_SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "date de la depense", "date depense", "jour", "date facture", "date paiement"],
    "category": ["categorie", "category", "type de depense", "poste", "nature"],
    "supplier": ["fournisseur", "supplier", "prestataire", "vendeur", "beneficiaire"],
    "description": ["description", "libelle", "designation", "objet", "commentaire"],
    "amount_ht": ["montant ht", "ht", "total ht", "montant hors taxes", "prix ht", "amount ht", "montant"],
    "vat_amount": ["tva", "montant tva", "vat", "tva mad"],
    "amount_ttc": ["ttc", "montant ttc", "total ttc", "amount ttc", "prix ttc"],
    "quantity": ["quantite", "quantité", "quantity", "qte", "consommation", "volume"],
    "unit": ["unite", "unité", "unit", "mesure"],
    "factor_code": ["code facteur", "facteur", "code facteur emission", "fe", "emission factor"],
    "emission_factor_value": ["facteur kgco2e", "kgco2e par unite", "valeur facteur", "fe valeur"],
    "emissions_source": ["source", "source carbone", "source emission", "source donnee carbone"],
    "verification_status": ["statut", "statut verification", "verification", "status"],
}

CATEGORY_LOOKUP: dict[str, str] = {}


def _slug(text: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_text.lower().replace("’", "'").split())


def _init_category_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for code, label in EXPENSE_CATEGORIES.items():
        lookup[_slug(label)] = code
        lookup[_slug(code.replace("_", " "))] = code
    extra = {
        "carburant": "transport", "essence": "transport", "gasoil": "transport", "diesel": "transport",
        "electricite": "energie", "eau": "services", "loyer": "services", "assurance": "services",
        "matieres premieres": "achats", "materiel": "equipements", "machines": "equipements",
        "voyage": "voyages", "deplacement": "voyages", "hotel": "voyages",
        "poubelle": "dechets", "traitement des dechets": "dechets",
    }
    lookup.update(extra)
    return lookup


CATEGORY_LOOKUP = _init_category_lookup()

STATUS_LOOKUP = {
    "a verifier": "a_verifier", "à verifier": "a_verifier", "a_verifier": "a_verifier",
    "verifiee": "verifiee", "verifie": "verifiee", "vérifiée": "verifiee", "ok": "verifiee",
    "rejetee": "rejetee", "rejete": "rejetee",
}


@dataclass
class ParsedFile:
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    warnings: list[str] = field(default_factory=list)
    sheet_name: str = ""


@dataclass
class RowIssue:
    row: int
    level: str  # erreur | avertissement
    message: str
    field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "level": self.level, "message": self.message, "field": self.field}


@dataclass
class ValidationReport:
    rows: list[dict[str, Any]] = field(default_factory=list)          # lignes normalisées prêtes à l'import
    issues: list[RowIssue] = field(default_factory=list)
    preview: list[dict[str, Any]] = field(default_factory=list)       # statut par ligne pour l'affichage
    stats: dict[str, int] = field(default_factory=dict)

    def errors(self) -> list[RowIssue]:
        return [issue for issue in self.issues if issue.level == "erreur"]

    def warnings(self) -> list[RowIssue]:
        return [issue for issue in self.issues if issue.level == "avertissement"]


def parse_file(path: Path, filename: str, max_rows: int = 5000) -> ParsedFile:
    """Étape 1-2 : lit le fichier et renvoie colonnes + lignes brutes."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return _parse_csv(path, max_rows)
    if suffix in {".xlsx", ".xlsm"}:
        return _parse_xlsx(path, max_rows)
    raise ValidationError("Format non pris en charge : utilisez un fichier CSV ou Excel (.xlsx).")


def _parse_csv(path: Path, max_rows: int) -> ParsedFile:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValidationError("Impossible de lire le fichier CSV (encodage non reconnu).")
    sample = text[:4096]
    delimiter = ";"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delimiter = dialect.delimiter
    except csv.Error:
        if sample.count(",") > sample.count(";"):
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows_raw = [row for row in reader if any(str(cell).strip() for cell in row)]
    if not rows_raw:
        raise ValidationError("Le fichier ne contient aucune ligne exploitable.")
    header = [str(cell).strip() for cell in rows_raw[0]]
    data_rows = rows_raw[1:]
    warnings: list[str] = []
    if len(data_rows) > max_rows:
        warnings.append(f"Fichier tronqué aux {max_rows} premières lignes (sur {len(data_rows)}).")
        data_rows = data_rows[:max_rows]
    rows = []
    for index, raw_row in enumerate(data_rows, start=2):
        row = {}
        for col_index, column in enumerate(header):
            row[column] = raw_row[col_index].strip() if col_index < len(raw_row) else ""
        row["__ligne__"] = index
        rows.append(row)
    return ParsedFile(columns=header, rows=rows, total_rows=len(rows), warnings=warnings)


def _parse_xlsx(path: Path, max_rows: int) -> ParsedFile:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # pragma: no cover - dépend du fichier
        raise ValidationError(f"Fichier Excel illisible : {exc}") from exc
    sheet = workbook[workbook.sheetnames[0]]
    rows_iter = sheet.iter_rows(values_only=True)
    header_raw = next(rows_iter, None)
    if header_raw is None:
        raise ValidationError("Le classeur ne contient aucune ligne d'en-tête.")
    header = [str(cell).strip() if cell is not None else f"Colonne {index + 1}" for index, cell in enumerate(header_raw)]
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, raw_row in enumerate(rows_iter, start=2):
        if raw_row is None or all(cell is None or str(cell).strip() == "" for cell in raw_row):
            continue
        if len(rows) >= max_rows:
            warnings.append(f"Fichier tronqué aux {max_rows} premières lignes.")
            break
        row = {}
        for col_index, column in enumerate(header):
            value = raw_row[col_index] if col_index < len(raw_row) else None
            row[column] = value
        row["__ligne__"] = index
        rows.append(row)
    workbook.close()
    return ParsedFile(columns=header, rows=rows, total_rows=len(rows), warnings=warnings, sheet_name=sheet.title)


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    """Étape 3 : proposition de correspondance colonnes -> champs."""
    mapping: dict[str, str] = {}
    normalized = {_slug(column): column for column in columns if column}
    for field_name, synonyms in COLUMN_SYNONYMS.items():
        for synonym in synonyms:
            slug = _slug(synonym)
            if slug in normalized:
                mapping[field_name] = normalized[slug]
                break
    return mapping


def _lookup_category(value: Any) -> tuple[str, bool]:
    if value in (None, ""):
        return "autres", False
    slug = _slug(value)
    if slug in CATEGORY_LOOKUP:
        return CATEGORY_LOOKUP[slug], False
    for code, label in EXPENSE_CATEGORIES.items():
        if slug in _slug(label):
            return code, False
    return "autres", True


def _lookup_status(value: Any) -> str:
    if value in (None, ""):
        return "a_verifier"
    return STATUS_LOOKUP.get(_slug(value), "a_verifier")


def validate_rows(
    parsed: ParsedFile,
    mapping: dict[str, str],
    factors_by_code: dict[str, Any],
    existing_keys: set[str],
    *,
    include_duplicates: bool = False,
) -> ValidationReport:
    """Étape 4 : valide, normalise et détecte erreurs / avertissements / doublons."""
    report = ValidationReport()
    if "date" not in mapping:
        raise ValidationError("La colonne « Date » doit être associée à un champ du fichier.")
    if not ({"amount_ht", "amount_ttc"} & set(mapping)):
        raise ValidationError("Associez au moins un montant (HT ou TTC).")

    seen_keys: set[str] = set()
    valid_count = error_count = warning_count = duplicate_count = carbon_count = 0
    max_issues = 400

    for row in parsed.rows:
        line = int(row.get("__ligne__") or 0)
        issues_row: list[RowIssue] = []

        def value(field_name: str) -> Any:
            column = mapping.get(field_name)
            return row.get(column) if column else None

        raw_date = value("date")
        date_value = parse_date(raw_date)
        if date_value is None:
            issues_row.append(RowIssue(line, "erreur", f"Date illisible ou manquante : « {raw_date} ».", "date"))

        amount_ht = to_decimal(value("amount_ht"))
        vat_amount = to_decimal(value("vat_amount")) or Decimal("0")
        amount_ttc = to_decimal(value("amount_ttc"))

        if amount_ht is None and amount_ttc is not None:
            amount_ht = amount_ttc - vat_amount
            issues_row.append(
                RowIssue(line, "avertissement", "Montant HT absent : calculé à partir du TTC et de la TVA.", "amount_ht")
            )
        elif amount_ht is None:
            issues_row.append(RowIssue(line, "erreur", "Aucun montant exploitable (HT ou TTC requis).", "amount_ht"))
        if amount_ht is not None and amount_ht < 0:
            issues_row.append(RowIssue(line, "erreur", "Montant HT négatif : vérifiez la ligne.", "amount_ht"))

        if amount_ht is not None and amount_ttc is None:
            amount_ttc = amount_ht + vat_amount

        category, category_guessed = _lookup_category(value("category"))
        if category_guessed:
            issues_row.append(
                RowIssue(
                    line,
                    "avertissement",
                    f"Catégorie « {value('category')} » non reconnue : classée dans « Autres dépenses ».",
                    "category",
                )
            )

        status = _lookup_status(value("verification_status"))
        supplier = str(value("supplier") or "").strip()
        description = str(value("description") or "").strip()
        if not description and not supplier:
            issues_row.append(
                RowIssue(line, "avertissement", "Ni description ni fournisseur : ligne difficile à tracer.", "description")
            )

        # --- Estimation carbone : uniquement si les informations sont suffisantes ---
        quantity = to_decimal(value("quantity"))
        unit_raw = value("unit")
        unit = canonical_unit(unit_raw) if unit_raw not in (None, "") else None
        factor_code = str(value("factor_code") or "").strip()
        factor_value = to_decimal(value("emission_factor_value"))
        carbon_plan: dict[str, Any] | None = None

        if factor_code:
            factor = factors_by_code.get(factor_code) or factors_by_code.get(factor_code.upper())
            if factor is None:
                issues_row.append(
                    RowIssue(
                        line,
                        "avertissement",
                        f"Facteur « {factor_code} » introuvable dans le catalogue : carbone non estimé pour cette ligne.",
                        "factor_code",
                    )
                )
            elif quantity is None:
                issues_row.append(
                    RowIssue(line, "avertissement", f"Quantité manquante : carbone non estimé (facteur {factor.code}).", "quantity")
                )
            else:
                row_unit = unit or factor.unit
                if not are_compatible(row_unit, factor.unit):
                    issues_row.append(
                        RowIssue(
                            line,
                            "avertissement",
                            f"Unité « {row_unit} » incompatible avec le facteur {factor.code} ({factor.unit}) : carbone non estimé.",
                            "unit",
                        )
                    )
                else:
                    converted = convert(quantity, row_unit, factor.unit)
                    carbon_plan = {
                        "factor_id": factor.id,
                        "factor_code": factor.code,
                        "quantity_base": converted,
                        "unit_base": factor.unit,
                        "kgco2e": compute_emissions_kg(converted, factor.kgco2e_per_unit),
                        "method": factor.method,
                        "status": status_from_method(factor.method),
                        "confidence": factor.confidence,
                        "source": factor.source_name,
                    }
        elif factor_value is not None and unit:
            carbon_plan = {
                "factor_id": None,
                "factor_code": "",
                "quantity_base": quantity,
                "unit_base": unit,
                "kgco2e": compute_emissions_kg(quantity or Decimal("0"), factor_value),
                "method": "estime",
                "status": "estime",
                "confidence": "faible",
                "source": str(value("emissions_source") or "Fichier importé (facteur fourni dans le fichier)"),
            }
            issues_row.append(
                RowIssue(
                    line,
                    "avertissement",
                    "Facteur fourni directement dans le fichier : estimation signalée comme telle (source : fichier importé).",
                    "emission_factor_value",
                )
            )
        elif quantity is not None and unit and not factor_code:
            issues_row.append(
                RowIssue(
                    line,
                    "avertissement",
                    "Quantité et unité présentes mais aucun facteur d'émission associé : carbone non estimé (choix explicite requis).",
                    "factor_code",
                )
            )

        # --- Doublons potentiels ---
        duplicate_key = ""
        if date_value is not None and amount_ht is not None:
            duplicate_key = f"{date_value.isoformat()}|{supplier.lower()}|{amount_ht.quantize(Decimal('0.01'))}"
            if duplicate_key in seen_keys or duplicate_key in existing_keys:
                duplicate_count += 1
                level = "avertissement"
                issues_row.append(
                    RowIssue(line, level, "Doublon potentiel détecté (même date, fournisseur et montant).", "date")
                )

        has_error = any(issue.level == "erreur" for issue in issues_row)
        has_warning = any(issue.level == "avertissement" for issue in issues_row)

        if not has_error and duplicate_key and (
            duplicate_key in seen_keys or duplicate_key in existing_keys
        ) and not include_duplicates:
            # Doublon ignoré par défaut, mais la ligne reste visible dans l'aperçu.
            report.preview.append(
                {
                    "line": line,
                    "status": "doublon",
                    "messages": [issue.message for issue in issues_row],
                    "date": date_value,
                    "supplier": supplier,
                    "description": description,
                    "amount_ht": amount_ht,
                    "amount_ttc": amount_ttc,
                    "category": category,
                    "carbon": None,
                }
            )
            if len(report.issues) < max_issues:
                report.issues.extend(issues_row)
            warning_count += 1
            if duplicate_key:
                seen_keys.add(duplicate_key)
            continue

        if has_error:
            error_count += 1
            if len(report.issues) < max_issues:
                report.issues.extend(issues_row)
            report.preview.append(
                {
                    "line": line,
                    "status": "erreur",
                    "messages": [issue.message for issue in issues_row],
                    "date": date_value,
                    "supplier": supplier,
                    "description": description,
                    "amount_ht": amount_ht,
                    "amount_ttc": amount_ttc,
                    "category": category,
                    "carbon": None,
                }
            )
            continue

        if has_warning:
            warning_count += 1
            # Les avertissements des lignes reprises doivent aussi figurer dans la
            # liste des problèmes (export de correction téléchargeable).
            if len(report.issues) < max_issues:
                report.issues.extend(issues_row)
        if carbon_plan:
            carbon_count += 1
        valid_count += 1
        if duplicate_key:
            seen_keys.add(duplicate_key)

        normalized = {
            "line": line,
            "expense_date": date_value,
            "category": category,
            "supplier": supplier,
            "description": description,
            "amount_ht": amount_ht.quantize(Decimal("0.01")),
            "vat_amount": vat_amount.quantize(Decimal("0.01")),
            "amount_ttc": (amount_ttc or Decimal("0")).quantize(Decimal("0.01")),
            "quantity": quantity,
            "unit": unit,
            "factor_id": carbon_plan["factor_id"] if carbon_plan else None,
            "factor_code": carbon_plan["factor_code"] if carbon_plan else "",
            "carbon_kg": carbon_plan["kgco2e"] if carbon_plan else None,
            "carbon_status": carbon_plan["status"] if carbon_plan else None,
            "carbon_method": carbon_plan["method"] if carbon_plan else None,
            "carbon_confidence": carbon_plan["confidence"] if carbon_plan else None,
            "carbon_source": carbon_plan["source"] if carbon_plan else "",
            "carbon_quantity_base": carbon_plan["quantity_base"] if carbon_plan else None,
            "carbon_unit_base": carbon_plan["unit_base"] if carbon_plan else None,
            "verification_status": status,
            "warnings": [issue.message for issue in issues_row],
        }
        report.rows.append(normalized)
        if len(report.preview) < 500:
            report.preview.append(
                {
                    "line": line,
                    "status": "avertissement" if has_warning else "ok",
                    "messages": [issue.message for issue in issues_row],
                    "date": date_value,
                    "supplier": supplier,
                    "description": description,
                    "amount_ht": amount_ht,
                    "amount_ttc": amount_ttc,
                    "category": category,
                    "carbon": float(carbon_plan["kgco2e"]) if carbon_plan else None,
                }
            )

    report.stats = {
        "total": len(parsed.rows),
        "valid": valid_count,
        "errors": error_count,
        "warnings": warning_count,
        "duplicates": duplicate_count,
        "with_carbon": carbon_count,
        "without_carbon": valid_count - carbon_count,
    }
    return report


def rows_to_csv(issues: list[RowIssue]) -> str:
    """Export CSV des problèmes détectés (pour correction hors application)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["ligne", "niveau", "champ", "message"])
    for issue in issues:
        writer.writerow([issue.row, issue.level, issue.field, issue.message])
    return buffer.getvalue()


def duplicate_keys_for_expenses(expenses) -> set[str]:
    """Clés de doublons des dépenses existantes (date | fournisseur | montant HT)."""
    keys: set[str] = set()
    for expense in expenses:
        try:
            keys.add(
                f"{expense.expense_date.isoformat()}|{(expense.supplier or '').lower()}|{Decimal(expense.amount_ht).quantize(Decimal('0.01'))}"
            )
        except Exception:  # pragma: no cover - défensif
            continue
    return keys


# ---------------------------------------------------------------------------
# Étapes côté base : validation d'un lot et création des dépenses
# ---------------------------------------------------------------------------
def factors_lookup(db: OrmSession, organization_id: int) -> dict[str, Any]:
    """Facteurs disponibles : catalogue global + facteurs propres à l'organisation."""
    factors = (
        db.execute(
            select(EmissionFactor).where(
                (EmissionFactor.organization_id.is_(None)) | (EmissionFactor.organization_id == organization_id)
            )
        )
        .scalars()
        .all()
    )
    mapping: dict[str, Any] = {}
    for factor in factors:
        mapping[factor.code] = factor
        mapping[factor.code.lower()] = factor
    return mapping


def validate_batch(
    db: OrmSession,
    batch: Any,
    mapping: dict[str, str],
    *,
    include_duplicates: bool = False,
) -> ValidationReport:
    """Relit le fichier du lot et renvoie le rapport de validation complet.

    Partagé par l'assistant d'importation web et l'application Streamlit :
    mêmes règles, mêmes messages, mêmes doublons détectés.
    """
    parsed = parse_file(Path(batch.stored_path), batch.filename)
    factors = factors_lookup(db, batch.organization_id)
    existing = (
        db.execute(select(Expense).where(Expense.organization_id == batch.organization_id)).scalars().all()
    )
    existing_keys = duplicate_keys_for_expenses(existing)
    return validate_rows(parsed, mapping, factors, existing_keys, include_duplicates=include_duplicates)


def create_expenses_from_report(
    db: OrmSession,
    *,
    organization_id: int,
    user_id: int,
    report: ValidationReport,
    batch_filename: str,
) -> tuple[int, int]:
    """Crée les dépenses validées et leurs estimations carbone associées.

    Renvoie ``(dépenses créées, estimations carbone créées)``. Aucune ligne
    n'est reprise sans avoir passé l'étape de validation.
    """
    created = 0
    carbon_created = 0
    for row in report.rows:
        expense = Expense(
            organization_id=organization_id,
            expense_date=row["expense_date"],
            category=row["category"] if row["category"] in EXPENSE_CATEGORIES else "autres",
            supplier=row["supplier"],
            description=row["description"] or f"Import {batch_filename} (ligne {row['line']})",
            amount_ht=row["amount_ht"],
            vat_amount=row["vat_amount"],
            amount_ttc=row["amount_ttc"],
            quantity=row["quantity"],
            unit=row["unit"],
            emission_factor_id=row["factor_id"],
            carbon_source_note=row["carbon_source"] or "Carbone non estimé : données insuffisantes à l'import.",
            verification_status=row["verification_status"] if row["verification_status"] in VERIFICATION_STATUSES else "a_verifier",
            is_demo=False,
            created_by_id=user_id,
        )
        db.add(expense)
        db.flush()
        created += 1
        if row["carbon_kg"] is not None:
            db.add(
                CarbonRecord(
                    organization_id=organization_id,
                    expense_id=expense.id,
                    category=row["category"],
                    period_start=row["expense_date"].replace(day=1),
                    period_end=row["expense_date"],
                    activity_quantity=row["carbon_quantity_base"] or (row["quantity"] or Decimal("0")),
                    activity_unit=row["carbon_unit_base"] or (row["unit"] or ""),
                    emission_factor_id=row["factor_id"],
                    method=row["carbon_method"] or "estime",
                    kgco2e=row["carbon_kg"],
                    status=row["carbon_status"] or status_from_method(row["carbon_method"] or "estime"),
                    confidence=row["carbon_confidence"] or "faible",
                    notes=f"Import « {batch_filename} » (ligne {row['line']}). "
                          + (f"Source : {row['carbon_source']}." if row["carbon_source"] else ""),
                    is_demo=False,
                )
            )
            carbon_created += 1
    return created, carbon_created
