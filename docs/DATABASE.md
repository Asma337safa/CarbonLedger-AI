# Modèle de données

15 tables, 100 % rattachées à une organisation (`organizations.id`) sauf le
catalogue global de facteurs et les comptes utilisateurs. Le SQL correspondant est
généré par `python scripts/dump_schema.py` dans [`schema.sql`](schema.sql) ; les
migrations Alembic (`alembic/versions/`) sont la référence pour les évolutions.

- SQLite par défaut (`CARBONLEDGER_DATABASE_URL=sqlite:///data/carbonledger.db`), clés
  étrangères **activées** (`PRAGMA foreign_keys=ON`) et journal `WAL`.
- PostgreSQL en production : `postgresql+psycopg://…` (aucun changement de code).
- Types numériques : `NUMERIC` partout (jamais de flottant pour les montants) —
  montants 16,2 / 14,2 ; quantités 18,4 ; émissions kg 18,3 ; facteurs 18,6 ;
  pourcentages 6,2 ; années 5,1.
- Dates : `DATE` pour les périodes comptables, `DATETIME` UTC naïf pour les
  horodatages techniques (portable entre SQLite et PostgreSQL).

---

## 1. Comptes, organisations, sécurité

### `users`
Comptes de connexion.

| Colonne | Type | Notes |
|---|---|---|
| `id` | PK | |
| `email` | VARCHAR(255) | **unique**, normalisé en minuscules |
| `password_hash` | VARCHAR(255) | scrypt + sel (jamais de mot de passe en clair) |
| `full_name`, `locale` | VARCHAR | `locale` par défaut `fr` |
| `is_active` | BOOLEAN | désactivation sans suppression |
| `failed_login_count`, `locked_until` | INT / DATETIME | verrouillage temporaire après échecs répétés |
| `created_at`, `last_login_at` | DATETIME | |

### `organizations`
L'entreprise (une PME marocaine) : `name`, `ice` (Identifiant Commun de
l'Entreprise), `sector`, `company_size`, `currency` (`MAD`),
`internal_carbon_price` (DH/tCO₂e, hypothèse de décision),
`onboarding_done`, `demo_data_loaded`, `created_at`.

### `organization_members`
Appartenance d'un utilisateur à une organisation : `organization_id`, `user_id`,
`role` (`proprietaire` | `administrateur` | `membre` | `lecteur`), contrainte
d'unicité `(organization_id, user_id)`.

### `auth_sessions`
Sessions serveur : clé primaire = **SHA-256 du jeton** (le jeton en clair n'est
jamais stocké), `user_id`, `organization_id` (organisation active),
`csrf_token`, `flash` (messages temporaires JSON), `expires_at`, `last_seen_at`,
`ip`, `user_agent`.

### `invitations`
Invitations de collaborateurs : `organization_id`, `email`, `role`,
`token_hash` (unique), `expires_at`, `accepted_at`, `created_by_id`.

---

## 2. Référentiel carbone

### `emission_factors`
Facteur d'émission documenté. `organization_id` **NULL = catalogue global**
(11 facteurs livrés) ; sinon facteur propre à l'organisation. Contrainte
d'unicité `(organization_id, code)`.

| Colonne | Rôle |
|---|---|
| `code`, `label`, `category` | identification |
| `unit` | unité de référence (`kWh`, `L`, `kg`, `t`, `t.km`, `passager.km`, `m3`, `MAD`…) |
| `scope` | `1` (direct), `2` (énergie importée), `3` (chaîne de valeur) |
| `method` | `mesure`, `calcule`, `estime`, `monetaire` |
| `kgco2e_per_unit` | valeur (NUMERIC 18,6) |
| `source_name`, `source_url`, `source_version`, `geography` | **traçabilité obligatoire** |
| `valid_from`, `valid_until` | période de validité |
| `confidence` | `haute` | `moyenne` | `faible` |
| `calculation_note` | formule/périmètre documentés (ex. dérivation IPCC : L × PCI × facteur) |
| `is_demo` | marqueur des données de démonstration |

---

## 3. Dépenses et registre carbone

### `expenses`
Dépense réelle : `expense_date`, `category` (énergie, transport, achats,
équipements, voyages, services, déchets, autres), `supplier`, `description`,
`amount_ht`, `vat_amount`, `amount_ttc`, `quantity`, `unit`,
`emission_factor_id` (nullable), `carbon_source_note`,
`verification_status` (`a_verifier` | `verifiee` | `rejetee`), `is_demo`,
`created_by_id`, horodatages. Index `(organization_id, expense_date)` et
`(organization_id, category)`.

