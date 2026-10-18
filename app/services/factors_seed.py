"""Catalogue initial de facteurs d'émission documentés.

Règles appliquées :
- chaque facteur précise sa **source**, son **unité**, son **périmètre
  géographique**, sa **date de validité** et sa **version** lorsqu'elles sont
  connues ;
- les valeurs dérivées (combustibles) affichent leur **formule de calcul**
  dans ``calculation_note`` afin d'être vérifiables ;
- les valeurs « indicatives » sont explicitement signalées et leur niveau de
  confiance est abaissé : l'application ne prétend jamais qu'un facteur est
  certifié pour une entreprise donnée ;
- aucune dépense n'est associée automatiquement à un facteur : la sélection
  reste un acte explicite de l'utilisateur.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..db import session_scope
from ..models import EmissionFactor

# Valeurs de référence IPCC 2006 (Guidelines for National GHG Inventories, vol. 2)
IPCC_URL = "https://www.ipcc-nggip.iges.or.jp/public/2006gl/vol2.html"
ADEME_URL = "https://base-empreinte.ademe.fr/"

CATALOG: list[dict[str, Any]] = [
    {
        "code": "ELEC-RESEAU-MA",
        "label": "Électricité — réseau marocain",
        "category": "energie",
        "unit": "kWh",
        "scope": "2",
        "method": "calcule",
        "kgco2e_per_unit": "0.7",
        "source_name": "ADEME Base Empreinte — électricité Maroc (valeur indicative)",
        "source_url": ADEME_URL,
        "source_version": "Base Empreinte, mix électrique Maroc (valeur d'ordre de grandeur)",
        "geography": "MA",
        "valid_from": date(2022, 1, 1),
        "valid_until": None,
        "confidence": "moyenne",
        "calculation_note": (
            "Ordre de grandeur du contenu CO₂e du kWh du réseau marocain (production + pertes réseau). "
            "Valeur indicative : vérifiez le facteur en vigueur dans la Base Empreinte (ADEME), "
            "chez votre fournisseur d'électricité ou à l'ONEE, puis remplacez ce facteur si nécessaire."
        ),
    },
    {
        "code": "GAZOLE-L",
        "label": "Gazole (diesel) — combustion",
        "category": "energie",
        "unit": "L",
        "scope": "1",
        "method": "calcule",
        "kgco2e_per_unit": "2.652",
        "source_name": "IPCC 2006, Lignes directrices, vol. 2 (Ch. 2, valeurs par défaut)",
        "source_url": IPCC_URL,
        "source_version": "IPCC 2006 vol. 2 — diesel, CO₂ combustion",
        "geography": "INT",
        "valid_from": date(2006, 1, 1),
        "valid_until": None,
        "confidence": "haute",
        "calculation_note": (
            "Calcul : 74,1 kgCO₂/GJ × 42,6 GJ/t ÷ 0,84 kg/L = 2,652 kgCO₂e/L. "
            "Pouvoir calorifique inférieur et densité selon valeurs par défaut IPCC 2006. "
            "Émissions de combustion uniquement (hors amont)."
        ),
    },
    {
        "code": "ESSENCE-L",
        "label": "Essence — combustion",
        "category": "energie",
        "unit": "L",
        "scope": "1",
        "method": "calcule",
        "kgco2e_per_unit": "2.272",
        "source_name": "IPCC 2006, Lignes directrices, vol. 2 (Ch. 2, valeurs par défaut)",
        "source_url": IPCC_URL,
        "source_version": "IPCC 2006 vol. 2 — essence, CO₂ combustion",
        "geography": "INT",
        "valid_from": date(2006, 1, 1),
        "valid_until": None,
        "confidence": "haute",
        "calculation_note": (
            "Calcul : 69,3 kgCO₂/GJ × 44,3 GJ/t ÷ 0,74 kg/L = 2,272 kgCO₂e/L. "
            "Émissions de combustion uniquement (hors amont)."
        ),
    },
    {
        "code": "GPL-L",
        "label": "GPL / butane-propane — combustion",
        "category": "energie",
        "unit": "L",
        "scope": "1",
        "method": "calcule",
        "kgco2e_per_unit": "1.6",
        "source_name": "IPCC 2006, Lignes directrices, vol. 2 (Ch. 2, valeurs par défaut)",
        "source_url": IPCC_URL,
        "source_version": "IPCC 2006 vol. 2 — GPL, CO₂ combustion",
        "geography": "INT",
        "valid_from": date(2006, 1, 1),
        "valid_until": None,
        "confidence": "moyenne",
        "calculation_note": (
            "Calcul : 63,1 kgCO₂/GJ × 46,1 GJ/t × 0,55 kg/L ≈ 1,60 kgCO₂e/L. "
            "La densité du GPL varie : ajustez si votre fournisseur fournit une valeur précise."
        ),
    },
    {
        "code": "GAZ-NAT-kWh",
        "label": "Gaz naturel — combustion (PCI)",
        "category": "energie",
        "unit": "kWh",
        "scope": "1",
        "method": "calcule",
        "kgco2e_per_unit": "0.202",
        "source_name": "IPCC 2006, Lignes directrices, vol. 2 (Ch. 2, valeurs par défaut)",
        "source_url": IPCC_URL,
        "source_version": "IPCC 2006 vol. 2 — gaz naturel, CO₂ combustion",
        "geography": "INT",
        "valid_from": date(2006, 1, 1),
        "valid_until": None,
        "confidence": "haute",
        "calculation_note": (
            "Calcul : 56,1 kgCO₂/GJ ÷ 3,6 MJ/kWh = 0,202 kgCO₂e/kWh (base PCI). "
            "Si votre facture est en m³, saisissez la quantité en kWh correspondante ou créez un facteur par m³."
        ),
    },
    {
        "code": "EAU-M3",
        "label": "Eau potable — réseau",
        "category": "services",
        "unit": "m3",
        "scope": "3",
        "method": "estime",
        "kgco2e_per_unit": "0.3",
        "source_name": "Ordre de grandeur ADEME (valeur indicative)",
        "source_url": ADEME_URL,
        "source_version": "valeur indicative à vérifier",
        "geography": "INT",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": (
            "Ordre de grandeur usuel de 0,2 à 0,4 kgCO₂e/m³ (production, traitement, distribution). "
            "Valeur indicative : remplacez-la par le facteur de votre régie si disponible."
        ),
    },
    {
        "code": "DECHETS-T",
        "label": "Déchets — enfouissement (mélange)",
        "category": "dechets",
        "unit": "t",
        "scope": "3",
        "method": "estime",
        "kgco2e_per_unit": "600",
        "source_name": "Ordre de grandeur (valeur indicative, très variable)",
        "source_url": "",
        "source_version": "valeur indicative à vérifier",
        "geography": "INT",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": (
            "Les émissions de l'enfouissement dépendent fortement de la composition des déchets et de la "
            "captation du méthane : ordre de grandeur 0,5 à 1,2 tCO₂e/t. À documenter avec votre prestataire."
        ),
    },
    {
        "code": "PAPIER-KG",
        "label": "Papier bureautique vierge",
        "category": "achats",
        "unit": "kg",
        "scope": "3",
        "method": "estime",
        "kgco2e_per_unit": "0.92",
        "source_name": "Ordre de grandeur ADEME (valeur indicative)",
        "source_url": ADEME_URL,
        "source_version": "valeur indicative à vérifier",
        "geography": "INT",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": "Ordre de grandeur usuel (~0,9 kgCO₂e/kg) pour du papier vierge, analyse de cycle de vie simplifiée.",
    },
    {
        "code": "AVION-PKM",
        "label": "Voyage aérien — par passager-kilomètre",
        "category": "voyages",
        "unit": "passager.km",
        "scope": "3",
        "method": "estime",
        "kgco2e_per_unit": "0.23",
        "source_name": "Ordre de grandeur ADEME par passager-kilomètre (valeur indicative)",
        "source_url": ADEME_URL,
        "source_version": "valeur indicative à vérifier",
        "geography": "INT",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": (
            "Ordre de grandeur pour un vol moyen-courrier en classe économique. Les valeurs varient "
            "largement selon la distance et la classe : vérifiez auprès de votre compagnie ou d'une base reconnue."
        ),
    },
    {
        "code": "FRET-TKM",
        "label": "Fret routier — par tonne-kilomètre",
        "category": "transport",
        "unit": "t.km",
        "scope": "3",
        "method": "estime",
        "kgco2e_per_unit": "0.106",
        "source_name": "Ordre de grandeur ADEME (poids lourd, valeur indicative)",
        "source_url": ADEME_URL,
        "source_version": "valeur indicative à vérifier",
        "geography": "INT",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": (
            "Ordre de grandeur autour de 0,1 kgCO₂e/t.km pour un poids lourd 40 t. "
            "Vérifiez le facteur adapté à votre type de véhicule et taux de charge."
        ),
    },
    {
        "code": "MONETAIRE-ACHATS-1000MAD",
        "label": "Achats divers — ratio monétaire (1 000 DH)",
        "category": "achats",
        "unit": "MAD",
        "scope": "3",
        "method": "monetaire",
        "kgco2e_per_unit": "0.5",
        "source_name": "Ratio monétaire indicatif interne — à remplacer (aucune source externe)",
        "source_url": "",
        "source_version": "modèle à personnaliser",
        "geography": "MA",
        "valid_from": None,
        "valid_until": None,
        "confidence": "faible",
        "calculation_note": (
            "MÉTHODE DÉPENSE (approximative par nature) : 0,5 kgCO₂e pour 1 000 DH dépensés. "
            "Ce ratio est un simple ordre de grandeur pédagogique, sans source vérifiable : il doit être "
            "remplacé par un ratio documenté par votre organisation (ex. table monétaire sectorielle) avant "
            "tout usage sérieux. Les résultats obtenus par cette méthode sont signalés comme estimés."
        ),
    },
]


def seed_global_factors() -> int:
    """Insère le catalogue global s'il n'existe pas déjà (idempotent)."""
    inserted = 0
    with session_scope() as db:
        for entry in CATALOG:
            exists = (
                db.query(EmissionFactor)
                .filter(EmissionFactor.organization_id.is_(None), EmissionFactor.code == entry["code"])
                .first()
            )
            if exists:
                continue
            db.add(
                EmissionFactor(
                    organization_id=None,
                    is_demo=False,
                    **entry,
                )
            )
            inserted += 1
    return inserted
