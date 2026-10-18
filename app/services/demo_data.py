"""Jeu de données de démonstration.

Toutes les données sont fictives et marquées ``is_demo=True`` : elles
apparaissent avec un badge « Démonstration » dans l'interface et peuvent
être supprimées en un clic depuis les paramètres. Aucune donnée réelle
d'entreprise, de fournisseur ou de facteur n'est inventée : les facteurs
utilisés proviennent du catalogue documenté.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..calc.arbitration import arbitrate
from ..calc.decision import OptionInput, compare_options
from ..calc.emissions import compute_emissions_kg, status_from_method
from ..models import (
    CarbonRecord,
    DecisionOption,
    DecisionProject,
    EmissionFactor,
    Expense,
    Organization,
    Recommendation,
    Scenario,
)

DEMO_TAG = "démonstration"

# (mois d'ancienneté, jour, catégorie, fournisseur, description, HT, TVA %, quantité, unité, code facteur, statut)
DEMO_EXPENSES: list[tuple] = [
    (5, 6, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "7420.00", "20", "10600", "kWh", "ELEC-RESEAU-MA", "verifiee"),
    (5, 12, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "2860.00", "20", "1080", "L", "GAZOLE-L", "verifiee"),
    (5, 18, "achats", "Fournitures Bureau Plus (démo)", "Fournitures de bureau et papier (démo)", "3150.00", "20", "820", "kg", "PAPIER-KG", "a_verifier"),
    (5, 24, "services", "Prestataire Comptable (démo)", "Honoraires comptables mensuels (démo)", "4200.00", "20", None, None, None, "verifiee"),
    (4, 5, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "7890.00", "20", "11270", "kWh", "ELEC-RESEAU-MA", "verifiee"),
    (4, 9, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "3120.00", "20", "1177", "L", "GAZOLE-L", "verifiee"),
    (4, 15, "achats", "Acier Maghreb (démo)", "Matières premières — profilés acier (démo)", "18400.00", "20", "4200", "kg", None, "a_verifier"),
    (4, 21, "dechets", "Collecte Pro Déchets (démo)", "Évacuation déchets industriels (démo)", "1450.00", "20", "2.4", "t", "DECHETS-T", "a_verifier"),
    (3, 4, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "8030.00", "20", "11470", "kWh", "ELEC-RESEAU-MA", "verifiee"),
    (3, 11, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "2740.00", "20", "1034", "L", "GAZOLE-L", "verifiee"),
    (3, 19, "voyages", "Agence Voyages Pro (démo)", "Déplacement professionnel Casablanca–Paris (démo)", "3900.00", "20", "4800", "passager.km", "AVION-PKM", "a_verifier"),
    (3, 27, "equipements", "Techni-Équipement Maroc (démo)", "Maintenance préventive compresseur (démo)", "3600.00", "20", None, None, None, "verifiee"),
    (2, 3, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "7540.00", "20", "10770", "kWh", "ELEC-RESEAU-MA", "verifiee"),
    (2, 14, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "2980.00", "20", "1124", "L", "GAZOLE-L", "a_verifier"),
    (2, 20, "achats", "Acier Maghreb (démo)", "Matières premières — tôles (démo)", "15600.00", "20", "3600", "kg", None, "a_verifier"),
    (2, 26, "services", "Prestataire Comptable (démo)", "Honoraires comptables mensuels (démo)", "4200.00", "20", None, None, None, "verifiee"),
    (1, 8, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "8210.00", "20", "11730", "kWh", "ELEC-RESEAU-MA", "verifiee"),
    (1, 13, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "3050.00", "20", "1151", "L", "GAZOLE-L", "verifiee"),
    (1, 17, "transport", "Fret Logistique Sud (démo)", "Transport de marchandises (démo)", "6800.00", "20", "41000", "t.km", "FRET-TKM", "a_verifier"),
    (1, 23, "dechets", "Collecte Pro Déchets (démo)", "Évacuation déchets industriels (démo)", "1520.00", "20", "2.5", "t", "DECHETS-T", "a_verifier"),
    (0, 4, "energie", "Atlas Énergie (démo)", "Facture d'électricité — atelier (démo)", "7980.00", "20", "11400", "kWh", "ELEC-RESEAU-MA", "a_verifier"),
    (0, 9, "transport", "Méditerranée Transport (démo)", "Gasoil — camionnettes de livraison (démo)", "2910.00", "20", "1098", "L", "GAZOLE-L", "a_verifier"),
    (0, 16, "achats", "Fournitures Bureau Plus (démo)", "Fournitures de bureau et papier (démo)", "2960.00", "20", "760", "kg", "PAPIER-KG", "a_verifier"),
    (0, 22, "services", "Prestataire Comptable (démo)", "Honoraires comptables mensuels (démo)", "4200.00", "20", None, None, None, "a_verifier"),
    (0, 25, "autres", "Divers (démo)", "Frais administratifs divers (démo)", "1850.00", "20", None, None, None, "a_verifier"),
]


def _factors_by_code(db: OrmSession, organization_id: int) -> dict[str, EmissionFactor]:
    rows = (
        db.execute(
            select(EmissionFactor).where(
                (EmissionFactor.organization_id.is_(None))
                | (EmissionFactor.organization_id == organization_id)
            )
        )
        .scalars()
        .all()
    )
    return {factor.code: factor for factor in rows}


def load_demo_data(db: OrmSession, organization: Organization, created_by_id: int | None = None) -> dict[str, int]:
    """Charge (ou recharge) le jeu de démonstration pour l'organisation."""
    delete_demo_data(db, organization)
    factors = _factors_by_code(db, organization.id)
    today = date.today()
    created_expenses = 0
    created_records = 0

    for month_ago, day, category, supplier, description, ht, vat_pct, quantity, unit, factor_code, status in DEMO_EXPENSES:
        year = today.year
        month = today.month - month_ago
        while month <= 0:
            month += 12
            year -= 1
        expense_date = date(year, month, min(day, 28))
        amount_ht = Decimal(ht)
        vat_amount = (amount_ht * Decimal(vat_pct) / 100).quantize(Decimal("0.01"))
        factor = factors.get(factor_code) if factor_code else None
        expense = Expense(
            organization_id=organization.id,
            expense_date=expense_date,
            category=category,
            supplier=supplier,
            description=description,
            amount_ht=amount_ht,
            vat_amount=vat_amount,
            amount_ttc=amount_ht + vat_amount,
            quantity=Decimal(str(quantity)) if quantity is not None else None,
            unit=unit,
            emission_factor_id=factor.id if factor else None,
            carbon_source_note=(factor.source_name if factor else "Carbone non estimé : informations insuffisantes"),
            verification_status=status,
            is_demo=True,
            created_by_id=created_by_id,
        )
        db.add(expense)
        db.flush()
        created_expenses += 1

        if factor and expense.quantity is not None and expense.unit == factor.unit:
            kg = compute_emissions_kg(expense.quantity, factor.kgco2e_per_unit)
            db.add(
                CarbonRecord(
                    organization_id=organization.id,
                    expense_id=expense.id,
                    category=category,
                    period_start=expense_date.replace(day=1),
                    period_end=expense_date,
                    activity_quantity=expense.quantity,
                    activity_unit=expense.unit,
                    emission_factor_id=factor.id,
                    method=factor.method,
                    kgco2e=kg,
                    status=status_from_method(factor.method),
                    confidence=factor.confidence,
                    notes=f"Généré depuis la dépense « {description} » — donnée de démonstration.",
                    is_demo=True,
                )
            )
            created_records += 1

    projects_created = _load_demo_projects(db, organization, created_by_id)
    organization.demo_data_loaded = True
    return {
        "expenses": created_expenses,
        "carbon_records": created_records,
        "projects": projects_created,
    }


