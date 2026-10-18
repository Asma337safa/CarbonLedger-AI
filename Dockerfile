# CarbonLedger AI — image de production (FastAPI + Uvicorn)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CARBONLEDGER_DATA_DIR=/data

WORKDIR /app

# Dépendances système minimales (reportlab/openpyxl n'en exigent aucune de plus).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Utilisateur non privilégié et dossier de données persistant.
RUN useradd --system --create-home --home-dir /home/appuser appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Le schéma est créé au démarrage par l'application (idempotent) ; pour appliquer
# les migrations versionnées : docker compose exec app alembic upgrade head
# Port d'écoute : $PORT est fourni par les plateformes d'hébergement (Render,
# Railway…) ; repli sur 8000 pour l'exécution locale `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
