"""Référentiels métier (libellés français) partagés par l'ensemble de l'application."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Catégories de dépenses (libellé affiché -> code stocké)
# ---------------------------------------------------------------------------
EXPENSE_CATEGORIES: dict[str, str] = {
    "energie": "Énergie",
    "transport": "Transport",
    "achats": "Achats et matières premières",
    "equipements": "Équipements",
    "voyages": "Voyages professionnels",
    "services": "Services",
    "dechets": "Déchets",
    "autres": "Autres dépenses",
}

# Catégories du registre carbone (activités génératrices d'émissions)
CARBON_CATEGORIES: dict[str, str] = {
    "energie": "Énergie (combustion et électricité)",
    "transport": "Transport et déplacements",
    "achats": "Achats et matières premières",
    "dechets": "Déchets",
    "services": "Services",
    "equipements": "Équipements",
    "autres": "Autres postes",
}

VERIFICATION_STATUSES: dict[str, str] = {
    "a_verifier": "À vérifier",
    "verifiee": "Vérifiée",
    "rejetee": "Rejetée",
}

# Statut d'une donnée carbone : la distinction est essentielle pour ne pas
# confondre une mesure avec une simple estimation.
CARBON_STATUSES: dict[str, str] = {
    "mesure": "Mesuré",
    "calcule": "Calculé",
    "estime": "Estimé",
}

EMISSION_METHODS: dict[str, str] = {
    "mesure": "Mesure directe",
    "calcule": "Calcul à partir d'un facteur documenté",
    "estime": "Estimation à partir d'activité",
    "monetaire": "Estimation monétaire (approximative)",
}

CONFIDENCE_LEVELS: dict[str, str] = {
    "haute": "Haute",
    "moyenne": "Moyenne",
    "faible": "Faible",
}

PROJECT_STATUSES: dict[str, str] = {
    "brouillon": "Brouillon",
    "enregistree": "Enregistrée",
    "archivee": "Archivée",
}

PRIORITIES: dict[str, str] = {
    "cout": "Réduire les coûts totaux",
    "tresorerie": "Préserver la trésorerie à court terme",
    "emissions": "Réduire les émissions",
    "equilibre": "Compromis équilibré (coût et émissions)",
}

MEMBER_ROLES: dict[str, str] = {
    "proprietaire": "Propriétaire",
    "administrateur": "Administrateur",
    "membre": "Membre",
    "lecteur": "Lecteur",
}

SCENARIO_KINDS: dict[str, str] = {
    "base": "Scénario de base",
    "optimiste": "Scénario optimiste",
    "defavorable": "Scénario défavorable",
    "personnalise": "Scénario personnalisé",
}

# Unités d'activité reconnues (familles pour conversions, voir app.calc.units)
UNITS: dict[str, str] = {
    "kWh": "kilowattheure",
    "MWh": "mégawattheure",
    "GJ": "gigajoule",
    "L": "litre",
    "m3": "mètre cube",
    "kg": "kilogramme",
    "t": "tonne",
    "km": "kilomètre",
    "t.km": "tonne-kilomètre",
    "passager.km": "passager-kilomètre",
    "m2": "mètre carré",
    "unite": "unité",
    "nuit": "nuitée",
    "forfait": "forfait",
    "MAD": "dirham",
}

SCOPES: dict[str, str] = {
    "1": "Scope 1 — émissions directes",
    "2": "Scope 2 — énergie importée",
    "3": "Scope 3 — chaîne de valeur",
}

PERIOD_PRESETS: dict[str, str] = {
    "mois": "Mois en cours",
    "mois_precedent": "Mois précédent",
    "trimestre": "Trimestre en cours",
    "annee": "Année en cours",
    "12_mois": "12 derniers mois",
    "tout": "Tout l'historique",
    "personnalise": "Période personnalisée",
}

# Rôles autorisés à modifier les données (contrôle vérifié côté serveur)
WRITE_ROLES = {"proprietaire", "administrateur", "membre"}
ADMIN_ROLES = {"proprietaire", "administrateur"}
