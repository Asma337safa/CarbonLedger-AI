"""Configuration de l'application, chargée depuis l'environnement et un fichier .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Charge un fichier .env minimaliste (KEY=VALUE) sans écraser l'environnement réel."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "oui", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "CarbonLedger AI"
    env: str = os.environ.get("CARBONLEDGER_ENV", "development")
    secret_key: str = os.environ.get("CARBONLEDGER_SECRET_KEY", "dev-secret-a-changer")
    base_url: str = os.environ.get("CARBONLEDGER_BASE_URL", "http://127.0.0.1:8000")
    database_url: str = os.environ.get("CARBONLEDGER_DATABASE_URL", "sqlite:///data/carbonledger.db")
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("CARBONLEDGER_DATA_DIR", str(BASE_DIR / "data"))))
    max_upload_mb: int = int(os.environ.get("CARBONLEDGER_MAX_UPLOAD_MB", "5"))
    session_days: int = int(os.environ.get("CARBONLEDGER_SESSION_DAYS", "14"))
    cookie_secure: bool = _env_bool("CARBONLEDGER_COOKIE_SECURE", False)

    # Assistant IA optionnel (API compatible OpenAI).
    ai_api_key: str = os.environ.get("CARBONLEDGER_AI_API_KEY", "")
    ai_base_url: str = os.environ.get("CARBONLEDGER_AI_BASE_URL", "https://api.openai.com/v1")
    ai_model: str = os.environ.get("CARBONLEDGER_AI_MODEL", "gpt-4o-mini")

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in {"production", "prod"}

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key.strip())

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.uploads_dir, self.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

# Constantes métier transverses
DEFAULT_CURRENCY = "MAD"
DEFAULT_CURRENCY_LABEL = "DH"
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xlsm"}
