"""Point d'entrée FastAPI : application, sécurité, gestion des erreurs."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import SessionLocal, init_db
from .deps import CSRF_COOKIE, RedirectException, load_session
from .errors import AccessDenied, AppError, NotFoundError, ValidationError
from .routers import api, auth, carbon, copilot, dashboard, decisions, expenses, imports, reports, settings as settings_router, simulations
from .security import safe_equal
from .services.factors_seed import seed_global_factors
from .web import page_context, render

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

DEFAULT_SECRET = "dev-secret-a-changer"


def check_configuration() -> list[str]:
    """Contrôles de configuration au démarrage.

    En production, une clé secrète restée à sa valeur de développement est une
    erreur fatale (les sessions pourraient être forgées) ; le reste est signalé
    sous forme d'avertissements dans les journaux.
    """
    warnings: list[str] = []
    if settings.is_production and settings.secret_key.strip() in {"", DEFAULT_SECRET}:
        raise RuntimeError(
            "CARBONLEDGER_SECRET_KEY doit être défini avec une valeur unique en production "
            "(python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
        )
    if not settings.cookie_secure:
        warnings.append(
            "CARBONLEDGER_COOKIE_SECURE=false : activez-le derrière HTTPS pour que le cookie "
            "de session ne circule qu'en HTTPS."
        )
    if settings.secret_key.strip() in {"", DEFAULT_SECRET}:
        warnings.append("Clé secrète de développement utilisée : à remplacer avant toute mise en ligne.")
    return warnings


@asynccontextmanager
async def lifespan(app: FastAPI):
    for message in check_configuration():
        print(f"[CarbonLedger] Avertissement de configuration : {message}")
    init_db()
    seed_global_factors()
    yield


app = FastAPI(
    title="CarbonLedger AI",
    version="0.9.0",
    description="Pilotage financier et carbone pour PME marocaines.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Protection CSRF (jeton de session ou double-soumission) + en-têtes de sécurité."""
    is_api = request.url.path.startswith("/api/") or "/api/" in request.url.path
    if request.method in UNSAFE_METHODS:
        token = request.headers.get("x-csrf-token")
        if not token:
            content_type = request.headers.get("content-type", "")
            if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
                try:
                    # Le corps est lu puis remis à disposition du gestionnaire de
                    # route (BaseHTTPMiddleware ne rejoue que les corps mis en cache).
                    await request.body()
                    form = await request.form()
                    token = form.get("csrf_token")
                except Exception:
                    token = None
        db = SessionLocal()
        try:
            session = load_session(db, request)
        finally:
            db.close()
        expected = session.csrf_token if session is not None else request.cookies.get(CSRF_COOKIE)
        if not safe_equal(token, expected):
            message = "Jeton de sécurité invalide ou expiré. Rechargez la page puis réessayez."
            if is_api:
                return JSONResponse({"ok": False, "error": message}, status_code=403)
            response = render(request, "errors/403.html", {"message": message}, status_code=403)
            return _with_security_headers(response)

    response = await call_next(request)
    return _with_security_headers(response)


def _with_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'",
    )
    return response


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


# ---------------------------------------------------------------------------
# Gestion des erreurs
# ---------------------------------------------------------------------------
@app.exception_handler(RedirectException)
async def redirect_handler(_request: Request, exc: RedirectException):
    return RedirectResponse(exc.location, status_code=exc.status_code)


@app.exception_handler(AccessDenied)
async def access_denied_handler(request: Request, exc: AccessDenied):
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": exc.message}, status_code=403)
    return _with_security_headers(render(request, "errors/403.html", {"message": exc.message}, status_code=403))


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": exc.message}, status_code=404)
    return _with_security_headers(render(request, "errors/404.html", {"message": exc.message}, status_code=404))


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": exc.message, "fields": exc.fields}, status_code=422)
    return _with_security_headers(render(request, "errors/400.html", {"message": exc.message}, status_code=400))


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": exc.message}, status_code=400)
    return _with_security_headers(render(request, "errors/400.html", {"message": exc.message}, status_code=400))


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == 404:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "Ressource introuvable."}, status_code=404)
        return _with_security_headers(render(request, "errors/404.html", {"message": "Page introuvable."}, status_code=404))
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)
    if exc.status_code in (301, 302, 303, 307, 308) and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
    return _with_security_headers(
        render(request, "errors/400.html", {"message": str(exc.detail)}, status_code=exc.status_code)
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover - défensif
    if _wants_json(request):
        return JSONResponse({"ok": False, "error": "Erreur interne inattendue."}, status_code=500)
    return _with_security_headers(
        render(
            request,
            "errors/500.html",
            {"message": "Une erreur interne est survenue. Vos données n'ont pas été modifiées.", "detail": type(exc).__name__},
            status_code=500,
        )
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(expenses.router)
app.include_router(imports.router)
app.include_router(imports.api_router)
app.include_router(carbon.router)
app.include_router(decisions.router)
app.include_router(simulations.router)
app.include_router(reports.router)
app.include_router(copilot.router)
app.include_router(settings_router.router)
app.include_router(api.router)


@app.get("/health")
def health():
    return {"ok": True, "app": settings.app_name, "env": settings.env}
