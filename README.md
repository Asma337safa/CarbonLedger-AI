# CarbonLedger AI

**Plateforme de décision financière et carbone pour les PME marocaines.**
Dépenses réelles, registre carbone traçable, et surtout un **comparateur de décisions**
qui explique les compromis coût / émissions — sans inventer de chiffres.

Interface en français, montants en dirhams (DH / MAD), aucune dépendance à un CDN
(tout est servi localement) et aucun script en ligne (CSP `script-src 'self'`).

---

## 1. Ce que fait l'application

| Section | Contenu |
|---|---|
| **Tableau de bord** | Totaux de dépenses (HT/TVA/TTC), évolution vs période précédente, répartition par catégorie, émissions de la période, part estimée vs mesurée, alertes et opportunités déclarées. |
| **Dépenses** | Saisie, modification, vérification, suppression, filtres (période, catégorie, fournisseur, statut, recherche), export CSV. Estimation carbone **seulement** si une quantité, une unité et un facteur documenté sont fournis. |
| **Comptabilité carbone** | Registre d'activités (énergie, transport, achats, déchets…), calcul `quantité × facteur`, traçabilité de la source, statut **mesuré / calculé / estimé**, scopes 1-2-3, export CSV. |
| **Comparateur de décisions** ⭐ | 2 à N options comparées sur une période commune : coûts totaux, trésorerie, coût par tonne de CO₂e évitée, délai de rattrapage, frontière de compromis, classement selon la priorité choisie, texte d'arbitrage explicable, scénarios, analyse de sensibilité, export CSV et rapport PDF. |
| **Simulations** | Mêmes moteurs que le comparateur, en mode « bac à sable » : curseurs d'hypothèses, scénarios prédéfinis (base / optimiste / défavorable), recalcul immédiat, sans modifier le projet. |
| **Rapports** | Rapport de période (PDF), classeur Excel (dépenses + carbone), rapport de décision (PDF), historique des rapports générés, téléchargement et suppression. |
| **Assistant IA** | « CarbonLedger Copilot » : répond uniquement à partir des données calculées de l'organisation. **Sans clé d'API, il bascule en mode démonstration déterministe** (aucun appel réseau, aucune invention). |
| **Paramètres** | Organisation (ICE, secteur, effectif, prix interne du carbone), membres et rôles (propriétaire / administrateur / membre / lecteur), invitations, catalogue de facteurs (globaux + spécifiques), configuration IA, données de démonstration, journal d'audit, export JSON complet, suppression de l'organisation. |

Plus : inscription / connexion, isolation stricte des données par organisation,
protection CSRF, sessions serveur, import CSV/Excel en 4 étapes avec validation
ligne par ligne.

---

## 2. Démarrage rapide

Prérequis : **Python 3.11+** (aucun Node.js, aucune base à installer pour démarrer).

```bash
# 1. Environnement virtuel
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 2. Dépendances
pip install -r requirements.txt

# 3. Configuration (facultatif : les valeurs par défaut fonctionnent)
copy .env.example .env        # Windows
cp .env.example .env          # Linux / macOS

# 4. Base de données + catalogue de facteurs
python scripts/init_db.py

# 5. (Option A) Compte de démonstration prêt à l'emploi
python scripts/seed_demo.py --email demo@carbonledger.ma --password DemoCarbon2026 --company "PME de démonstration"

# 6. Lancer
python run.py                 # http://127.0.0.1:8000
```

Option B : créez votre compte depuis l'interface (`/register`), puis, à l'étape
d'accueil, choisissez **« Charger le jeu de démonstration »** pour découvrir
l'application avec des données complètes.

> Le jeu de démonstration comprend 25 dépenses réparties sur 6 mois, les
> enregistrements carbone associés et 3 projets de décision (dont l'exemple
> chiffré du cahier des charges). Toutes ces lignes portent un badge
> « Démonstration » et se suppriment en un clic depuis **Paramètres → Données**.

### Vitrine Streamlit (démonstration en ligne)