def _load_demo_projects(db: OrmSession, organization: Organization, created_by_id: int | None) -> int:
    """Projets de décision pédagogiques, dont l'exemple du cahier des charges."""
    projects: list[tuple[str, str, str, list[dict], str, str, str]] = [
        (
            "Remplacement d'une presse hydraulique (démo)",
            "Exemple pédagogique du cahier des charges : comparaison sur 5 ans hors actualisation, "
            "maintenance et valeur résiduelle non chiffrées.",
            "equipements",
            [
                {"name": "Option A — presse standard", "supplier": "Fournisseur A (démo)", "purchase_cost": "80000",
                 "annual_opex": "24000", "annual_energy_share_pct": "45", "annual_emissions_kg": "12000",
                 "emissions_basis": "estime", "confidence": "moyenne",
                 "emissions_source_note": "Estimation pédagogique (démonstration), non mesurée."},
                {"name": "Option B — presse haute efficacité", "supplier": "Fournisseur B (démo)", "purchase_cost": "95000",
                 "annual_opex": "17000", "annual_energy_share_pct": "35", "annual_emissions_kg": "7000",
                 "emissions_basis": "estime", "confidence": "moyenne",
                 "emissions_source_note": "Estimation pédagogique (démonstration), non mesurée."},
            ],
            "enregistree",
            "equilibre",
            "0",
        ),
        (
            "Choix d'un fournisseur d'équipement énergivore (démo)",
            "Cas où l'option la moins émettrice coûte plus cher : illustre le coût par tonne de CO₂e évitée.",
            "achats",
            [
                {"name": "Fournisseur standard (démo)", "supplier": "Fournisseur C (démo)", "purchase_cost": "80000",
                 "annual_opex": "24000", "annual_energy_share_pct": "50", "annual_emissions_kg": "12000",
                 "emissions_basis": "estime", "confidence": "moyenne",
                 "emissions_source_note": "Estimation pédagogique (démonstration)."},
                {"name": "Fournisseur certifié haute efficacité (démo)", "supplier": "Fournisseur D (démo)", "purchase_cost": "95000",
                 "annual_opex": "22000", "annual_energy_share_pct": "40", "annual_emissions_kg": "5000",
                 "emissions_basis": "estime", "confidence": "moyenne",
                 "emissions_source_note": "Estimation pédagogique (démonstration)."},
            ],
            "enregistree",
            "emissions",
            "1000",
        ),
        (
            "Éclairage LED de l'entrepôt (démo)",
            "Projet à l'état de brouillon : données encore incomplètes (émissions de l'option A non renseignées).",
            "energie",
            [
                {"name": "Maintenir l'éclairage actuel (démo)", "supplier": "", "purchase_cost": "0",
                 "annual_opex": "18000", "annual_energy_share_pct": "90", "annual_maintenance": "4200",
                 "annual_emissions_kg": "25000", "emissions_basis": "calcule", "confidence": "moyenne",
                 "emissions_source_note": "Calcul à partir des kWh consommés et du facteur réseau (démonstration)."},
                {"name": "Rénovation LED (démo)", "supplier": "Lumière Pro (démo)", "purchase_cost": "45000",
                 "annual_opex": "6000", "annual_energy_share_pct": "85", "annual_savings": "9500",
                 "annual_emissions_kg": "8000", "emissions_basis": "calcule", "confidence": "haute",
                 "emissions_source_note": "Calcul à partir des kWh économisés et du facteur réseau (démonstration)."},
                {"name": "Rénovation LED avec optimisation (démo)", "supplier": "Lumière Pro (démo)", "purchase_cost": "58000",
                 "annual_opex": "5200", "annual_energy_share_pct": "85", "annual_savings": "11200",
                 "annual_emissions_kg": None, "confidence": "faible",
                 "emissions_source_note": "Émissions à documenter : estimation fournisseur non fournie."},
            ],
            "brouillon",
            "cout",
            "0",
        ),
    ]

    count = 0
    for title, description, category, options_data, status, priority, carbon_price in projects:
        project = DecisionProject(
            organization_id=organization.id,
            title=title,
            description=description,
            category=category,
            horizon_years=5,
            priority=priority,
            internal_carbon_price=Decimal(carbon_price),
            status=status,
            is_demo=True,
            created_by_id=created_by_id,
        )
        db.add(project)
        db.flush()
        count += 1
        for index, option_data in enumerate(options_data):
            option = DecisionOption(
                project_id=project.id,
                sort_order=index,
                name=option_data["name"],
                supplier=option_data.get("supplier", ""),
                purchase_cost=Decimal(option_data.get("purchase_cost", "0")),
                transport_cost=Decimal(option_data.get("transport_cost", "0")),
                annual_opex=Decimal(option_data.get("annual_opex", "0")),
                annual_energy_share_pct=Decimal(option_data["annual_energy_share_pct"]) if option_data.get("annual_energy_share_pct") else None,
                annual_maintenance=Decimal(option_data.get("annual_maintenance", "0")),
                annual_savings=Decimal(option_data.get("annual_savings", "0")),
                useful_life_years=Decimal(option_data["useful_life_years"]) if option_data.get("useful_life_years") else None,
                annual_emissions_kg=Decimal(option_data["annual_emissions_kg"]) if option_data.get("annual_emissions_kg") else None,
                emissions_basis=option_data.get("emissions_basis"),
                emissions_source_note=option_data.get("emissions_source_note", ""),
                confidence=option_data.get("confidence", "moyenne"),
                notes=f"Donnée {DEMO_TAG}.",
            )
            db.add(option)
        db.flush()

        # Enregistre la recommandation du moteur pour les projets enregistrés (transparence du calcul)
        if status == "enregistree":
            inputs = [
                OptionInput.from_dict(
                    {
                        "name": option.name,
                        "supplier": option.supplier,
                        "purchase_cost": str(option.purchase_cost),
                        "annual_opex": str(option.annual_opex),
                        "annual_energy_share_pct": str(option.annual_energy_share_pct) if option.annual_energy_share_pct is not None else None,
                        "annual_maintenance": str(option.annual_maintenance),
                        "annual_savings": str(option.annual_savings),
                        "annual_emissions_kg": str(option.annual_emissions_kg) if option.annual_emissions_kg is not None else None,
                        "emissions_basis": option.emissions_basis,
                        "confidence": option.confidence,
                    },
                    key=f"o{option.id}",
                    index=index,
                )
                for index, option in enumerate(project.options)
            ]
            comparison = compare_options(inputs, project.horizon_years, carbon_price=project.internal_carbon_price)
            result = arbitrate(comparison, project.priority)
            db.add(
                Recommendation(
                    project_id=project.id,
                    priority=project.priority,
                    carbon_price=project.internal_carbon_price,
                    summary=result.recommendation_title + " " + " ".join(result.recommendation_paragraphs),
                    details=result.to_dict(),
                    created_by_id=created_by_id,
                )
            )
            db.add(
                Scenario(
                    project_id=project.id,
                    name="Scénario prudent (énergie +15 %)",
                    kind="personnalise",
                    parameters={
                        "label": "Énergie +15 %",
                        "energy_price_delta_pct": 15,
                        "savings_delta_pct": -10,
                    },
                    notes=f"Scénario {DEMO_TAG} enregistré pour illustration.",
                    is_demo=True,
                    created_by_id=created_by_id,
                )
            )
    return count


def delete_demo_data(db: OrmSession, organization: Organization) -> dict[str, int]:
    """Supprime toutes les données de démonstration de l'organisation."""
    counts = {"expenses": 0, "carbon_records": 0, "projects": 0}
    records = db.execute(
        select(CarbonRecord).where(CarbonRecord.organization_id == organization.id, CarbonRecord.is_demo.is_(True))
    ).scalars().all()
    for record in records:
        db.delete(record)
        counts["carbon_records"] += 1
    expenses = db.execute(
        select(Expense).where(Expense.organization_id == organization.id, Expense.is_demo.is_(True))
    ).scalars().all()
    for expense in expenses:
        db.delete(expense)
        counts["expenses"] += 1
    projects = db.execute(
        select(DecisionProject).where(
            DecisionProject.organization_id == organization.id, DecisionProject.is_demo.is_(True)
        )
    ).scalars().all()
    for project in projects:
        db.delete(project)
        counts["projects"] += 1
    organization.demo_data_loaded = False
    db.flush()
    return counts
