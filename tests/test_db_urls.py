"""Normalisation des URL de base de données (SQLite ↔ PostgreSQL).

Vérifie notamment que les chaînes fournies telles quelles par les hébergeurs
(Neon, Render, Heroku…) sont acceptées sans réécriture manuelle.
"""

from __future__ import annotations

from app.config import BASE_DIR
from app.db import _normalize_url


def test_url_postgresql_aiguillee_vers_psycopg():
    neon = "postgresql://user:pass@ep-exemple.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    assert _normalize_url(neon) == (
        "postgresql+psycopg://user:pass@ep-exemple.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    )
    assert _normalize_url("postgres://user:pass@host:5432/db") == (
        "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_url_psycopg_deja_explicite_inchangee():
    url = "postgresql+psycopg://user:pass@host:5432/db"
    assert _normalize_url(url) == url


def test_chemin_sqlite_relatif_rendu_absolu():
    absolute = (BASE_DIR / "data" / "carbonledger.db").resolve().as_posix()
    assert _normalize_url("sqlite:///data/carbonledger.db") == f"sqlite:///{absolute}"
    assert _normalize_url("sqlite:///:memory:") == "sqlite:///:memory:"
