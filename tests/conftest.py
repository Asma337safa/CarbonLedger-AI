"""Fixtures partagées : base de données de test isolée, client HTTP, helpers.

L'environnement de test est fixé **avant** le premier import du paquet ``app``
(sinon la configuration et le moteur SQLAlchemy seraient déjà construits sur la
base de développement). Le dossier de travail est configurable via
``CARBONLEDGER_TEST_DIR`` ; sinon un dossier temporaire est créé puis supprimé.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Environnement isolé ----------------------------------------------------
_OWN_TEMP = not os.environ.get("CARBONLEDGER_TEST_DIR")
TEST_DIR = Path(os.environ.get("CARBONLEDGER_TEST_DIR") or tempfile.mkdtemp(prefix="carbonledger_tests_"))
TEST_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = TEST_DIR / "carbonledger_test.db"
for suffix in ("", "-wal", "-shm"):
    candidate = Path(str(DB_PATH) + suffix)
    if candidate.exists():
        candidate.unlink()

os.environ["CARBONLEDGER_DATA_DIR"] = str(TEST_DIR)
os.environ["CARBONLEDGER_DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["CARBONLEDGER_SECRET_KEY"] = os.environ.get("CARBONLEDGER_TEST_SECRET", "secret-de-test-carbonledger")
os.environ["CARBONLEDGER_ENV"] = "test"
os.environ["CARBONLEDGER_AI_API_KEY"] = ""  # l'assistant doit rester en mode démonstration
os.environ["CARBONLEDGER_COOKIE_SECURE"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.factors_seed import seed_global_factors  # noqa: E402
from tests import helpers  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Supprime le dossier temporaire créé par la suite de tests."""
    if _OWN_TEMP and not os.environ.get("CARBONLEDGER_TEST_KEEP"):
        shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Schéma + catalogue de facteurs, une seule fois pour toute la session."""
    init_db()
    seed_global_factors()


@pytest.fixture(scope="session")
def app_instance():
    return app


@pytest.fixture
def client():
    """Client HTTP de test (le cycle de vie FastAPI initialise la base)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    """Session SQLAlchemy directe, pour les vérifications en base."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def company(client):
    """Une organisation de test connectée : (client, e-mail, mot de passe)."""
    return helpers.register_company(client)


@pytest.fixture
def demo_company(client):
    """Organisation connectée avec le jeu de données de démonstration chargé."""
    account = helpers.register_company(client)
    helpers.load_demo_data(client)
    return account
