# CarbonLedger AI — État des fonctionnalités

Ce document recense, point par point, ce qui est **fait**, **partiel** ou **non
fait**, par rapport au cahier des charges. Il est volontairement franc : chaque
limite est justifiée et accompagnée d'une piste.

Légende : ✅ **Fait** (implémenté et couvert par des tests ou vérifié dans
l'application) · 🟡 **Partiel** (fonctionne, mais avec une réserve explicite) ·
⛔ **Non fait** (assumé, avec la raison).

Dernière mise à jour : octobre 2026. Vérifications : `pytest` → **115 tests
passés** ; script de bout en bout → **43 vérifications passées** (inscription,
démonstration, 8 sections, comparateur, APIs, rapports, copilot, export).

---

## Sommaire

1. [Objectif du produit](#1-objectif-du-produit)
2. [Les 8 sections de l'application](#2-les-8-sections-de-lapplication)
3. [Le comparateur de décisions (cœur du produit)](#3-le-comparateur-de-décisions-cœur-du-produit)
4. [Moteur d'arbitrage explicable](#4-moteur-darbitrage-explicable)
5. [Simulations, scénarios, sensibilité](#5-simulations-scénarios-sensibilité)
6. [Comptabilité carbone et facteurs](#6-comptabilité-carbone-et-facteurs)
7. [Import de fichiers (4 étapes)](#7-import-de-fichiers-4-étapes)
8. [Rapports et exports](#8-rapports-et-exports)
9. [Assistant IA](#9-assistant-ia)
10. [Authentification, rôles, isolation](#10-authentification-rôles-isolation)
11. [Calculs déterministes et tests](#11-calculs-déterministes-et-tests)
12. [Sécurité](#12-sécurité)
13. [Interface : palette, typographie, accessibilité](#13-interface-palette-typographie-accessibilité)
14. [Jeu de données de démonstration](#14-jeu-de-données-de-démonstration)
15. [Livrables](#15-livrables)
16. [Limites assumées et hors périmètre](#16-limites-assumées-et-hors-périmètre)

---

## 1. Objectif du produit

> Plateforme de décision financière **et** carbone pour les PME marocaines :
> savoir quelles dépenses sont engagées, quelles émissions elles représentent,
> et — surtout — **comparer des options** (machines, énergies, transports…)
> en expliquant les compromis coût / CO₂e.

| Exigence | État | Où |
|---|---|---|
| Interface en français, montants en MAD (DH) | ✅ | tous les gabarits, `app/calc/formatting.py` |
| Le comparateur de décisions est la pièce maîtresse | ✅ | section 3 ci-dessous |
| Aucun chiffre inventé (donnée absente ⇒ « non disponible » + avertissement) | ✅ | `app/calc/decision.py`, `app/calc/arbitration.py` |
| Traçabilité de chaque chiffre (source, périmètre, méthode) | ✅ | facteurs, écarts, notes de calcul affichées et exportées |
| Fonctionne **sans** dépendance à un service externe (hors Copilot facultatif) | ✅ | zéro CDN, zéro appel réseau sans clé d'API |

## 2. Les 8 sections de l'application

| # | Section | État | Contenu |
|---|---|---|---|
| 1 | **Tableau de bord** | ✅ | Dépenses HT/TVA/TTC de la période, évolution vs période précédente, répartition par catégorie, émissions de la période (mesuré / calculé / estimé), derniers enregistrements, alertes, opportunités. |
| 2 | **Dépenses** | ✅ | Création, modification, vérification (`vérifié`/`à vérifier`), suppression, filtres (période, catégorie, fournisseur, statut, texte), export CSV, estimation carbone optionnelle (quantité + unité + facteur documenté exigés). |
| 3 | **Comptabilité carbone** | ✅ | Registre d'activités, `quantité × facteur`, conversions d'unités contrôlées (kWh↔MWh, km↔t.km interdit), scopes 1/2/3, statut mesuré/calculé/estimé, source et note de calcul affichées, export CSV. |
| 4 | **Comparateur de décisions** | ✅ | Voir section 3 : *c'est la fonction la plus complète du produit*. |
| 5 | **Simulations** | ✅ | Moteurs identiques au comparateur, en mode bac à sable : hypothèses modifiables, scénarios prédéfinis, recalcul immédiat, aucun enregistrement modifié. |
| 6 | **Rapports** | ✅ | Rapport de période PDF, classeur Excel (dépenses + carbone), rapport de décision PDF, historique des rapports, téléchargement, suppression. |
| 7 | **Assistant IA** | ✅ 🟡 | Voir section 9 : mode démonstration déterministe sans clé ; appel d'une API compatible OpenAI si une clé est fournie (non exercé ici, faute de clé réelle). |
| 8 | **Paramètres** | ✅ | Organisation (ICE, secteur, effectif, prix interne du carbone), membres et rôles, invitations, catalogue de facteurs (globaux + personnalisés), configuration IA, données de démonstration, journal d'audit, export JSON, suppression d'organisation. |

Chaque section est atteignable depuis la barre de navigation latérale, protégée
par session, et isolée par organisation.

## 3. Le comparateur de décisions (cœur du produit)

Un projet contient 2 à N options, un horizon en années et des hypothèses
partagées (énergie, transport, économies, volume d'activité, facteurs
d'émission, durée d'utilisation, prix interne du carbone).

| Exigence | État | Détail / test |
|---|---|---|
| Coût total par option = acquisition + transport + Σ(fonctionnement + maintenance − économies) | ✅ | `tests/test_decision_spec.py` |
| Exemple du cahier des charges reproduit **au dirham près** | ✅ | A = 80 000 + 24 000×5 = **200 000 DH** ; B = 95 000 + 17 000×5 = **180 000 DH** |
| Émissions cumulées = annuelles × horizon | ✅ | 12 t/an → 60 t ; 7 t/an → 35 t |
| Émissions évitées | ✅ | **5 t/an**, **25 t cumulées** |
| Coût par tonne de CO₂e évitée | ✅ | `(180 000 − 200 000) ÷ 25 = −800 DH/t`, affiché **« 800,00 DH économisés par tonne évitée »** (double gain), jamais un nombre nu |
| Formule du coût par tonne affichée dans l'interface | ✅ | bloc « Règle de calcul » sur chaque page de comparaison |
| Économie / surcoût entre options | ✅ | 20 000 DH d'économie sur 5 ans |
| Délai de rattrapage (payback) | ✅ | ≈ **2,143 ans** (surcoût initial 15 000 DH vs 7 000 DH/an) |
| Trésorerie année par année (courbe) | ✅ | `cash_curve`, graphique SVG |
| Frontière de compromis (coût × émissions) | ✅ | nuage d'options + option « dominée » signalée si une autre est à la fois moins chère et moins émettrice |
| Classement selon la priorité choisie | ✅ | pondération **Coût / Carbone / Équilibré** (curseur de priorité), recalcul instantané |
| Comparaison à plus de 2 options | ✅ | paires construites autour de l'option la moins émettrice, dédoublonnées |
| Données manquantes | ✅ | émissions absentes ⇒ métriques carbone « non disponibles » avec avertissement, jamais 0 ni estimation silencieuse |
| Valeur verte négative (double gain) expliquée | ✅ | phrase dédiée : ce n'est pas une recette comptable |
| Prix interne du carbone | ✅ | appliqué comme coût additionnel **séparé**, jamais mélangé au coût d'investissement |
| Aperçu quasi temps réel à la saisie | ✅ | `POST /api/projects/compute` + `decision.js` (brouillon non enregistré) |
| Export CSV de la comparaison | ✅ | page décision → « Exporter la comparaison (CSV) » |
| Rapport de décision PDF | ✅ | annexes : options, hypothèses, scénarios, sensibilité, avertissements |

## 4. Moteur d'arbitrage explicable

Objectif : **ne pas désigner un gagnant artificiel**. Le moteur expose les
compromis, pondère selon la priorité, et explique chaque classement.

| Exigence | État | Détail |
|---|---|---|
| Classement pondéré par priorité (coût / carbone / équilibré) | ✅ | `app/calc/arbitration.py`, testé |
| Phrases d'explication par option (rang, forces, faiblesses) | ✅ | texte affiché et exporté (PDF/CSV) |
| Détection de dominance (moins chère **et** moins émettrice) | ✅ | mention explicite « favorable dans les deux dimensions » |
| Cas où le recommandé est le plus vert | ✅ | paragraphe dédié : « émissions cumulées estimées les plus faibles » |
| Cas où recommandé ≠ plus vert | ✅ | phrase de compromis + condition de bascule |
| Aucun gagnant inventé quand les données carbone manquent | ✅ | l'arbitrage bascule sur le coût et le déclare |
| Recommandation conditionnelle (« si le prix du carbone dépasse X… ») | ✅ | calculée depuis les écarts réels, pas de seuil arbitraire |

## 5. Simulations, scénarios, sensibilité

| Exigence | État | Détail |
|---|---|---|
| Scénarios prédéfinis : base / optimiste / défavorable | ✅ | `app/calc/scenarios.py`, paramètres affichés avant application |
| Chaque paramètre documenté (ce qu'il modifie) | ✅ | `ScenarioParams.description()` |
| Sensibilité : classement des hypothèses les plus influentes | 🟡 | méthode **une hypothèse à la fois** (±10 %, et ±1 an de durée), graphique « tornade ». Pas d'analyse combinée multi-variables (raison : complexité d'interprétation, choix assumé). |
| Détection « cette hypothèse peut inverser le classement » | ✅ | comparaison base / basse / haute |
| Mode bac à sable sans écriture en base | ✅ | `/simulations` et API de recalcul en lecture seule |
| Scénarios personnalisés (API `custom`) | ✅ | `run_scenarios(..., custom=[...])` ; **non exposé** dans l'interface (réservé à l'API). |

## 6. Comptabilité carbone et facteurs

| Exigence | État | Détail |
|---|---|---|
| Catalogue de facteurs **documenté** (source, version, périmètre, méthode, confiance) | ✅ | 11 facteurs globaux, `app/services/factors_seed.py` |
| Facteurs incertains signalés « indicatif » | ✅ | mention visible dans l'UI, les CSV et le PDF |
| Aucun facteur attribué automatiquement | ✅ | l'estimation exige quantité **et** unité **et** facteur |
| Facteurs propres à l'organisation, prioritaires sur les globaux | ✅ | isolés par organisation |
| Scopes 1 / 2 / 3 | ✅ | stockés, filtrables, agrégés séparément |
| Statut mesuré / calculé / estimé | ✅ | champ explicite + agrégats séparés au tableau de bord |
| Conventions d'unités strictes (aucune conversion implicite) | ✅ | `app/calc/units.py`, tests dédiés |
| Mention « à remplacer » sur le ratio monétaire | ✅ | `MONETAIRE-ACHATS-1000MAD`, libellé explicite |

## 7. Import de fichiers (4 étapes)

| Étape | État | Détail |
|---|---|---|
| 1. Téléversement | ✅ | CSV (séparateurs `;`, `,`, `\|`, tabulation) et Excel `.xlsx`, encodages UTF-8 / cp1252 / latin-1, taille limitée par `.env` |
| 2. Aperçu | ✅ | colonnes détectées, échantillon de lignes, comptage |
| 3. Correspondance | ✅ | proposition automatique (`Date`, `Montant HT`, `TVA`, `Unité`, `Quantité`, `Code facteur`…), modifiable champ par champ |
| 4. Validation et confirmation | ✅ | erreurs bloquantes vs avertissements, doublons détectés (date + fournisseur + montant), export `errors.csv`, import des seules lignes valides |
| Lignes en erreur jamais importées silencieusement | ✅ | + les avertissements des lignes acceptées figurent aussi dans `errors.csv` |
| Estimation carbone à l'import = mêmes règles que la saisie | ✅ | facteur documenté obligatoire |

## 8. Rapports et exports

| Livrable | État | Format |
|---|---|---|
| Rapport de période | ✅ | PDF (ReportLab Helvetica, accents et DH corrects) |
| Classeur de données | ✅ | XLSX (feuilles dépenses + carbone) |
| Rapport de décision | ✅ | PDF, avec formules, hypothèses, scénarios, sensibilité, avertissements |
| Historique des rapports | ✅ | liste, téléchargement, suppression |
| Export CSV dépenses / carbone / comparaison / problèmes d'import | ✅ | CSV avec séparateur `;` (Excel FR) |
| Export JSON complet de l'organisation | ✅ | Paramètres → Données (portabilité RGPD-like) |

## 9. Assistant IA

| Exigence | État | Détail |
|---|---|---|
| Répond **uniquement** à partir des données calculées de l'organisation | ✅ | contexte construit à partir des agrégats serveur, jamais d'invention |
| Sans clé d'API : mode démonstration déterministe | ✅ | réponses préétablies et exactes (coûts, émissions, comparaisons), testé |
| Avec clé : API compatible OpenAI (OpenAI, Azure, Mistral, Ollama…) | 🟡 | intégration écrite et configurable, **non exercée** dans cet environnement (aucune clé disponible). Le contrat « ne jamais inventer » repose sur le contexte fourni et les instructions du modèle. |
| Clé d'API jamais exposée au navigateur | ✅ | configuration serveur uniquement |
| Refus explicite hors périmètre | ✅ | le Copilot déclare ne pas pouvoir répondre sans données |

## 10. Authentification, rôles, isolation

| Exigence | État | Détail |
|---|---|---|
| Inscription / connexion / déconnexion | ✅ | mots de passe hachés `scrypt` (bibliothèque standard) |
| Sessions serveur | ✅ | jeton opaque haché en base, cookie `HttpOnly`, `SameSite=Lax`, durée configurable |
| Rôles : propriétaire / administrateur / membre / lecteur | ✅ | refus des écritures côté serveur, pas seulement masquage dans l'UI |
| Invitations | ✅ | lien avec jeton, page d'acceptation |
| Isolation par organisation | ✅ | filtre systématique ; tests d'isolation croisée (2 organisations) |
| Héritage du rôle « propriétaire » | ✅ | un propriétaire ne peut pas se retirer lui-même ni être retiré |

## 11. Calculs déterministes et tests

| Exigence | État | Détail |
|---|---|---|
| Couche de calcul pure, sans accès base ni réseau | ✅ | `app/calc/` (décision, arbitrage, scénarios, sensibilité, émissions, unités, formatage, tableau de bord) |
| Arithmétique en `Decimal` (pas de flottants pour l'argent) | ✅ | avec arrondi final contrôlé |
| Tests unitaires des formules | ✅ | `tests/test_decision_spec.py`, `test_arbitration.py`, `test_scenarios_sensitivity.py`, `test_dashboard_calc.py`, `test_emissions.py`, `test_units.py` |
| Tests de l'exemple chiffré du cahier des charges | ✅ | 200 000 / 180 000 / 25 t / −800 DH/t / payback 2,143 ans |
| Tests d'intégration web (inscription → import → décision → rapport) | ✅ | `tests/test_web_flow.py` |
| Tests de sécurité (CSRF, rôles, isolation, sessions) | ✅ | `tests/test_security.py` |
| **Total** | ✅ | **115 tests, 0 avertissement** — commande dans le [README](README.md#vérifier-linstallation) |

## 12. Sécurité

| Exigence | État | Détail |
|---|---|---|
| Protection CSRF sur toutes les écritures | ✅ | jeton en session + repli double soumission `cl_csrf`, vérifié avant routage |
| CSP `script-src 'self'`, aucun script en ligne | ✅ | tous les comportements passent par `data-*` et des fichiers JS locaux |
| En-têtes de sécurité | ✅ | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP |
| Journal d'audit | ✅ | connexions, créations, suppressions, exports, invitations |
| Contrôles de production | ✅ | `CARBONLEDGER_ENV=production` refuse la clé secrète de développement ; avertissement si `COOKIE_SECURE=false` |
| Mots de passe robustes | ✅ | longueur minimale, comparaison à temps constant |

## 13. Interface : palette, typographie, accessibilité

| Exigence | État | Détail |
|---|---|---|
| Palette exacte demandée | ✅ | `#176B4D` (vert), `#DDF3E4` (vert clair), `#172B4D` (nuit), `#F8FAF9` (fond), `#64748B` (gris), `#E2E8F0` (bordure), `#F4B942` (ambre), `#D9534F` (rouge) — définies une seule fois dans `:root` |
| Typographie « Inter ou équivalente » | 🟡 | pile `"Inter", "Segoe UI", system-ui, …` : Inter est utilisé s'il est installé, sinon la police système. **Inter n'est pas embarqué** (un fichier de police représenterait ~300 Ko à héberger ; choix assumé, aucun CDN). |
| Graphiques sans dépendance externe | ✅ | SVG générés côté serveur (`app/services/charts.py`) |
| Responsive (ordinateur portable, tablette) | ✅ | dispositions en grille qui s'empilent sous 1 000 px |
| Navigation clavier des formulaires | ✅ | champs natifs, focus visible, boutons `<button>` |
| Unités et libellés non ambiguës | ✅ | « DH », « t CO₂e », « DH/t évitée », toujours avec l'unité |
| Pages d'erreur soignées | ✅ | 400 / 403 / 404 / 500 en français, avec issue |

## 14. Jeu de données de démonstration

| Exigence | État | Détail |
|---|---|---|
| Chargement en un clic depuis l'accueil ou les paramètres | ✅ | idempotent (jamais de doublons) |
| Données réalistes | ✅ | 25 dépenses sur 6 mois, catégories, fournisseurs, TVA |
| Registre carbone associé | ✅ | enregistrements liés aux dépenses |
| Projet reproduisant l'exemple du cahier des charges | ✅ | « Remplacement d'une presse hydraulique (démo) » |
| 2 autres projets de démonstration | ✅ | arbitrage « recommandé ≠ plus vert » et cas à données carbone manquantes |
| Lignes identifiables et supprimables | ✅ | badge « Démonstration », suppression en un clic |

## 15. Livrables

| Livrable | État | Emplacement |
|---|---|---|
| Code source complet | ✅ | dépôt (voir [README](README.md#7-structure-du-projet)) |
| Application exécutable | ✅ | `python run.py` → `http://127.0.0.1:8000` |
| Schéma de base + migrations | ✅ | `docs/schema.sql`, `docs/DATABASE.md`, Alembic (`alembic upgrade head`), `alembic check` propre |
| `.env.example` documenté | ✅ | 11 variables commentées |
| Jeu de données de démonstration | ✅ | `scripts/seed_demo.py` + chargement intégré |
| Tests de calcul | ✅ | `tests/` (115 tests) |
| README | ✅ | installation, configuration, formules, API, sécurité, limites |
| Instructions de déploiement | ✅ | [DEPLOYMENT.md](DEPLOYMENT.md) : local, Linux + PostgreSQL + Nginx + systemd, Docker, sauvegardes, Streamlit Community Cloud |
| Application Streamlit (démo publique) | ✅ | `streamlit_app.py` — accueil, inscription, connexion, espaces isolés par entreprise, mêmes moteurs de calcul ; démonstration chargée sur demande |
| Liste d'état des fonctionnalités | ✅ | ce document |

## 16. Limites assumées et hors périmètre

Décisions **volontaires** (la donnée absente est signalée, jamais inventée) :

- **Valeur résiduelle** : non chiffrée automatiquement. Un champ libre permet de la mentionner ; elle n'entre pas dans le coût total calculé.
- **Réinvestissement** : si la durée de vie d'un équipement est inférieure à l'horizon, l'application **le signale** sans calculer de remplacement.
- **Coût de financement** (intérêts d'emprunt) : hors périmètre des formules ; à intégrer dans les coûts de fonctionnement si besoin.
- **Prix interne du carbone** : indicateur de décision, pas une écriture comptable ; toujours présenté séparément.

Fonctions **non faites** (et pourquoi) :

- ⛔ **OCR de factures / relevés bancaires** : dépendance à un service externe, hors de la promesse « aucun chiffre inventé ». L'import CSV/XLSX est le chemin contrôlé.
- ⛔ **Multi-devise comptable** : le cahier des charges fixe le MAD ; les facteurs carbone restent par unité physique.
- ⛔ **Analyse de sensibilité probabiliste (Monte-Carlo)** : remplacée par l'analyse déterministe par hypothèse, plus explicable devant un comité.
- ⛔ **Refonte du scénario personnalisé dans l'UI** : disponible via l'API, pas encore exposé en interface.
- ⛔ **Notifications par e-mail** : les alertes sont consultables dans l'application (tableau de bord), aucun envoi externe n'est configuré.
- 🟡 **Facteurs d'émission par défaut** : issus de sources publiques citées mais **indicatifs**. Avant tout usage contractuel ou réglementaire, remplacez-les par vos valeurs documentées (c'est une exigence de rigueur, pas une lacune logicielle).

---

📄 Voir aussi : [README.md](README.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [docs/CALCULS.md](docs/CALCULS.md) · [docs/DATABASE.md](docs/DATABASE.md)
