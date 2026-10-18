"""CarbonLedger AI — application de pilotage financier et carbone pour PME.

Architecture (séparation des responsabilités) :

- ``app.calc``      : couche de calcul déterministe, sans dépendance à l'interface
                      ni à l'IA (coûts, émissions, comparaisons, scénarios,
                      arbitrage, sensibilité). Entièrement testée (``tests/``).
- ``app.models``    : modèle de données (SQLAlchemy, SQLite par défaut,
                      PostgreSQL en production).
- ``app.services``  : services applicatifs (import CSV/Excel, données de
                      démonstration, rapports PDF, Copilot, journal d'audit).
- ``app.routers``   : routes HTTP (FastAPI) rendues côté serveur (Jinja2) +
                      points d'API JSON pour le recalcul en direct.
- ``app.templates`` : interface utilisateur (français, devise MAD).
"""

__version__ = "0.9.0"
