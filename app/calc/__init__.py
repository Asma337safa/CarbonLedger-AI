"""Couche de calcul déterministe.

Aucune dépendance à l'interface, à la base de données ou à l'IA : ces
fonctions sont pures, documentées et couvertes par ``tests/``.
"""

from . import (  # noqa: F401
    arbitration,
    dashboard,
    decision,
    emissions,
    formatting,
    scenarios,
    sensitivity,
    units,
)

__all__ = [
    "arbitration",
    "dashboard",
    "decision",
    "emissions",
    "formatting",
    "scenarios",
    "sensitivity",
    "units",
]
