# Déploiement de CarbonLedger AI

Quatre scénarios : **poste de travail** (découverte), **serveur Linux** avec
PostgreSQL et Nginx (production PME), **Docker** (reproductible), **Render + Neon**
(hébergement gratuit en ligne).

---

## 0. Prérequis

- Python **3.11+** (3.12 recommandé)
- 512 Mo de RAM, 1 Go d'espace disque (SQLite) — prévoir davantage avec PostgreSQL
- Linux/macOS/Windows ; PostgreSQL 14+ en production
- Un domaine et un certificat TLS (Let's Encrypt) pour l'accès distant

---

## 1. Poste de travail (2 minutes)

```bash
git clone <dépôt> carbonledger && cd carbonledger
python -m venv .venv
source .venv/bin/activate         # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py --email demo@carbonledger.ma --password DemoCarbon2026
python run.py                     # http://127.0.0.1:8000
```

`scripts/init_db.py --reset --yes` repart d'une base vide (destructif).
`scripts/init_db.py --demo` crée en plus une organisation de démonstration.

---

## 2. Serveur Linux + PostgreSQL + Nginx (production)

### 2.1 Base de données

```bash
sudo -u postgres psql <<'SQL'
CREATE USER carbonledger WITH PASSWORD 'motdepasse-solide';
CREATE DATABASE carbonledger OWNER carbonledger ENCODING 'UTF8';
SQL
```

### 2.2 Application

```bash
sudo useradd --system --create-home --home-dir /srv/carbonledger carbonledger
sudo -u carbonledger git clone <dépôt> /srv/carbonledger/app
cd /srv/carbonledger/app
sudo -u carbonledger python3 -m venv .venv
sudo -u carbonledger .venv/bin/pip install -r requirements.txt
```

`.env` de production (à créer dans `/srv/carbonledger/app/.env`) :

```ini
CARBONLEDGER_ENV=production
CARBONLEDGER_SECRET_KEY=<sortie de : python -c "import secrets;print(secrets.token_urlsafe(48))">
CARBONLEDGER_BASE_URL=https://carbonledger.example.ma
CARBONLEDGER_DATABASE_URL=postgresql+psycopg://carbonledger:motdepasse-solide@localhost:5432/carbonledger
CARBONLEDGER_DATA_DIR=/srv/carbonledger/data
CARBONLEDGER_COOKIE_SECURE=true
CARBONLEDGER_MAX_UPLOAD_MB=10
CARBONLEDGER_AI_API_KEY=            # facultatif : laisser vide = mode démonstration
```

> En `CARBONLEDGER_ENV=production`, l'application **refuse de démarrer** si la clé
> secrète est restée à sa valeur de développement, et affiche un avertissement si
> `CARBONLEDGER_COOKIE_SECURE` n'est pas activé.

Schéma et données initiales :

```bash
sudo -u carbonledger .venv/bin/python scripts/init_db.py
sudo -u carbonledger .venv/bin/alembic upgrade head      # équivalent, versionné
```

### 2.3 Service systemd

`/etc/systemd/system/carbonledger.service` :

```ini
[Unit]
Description=CarbonLedger AI (FastAPI)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=carbonledger
Group=carbonledger
WorkingDirectory=/srv/carbonledger/app
EnvironmentFile=/srv/carbonledger/app/.env
ExecStart=/srv/carbonledger/app/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers
Restart=always
RestartSec=5
# Durcissement
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/srv/carbonledger/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now carbonledger
sudo systemctl status carbonledger
journalctl -u carbonledger -f
```

### 2.4 Nginx (TLS)

```nginx
server {
    listen 80;
    server_name carbonledger.example.ma;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name carbonledger.example.ma;

    ssl_certificate     /etc/letsencrypt/live/carbonledger.example.ma/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/carbonledger.example.ma/privkey.pem;

    client_max_body_size 12m;          # > CARBONLEDGER_MAX_UPLOAD_MB

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /static/ {
        alias /srv/carbonledger/app/app/static/;
        expires 30d;
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo certbot --nginx -d carbonledger.example.ma
sudo nginx -t && sudo systemctl reload nginx
```

### 2.5 Impression PDF en français

Les rapports PDF sont produits par ReportLab avec la police intégrée **Helvetica**
(accents et symboles € / DH / CO₂ gérés). Aucune installation de police n'est
nécessaire. Pour utiliser une autre police (Ubuntu, DejaVu), il suffit d'enregistrer
le TTF via ReportLab dans `app/services/report_pdf.py`.

### 2.6 Sauvegardes

```bash
# PostgreSQL
pg_dump -Fc carbonledger > /var/backups/carbonledger-$(date +%F).dump

# Données applicatives (fichiers importés, rapports générés)
tar czf /var/backups/carbonledger-data-$(date +%F).tar.gz -C /srv/carbonledger data

# Export complet par organisation (JSON) : Paramètres → Données → Exporter
```

Restauration : `pg_restore -d carbonledger fichier.dump` puis redéploiement du
dossier de données. Les rapports PDF/Excel sont régénérables : ils ne contiennent
pas de données exclusives.

### 2.7 Mise à jour

```bash
cd /srv/carbonledger/app
sudo -u carbonledger git pull
sudo -u carbonledger .venv/bin/pip install -r requirements.txt
sudo -u carbonledger .venv/bin/alembic upgrade head
sudo systemctl restart carbonledger
```

---

## 3. Docker

`Dockerfile` (fourni) puis :

```bash
docker build -t carbonledger .
docker run -d --name carbonledger \
  -p 8000:8000 \
  -e CARBONLEDGER_ENV=production \
  -e CARBONLEDGER_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  -e CARBONLEDGER_COOKIE_SECURE=false     # true derrière un reverse proxy TLS
  -v carbonledger-data:/data \
  carbonledger
```

Avec PostgreSQL, `docker-compose.yml` (fourni) :

```bash
export CARBONLEDGER_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
docker compose up -d --build
docker compose exec app python scripts/init_db.py
docker compose logs -f app
```

Les données sont persistées dans le volume `carbonledger-data` (base SQLite en
mode conteneur simple) ou dans le volume PostgreSQL `carbonledger-db`.

---

## 4. Hébergement gratuit (Render + Neon)

Combinaison sans carte bancaire : **service web Render** (gratuit) +
**PostgreSQL Neon** (gratuit, sans expiration). Le fichier `render.yaml` du
dépôt sert de plan de déploiement : Render s'en sert pour créer le service.

> Pourquoi pas SQLite sur Render ? Le disque des instances gratuites est
> éphémère : la base serait perdue à chaque redéploiement. PostgreSQL chez
> Neon rend les données persistantes.

### 4.1 Base de données Neon

1. Créer un compte sur <https://neon.com> puis « New Project » (région
   **Frankfurt**, la plus proche du Maroc).