Le dépôt contient aussi une **vitrine Streamlit** (`streamlit_app.py`) : tableau
de bord, dépenses, registre carbone, **comparateur de décisions** et simulations,
sur le jeu de démonstration embarqué (`streamlit_demo.db`, en lecture seule).
Elle réutilise **le même moteur de calcul** que l'application (`app/calc`,
`app/services`) : aucun chiffre n'est recalculé ailleurs.

```bash
streamlit run streamlit_app.py       # http://127.0.0.1:8501
```

Déploiement gratuit sur Streamlit Community Cloud : voir
[DEPLOYMENT.md § 4.4](DEPLOYMENT.md#44-vitrine-streamlit-streamlit-community-cloud).

### Vérifier l'installation

```bash
pytest                       # 112 tests : calculs, décisions, API, isolation, sécurité, vitrine Streamlit
python scripts/dump_schema.py            # régénère docs/schema.sql
alembic upgrade head                     # applique les migrations
alembic check                            # vérifie que le schéma correspond aux modèles
```

---

## 3. Configuration (fichier `.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `CARBONLEDGER_ENV` | `development` | `production` active les contrôles stricts d'exploitation. |
| `CARBONLEDGER_SECRET_KEY` | valeur de développement | Secret applicatif. **À remplacer en production.** |
| `CARBONLEDGER_BASE_URL` | `http://127.0.0.1:8000` | URL publique (liens d'invitation). |
| `CARBONLEDGER_DATABASE_URL` | `sqlite:///data/carbonledger.db` | SQLite par défaut ; PostgreSQL : `postgresql+psycopg://user:mdp@hôte:5432/carbonledger`. |
| `CARBONLEDGER_DATA_DIR` | `data` | Base SQLite, imports temporaires, rapports générés, exports. |
| `CARBONLEDGER_MAX_UPLOAD_MB` | `5` | Taille maximale d'un fichier importé. |
| `CARBONLEDGER_SESSION_DAYS` | `14` | Durée de vie d'une session. |
| `CARBONLEDGER_COOKIE_SECURE` | `false` | `true` derrière HTTPS. |
| `CARBONLEDGER_AI_API_KEY` | *(vide)* | Clé d'API du Copilot. Vide = mode démonstration. |
| `CARBONLEDGER_AI_BASE_URL` | `https://api.openai.com/v1` | Toute API compatible OpenAI (OpenAI, Azure, Mistral, Ollama…). |
| `CARBONLEDGER_AI_MODEL` | `gpt-4o-mini` | Modèle utilisé par le Copilot. |

---

## 4. Les règles de calcul (déterministes et testées)

Tout le calcul vit dans `app/calc/` (aucune dépendance à la base ni au web) et est
couvert par `tests/`. Le détail complet est dans [`docs/CALCULS.md`](docs/CALCULS.md).

```
Coût total d'une option   = coût d'acquisition + transport
                          + Σ (coûts de fonctionnement + maintenance − économies)

Émissions cumulées (t)    = émissions annuelles × nombre d'années   (1 t = 1 000 kg)

Coût par tonne évitée     = (coût de l'option la moins émettrice
                             − coût de l'option la plus émettrice)
                          ÷ (émissions de la plus émettrice − émissions de la moins émettrice)
```

Un **résultat négatif** signifie que l'option la moins émettrice est *aussi* la
moins chère : on parle alors de **double gain** (ce n'est pas une recette
comptable, mais un indicateur de compromis).

### Exemple de référence (cahier des charges, repris dans le jeu de démonstration)

| | Option A | Option B |
|---|---|---|
| Acquisition | 80 000 DH | 95 000 DH |
| Fonctionnement annuel | 24 000 DH | 17 000 DH |
| Coût total sur 5 ans | **200 000 DH** | **180 000 DH** |
| Émissions | 12 t CO₂e/an → 60 t | 7 t CO₂e/an → 35 t |

- Économie : **20 000 DH** sur 5 ans
- Émissions évitées : **5 t/an**, soit **25 t** cumulées
- Coût par tonne évitée : `(180 000 − 200 000) ÷ 25 = −800 DH/t` → **double gain**
- Délai de rattrapage du surcoût initial de B (15 000 DH) : ≈ 2,1 ans

Règles de rigueur appliquées partout :

- **Aucun chiffre inventé** : une donnée absente produit « non disponible » et un avertissement, jamais une estimation silencieuse.
- **Aucune conversion implicite d'unités** : `kWh ↔ MWh` oui, `kg ↔ kWh` non (l'estimation carbone est alors refusée).
- **Aucun réinvestissement automatique** si la durée de vie est plus courte que l'horizon : c'est signalé, pas chiffré.
- **Séparation stricte** entre données **mesurées**, **calculées** et **estimées** (y compris les estimations monétaires).

---

## 5. Facteurs d'émission

Le catalogue global (11 facteurs, `app/services/factors_seed.py`) est **documenté** :
source, version, périmètre, méthode, niveau de confiance, note de calcul.

| Code | Valeur | Unité | Scope | Source |
|---|---|---|---|---|
| `ELEC-RESEAU-MA` | 0,700 | kWh | 2 | ADEME Base Empreinte — électricité Maroc (indicatif) |
| `GAZOLE-L` | 2,652 | L | 1 | IPCC 2006, vol. 2 (valeurs par défaut) |
| `ESSENCE-L` | 2,272 | L | 1 | IPCC 2006, vol. 2 |
| `GPL-L` | 1,600 | L | 1 | IPCC 2006, vol. 2 |
| `GAZ-NAT-kWh` | 0,202 | kWh | 1 | IPCC 2006, vol. 2 |
| `EAU-M3` | 0,300 | m³ | 3 | Ordre de grandeur ADEME (indicatif) |
| `DECHETS-T` | 600,000 | t | 3 | Ordre de grandeur (très variable) |
| `PAPIER-KG` | 0,920 | kg | 3 | Ordre de grandeur ADEME (indicatif) |
| `AVION-PKM` | 0,230 | passager.km | 3 | Ordre de grandeur ADEME (indicatif) |
| `FRET-TKM` | 0,106 | t.km | 3 | Ordre de grandeur ADEME, poids lourd (indicatif) |
| `MONETAIRE-ACHATS-1000MAD` | 0,500 | MAD | 3 | **Ratio interne à remplacer** — aucune source externe |

Les valeurs « indicatives » sont **explicitement signalées comme telles** dans
l'interface et dans les exports. Chaque organisation peut créer ses propres
facteurs (valeur, unité, source, périmètre, validité) : ils sont prioritaires sur
le catalogue global et n'écrasent jamais les données des autres organisations.

---

## 6. Import de fichiers (4 étapes)

1. **Téléversement** — CSV (`;`, `,`, `|`, tabulation) ou Excel `.xlsx`, encodage détecté (UTF-8, cp1252, latin-1).
2. **Aperçu** — colonnes détectées, lignes brutes, nombre de lignes.
3. **Correspondance** — proposition automatique des colonnes (`Date`, `Montant HT`, `TVA`, `Unité`, `Quantité`, `Code facteur`…), modifiable.
4. **Validation et confirmation** — erreurs bloquantes vs avertissements, détection des doublons (même date, fournisseur et montant), export CSV des problèmes, puis import des seules lignes valides.

Aucun montant n'est repris sans contrôle : les lignes en erreur sont écartées et
téléchargeables pour correction. L'estimation carbone à l'import suit les mêmes
règles que la saisie manuelle (facteur documenté obligatoire).

---

## 7. Structure du projet

```
app/
  calc/            moteurs de calcul purs (décision, arbitrage, scénarios, sensibilité,
                   émissions, unités, formatage, tableau de bord)
  routers/         pages et API (auth, dashboard, expenses, carbon, imports, decisions,
                   simulations, reports, copilot, settings, api)
  services/        services applicatifs (import, démo, PDF, Excel, graphiques SVG,
                   copilot, audit, notifications, amorçage des facteurs)
  templates/       gabarits Jinja2 (français, sans script en ligne)
  static/          CSS et JavaScript servis localement (aucun CDN)
  models.py        15 entités SQLAlchemy
  main.py          application FastAPI (CSRF, en-têtes de sécurité, erreurs)
alembic/           migrations de schéma
streamlit_app.py   vitrine Streamlit (lecture seule), déployable sur Streamlit Cloud
streamlit_demo.db  base de démonstration embarquée de la vitrine
.streamlit/        thème Streamlit (charte CarbonLedger)
scripts/           init_db.py, seed_demo.py, dump_schema.py
tests/             112 tests (calculs, décision, arbitrage, imports, web, sécurité)
docs/              CALCULS.md, DATABASE.md, schema.sql
```

---

## 8. API (JSON)

Toutes les API exigent une session valide et l'en-tête `X-CSRF-Token`
(jeton fourni dans la balise `<meta name="csrf-token">` des pages).

| Méthode | Chemin | Rôle |
|---|---|---|
| `POST` | `/api/projects/compute` | Calcul complet d'un prospect non enregistré (options + hypothèses) : comparaison, arbitrage, scénarios, sensibilité, graphiques. |
| `POST` | `/api/decisions/{id}/compute` | Recalcul d'un projet enregistré avec priorités / hypothèses, **sans modifier la base**. |
| `POST` | `/api/emissions/preview` | Aperçu `quantité × facteur` avec conversion d'unité contrôlée. |
| `GET` | `/api/factors` | Catalogue de facteurs disponible pour l'organisation. |
| `POST` | `/api/copilot/ask` | Question au Copilot (réponse fondée sur les données calculées, ou mode démonstration). |
| `POST` | `/api/imports/upload` | Import de fichier (étape 1). |
| `POST` | `/api/imports/{batch}/mapping` | Validation avec correspondance de colonnes (étape 3-4). |
| `POST` | `/api/imports/{batch}/confirm` | Import des lignes valides. |
| `GET` | `/api/imports/{batch}/errors.csv` | Export des problèmes détectés. |
| `GET` | `/health` | Sonde de disponibilité. |

---

## 9. Sécurité et confidentialité

- Mots de passe hachés avec sel (`scrypt` de la bibliothèque standard), jamais stockés en clair.
- Sessions serveur en base (jeton opaque, haché en base), cookies `HttpOnly` + `SameSite=Lax`.
- Protection **CSRF** sur toutes les écritures (jeton de session, ou double soumission `cl_csrf`), vérifiée avant le routage.
- Isolation par organisation sur **chaque** requête ; rôles `propriétaire`, `administrateur`, `membre`, `lecteur` (les lectures restent possibles, les écritures sont refusées côté serveur).
- En-têtes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` (aucun script en ligne, aucun CDN).
- Journal d'audit des actions sensibles (connexions, créations, suppressions, exports).
- Export JSON complet (portabilité) et suppression d'organisation depuis les paramètres.

---

## 10. Limites assumées

- Les facteurs « indicatifs » du catalogue doivent être remplacés par vos valeurs documentées avant tout usage réglementaire ou contractuel.
- Aucune valeur résiduelle, aucun réinvestissement et aucun coût financier d'emprunt ne sont chiffrés automatiquement : ces éléments sont signalés comme à compléter.
- L'assistant IA est **facultatif** et n'a jamais accès à des chiffres qu'il pourrait inventer : sans clé d'API, il répond à partir des calculs, en mode démonstration.
- Pas d'OCR de factures, pas de connexion bancaire, pas de multi-devise comptable (les montants sont en MAD).
- SQLite suffit jusqu'à plusieurs dizaines de milliers de lignes ; au-delà, passez à PostgreSQL (voir [`DEPLOYMENT.md`](DEPLOYMENT.md)).

📄 Voir aussi : [`FEATURES.md`](FEATURES.md) (état des fonctionnalités), [`DEPLOYMENT.md`](DEPLOYMENT.md) (déploiement), [`docs/CALCULS.md`](docs/CALCULS.md) (formules), [`docs/DATABASE.md`](docs/DATABASE.md) (modèle de données).
