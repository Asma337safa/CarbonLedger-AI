"""Accès base de données (SQLAlchemy 2.x).

SQLite par défaut (aucune installation requise), PostgreSQL en production
via ``CARBONLEDGER_DATABASE_URL``. Le schéma est créé/mis à jour par
``scripts/init_db.py`` (Alembic) ; l'application vérifie également la
présence des tables au démarrage.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import BASE_DIR, settings


def _normalize_url(url: str) -> str:
    """Normalise l'URL de base de données.

    - ``postgres://`` / ``postgresql://`` (fournis tels quels par Neon, Render,
      Heroku…) sont aiguillés vers le pilote ``psycopg`` (v3) : pas besoin de
      réécrire la chaîne à la main.
    - Les chemins SQLite relatifs sont rendus absolus (depuis la racine du projet).
    """
    for legacy in ("postgres://", "postgresql://"):
        if url.startswith(legacy):
            return "postgresql+psycopg://" + url[len(legacy):]
    prefix = "sqlite:///"
    if url.startswith(prefix):
        raw = url[len(prefix):]
        if raw.startswith(":memory:") or Path(raw).is_absolute():
            return url
        absolute = (BASE_DIR / raw).resolve()
        return f"{prefix}{absolute.as_posix()}"
    return url


DATABASE_URL = _normalize_url(settings.database_url)

engine_kwargs: dict = {"future": True, "pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, **engine_kwargs)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - infra
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI : fournit une session de base de données par requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager pour les scripts et services hors requête HTTP."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Crée les tables manquantes (idempotent)."""
    from . import models  # noqa: F401  (enregistre les mappings)

    Base.metadata.create_all(engine)


def is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")