2. Copier la chaîne de connexion (`postgresql://…?sslmode=require`) — c'est la
   valeur de `CARBONLEDGER_DATABASE_URL`. Aucune réécriture n'est nécessaire :
   l'application l'aiguille automatiquement vers le pilote `psycopg`.

### 4.2 Service web Render

1. Pousser ce dossier sur un dépôt GitHub (branche `main`).
2. Sur <https://render.com> : « New + » → **Blueprint** → choisir le dépôt.
3. Renseigner les variables demandées :
   - `CARBONLEDGER_DATABASE_URL` : la chaîne Neon ;
   - `CARBONLEDGER_BASE_URL` : `https://<nom-du-service>.onrender.com`
     (préremplie pour `carbonledger-ai`, à ajuster si le nom diffère) ;
   - `CARBONLEDGER_SECRET_KEY` : générée automatiquement par Render.
4. Lancer le déploiement. Au premier démarrage, l'application crée le schéma
   (idempotent). Ensuite : **S'inscrire** dans l'application, puis
   Paramètres → Données → « Charger les données de démonstration ».

La sonde `/health` sert de contrôle de disponibilité pour Render.

### 4.3 Limites du plan gratuit Render

- Mise en veille après **15 minutes** sans trafic : la requête suivante prend
  ~30 à 60 secondes (les autres suivent normalement).
- 750 h d'instance par mois et par espace de travail, bande passante limitée.
- Disque **éphémère** : les imports et rapports générés sont perdus à chaque
  redéploiement (ils sont régénérables ; la base vit chez Neon).

Pour un service toujours actif ou un volume plus important, passer à une
instance payante (Render, Railway…), à un VPS
([section 2](#2-serveur-linux--postgresql--nginx-production)) ou à Docker
([section 3](#3-docker)).

---

## 5. Exploitation courante

| Tâche | Commande / écran |
|---|---|
| Sonde de disponibilité | `curl -fsS https://…/health` |
| Créer un compte en ligne de commande | `python scripts/seed_demo.py --email … --password …` |
| Recharger le jeu de démonstration | Paramètres → Données → « Charger les données de démonstration » |
| Supprimer les données de démonstration | Paramètres → Données → « Supprimer les données de démonstration » |
| Exporter toutes les données d'une organisation | `GET /settings/export.json` (session requise) |
| Audit | Paramètres → Journal d'audit |
| Vérifier la configuration | journaux de démarrage (`[CarbonLedger] Avertissement…`) |

### Supervision minimale

- `/health` renvoie `{"ok": true, "app": "CarbonLedger AI", "env": …}`.
- Surveiller les erreurs 5xx dans le journal (`journalctl -u carbonledger`).
- Vérifier la taille de `CARBONLEDGER_DATA_DIR` (rapports et imports).

### Journalisation

Uvicorn écrit sur stdout/stderr : tout est capturé par systemd ou le driver de
logs Docker. Les actions sensibles (connexions, créations, suppressions, exports)
sont **aussi** conservées dans la table `audit_logs` et visibles dans l'interface.

---

## 6. Points de vigilance

1. **Clé secrète** : unique par environnement, jamais commitée ; la rotation
   déconnecte les sessions (acceptable, les données restent intactes).
2. **HTTPS obligatoire** dès que l'application est exposée : `CARBONLEDGER_COOKIE_SECURE=true`.
3. **Facteurs d'émission** : remplacer les valeurs « indicatives » par vos valeurs
   documentées avant tout usage contractuel ou réglementaire (Paramètres → Facteurs).
4. **Sauvegardes testées** : une restauration non testée n'est pas une sauvegarde.
5. **Assistant IA** : sans clé d'API, aucune donnée ne sort du serveur ;
   avec une clé, seuls les chiffres calculés nécessaires à la réponse sont
   transmis au fournisseur choisi.
6. **SQLite** : suffisant jusqu'à quelques dizaines de milliers de lignes ;
   au-delà, PostgreSQL (aucune modification de code).
