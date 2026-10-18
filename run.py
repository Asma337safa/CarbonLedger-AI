"""Lancement local : python run.py (ou uvicorn app.main:app --reload)."""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("CARBONLEDGER_HOST", "127.0.0.1")
    # `PORT` est fourni par la plupart des plateformes d'hébergement (Render, Railway…).
    port = int(os.environ.get("CARBONLEDGER_PORT") or os.environ.get("PORT", "8000"))
    reload_enabled = os.environ.get("CARBONLEDGER_RELOAD", "1").strip() not in {"0", "false", "non"}
    print(f"CarbonLedger AI — http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_enabled)