### `carbon_records`
Registre carbone : `category`, `period_start`, `period_end`,
`activity_quantity`, `activity_unit`, `emission_factor_id`, `method`,
`kgco2e` (NUMERIC 18,3 — résultat du calcul, figé à la création),
`status` (`mesure` | `calcule` | `estime`), `confidence`, `notes`, `is_demo`.
Rattachements optionnels : `expense_id` (dépense d'origine) et `option_id`
(**émissions d'une option de décision** : une estimation reste une estimation).
Index `(organization_id, period_start)`.

---

## 4. Décisions, scénarios, recommandations

### `decision_projects`
Projet de décision : `title`, `description`, `category`, `horizon_years`
(période commune de comparaison), `discount_rate_pct` (0 = hors actualisation),
`priority` (`cout` | `tresorerie` | `emissions` | `equilibre`),
`internal_carbon_price`, `status` (`brouillon` | `enregistree` | `archivee`),
`chosen_option_id` (option retenue, FK vers `decision_options`),
`is_demo`, `created_by_id`, horodatages. Index `(organization_id, status)`.

> La FK `chosen_option_id` est déclarée en `use_alter` : la contrainte est créée
> par un `ALTER TABLE` (dépendance circulaire assumée entre projets et options).

### `decision_options`
Option comparée : `name`, `supplier`, `purchase_cost`, `transport_cost`,
`annual_opex`, `annual_energy_share_pct` (part de l'énergie dans les coûts de
fonctionnement — conditionne l'effet du scénario « prix de l'énergie »),
`annual_maintenance`, `annual_savings`, `useful_life_years`,
`annual_emissions_kg`, `emissions_basis`, `emission_factor_id`,
`emissions_source_note`, `confidence`, `notes`, `sort_order`.

### `scenarios`
Scénario enregistré : `name`, `kind` (`base` | `optimiste` | `defavorable` |
`personnalise`), `parameters` (JSON : écarts en % et durée), `notes`,
`created_by_id`.

### `recommendations`
Instantané d'arbitrage enregistré par l'utilisateur : `priority`,
`carbon_price`, `summary` (texte), `details` (JSON : classement, fiche par
option, frontière, limites), `chosen_option_id`, `created_by_id`.

---

## 5. Rapports, imports, audit

### `reports`
Rapport généré : `kind` (`pdf` | `csv` | `xlsx`), `scope` (`projet` | `periode` |
`global`), `title`, `period_start`, `period_end`, `file_path`,
`payload` (JSON : chiffres clés au moment de la génération), `project_id`,
`created_by_id`.

### `import_batches`
Import de fichier : `filename`, `stored_path`, `status` (`en_attente` |
`valide` | `importe` | `echec`), `mapping` (JSON des correspondances de colonnes),
`summary` (JSON : compteurs erreurs / avertissements / doublons / lignes
importées), `user_id`.

### `audit_logs`
Journal d'audit : `organization_id` (nullable), `user_id` (nullable), `action`
(ex. `login`, `expense_created`, `decision_deleted`, `export_generated`),
`entity_type`, `entity_id`, `details` (JSON), `ip`, `created_at`.

---

## 6. Isolation des données

- Chaque requête métier passe par `get_scoped(...)` (`app/deps.py`) qui filtre sur
  l'organisation active de la session : un identifiant appartenant à une autre
  organisation renvoie **404**, jamais les données.
- Les suppressions d'organisation sont en cascade (`ON DELETE CASCADE`) ; les
  références optionnelles (facteur supprimé, utilisateur supprimé) sont mises à
  `NULL` (`ON DELETE SET NULL`) pour ne jamais casser l'historique.
- Testé par `tests/test_web_flow.py::test_isolation_entre_organisations`
  (pages, exports, API, rapports).

---

## 7. Migrations

```bash
alembic upgrade head                       # appliquer le schéma
alembic revision --autogenerate -m "…"     # nouvelle révision (comparer avant de valider)
alembic downgrade -1                       # revenir en arrière
alembic check                              # vérifier l'écart modèles / base
python scripts/dump_schema.py              # régénérer docs/schema.sql
```

Révision initiale : `alembic/versions/0001_schema_initial.py` (15 tables, index et
contraintes). Sur SQLite, les modifications de colonnes passent par une
reconstruction de table (`render_as_batch=True`) ; sur PostgreSQL, le SQL standard
est utilisé.
