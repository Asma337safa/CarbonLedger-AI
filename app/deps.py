"""Dépendances HTTP : contexte utilisateur/organisation, contrôle des rôles,
messages flash et isolation des données par organisation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .db import get_db  # noqa: F401  (réexporté pour les routers)
from .enums import ADMIN_ROLES, WRITE_ROLES
from .errors import AccessDenied, NotFoundError
from .models import AuthSession, Organization, OrganizationMember, User, utcnow
from .security import new_csrf_token, new_token, safe_equal, token_hash

SESSION_COOKIE = "cl_session"
CSRF_COOKIE = "cl_csrf"

ModelT = TypeVar("ModelT")


class RedirectException(Exception):
    """Redirection HTTP demandée par une dépendance."""

    def __init__(self, location: str, status_code: int = 303):
        super().__init__(location)
        self.location = location
        self.status_code = status_code


@dataclass
class Context:
    user: User
    organization: Organization
    member: OrganizationMember
    auth_session: AuthSession
    csrf_token: str

    @property
    def role(self) -> str:
        return self.member.role

    @property
    def can_write(self) -> bool:
        return self.member.role in WRITE_ROLES

    @property
    def is_admin(self) -> bool:
        return self.member.role in ADMIN_ROLES


def load_session(db: OrmSession, request: Request) -> AuthSession | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    session = db.get(AuthSession, token_hash(raw))
    if session is None or session.expires_at < utcnow():
        return None
    return session


def load_context(request: Request, db: OrmSession) -> Context | None:
    """Contexte complet (utilisateur + organisation courante) ou ``None``."""
    session = load_session(db, request)
    if session is None:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    org_id = session.organization_id
    if org_id is None:
        membership = db.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.id)
        ).scalars().first()
        if membership is None:
            return None
        session.organization_id = membership.organization_id
        db.commit()
        org_id = membership.organization_id
    member = db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id, OrganizationMember.organization_id == org_id
        )
    ).scalars().first()
    if member is None:
        # L'accès a été retiré entre-temps : on invalide la session.
        db.delete(session)
        db.commit()
        return None
    organization = db.get(Organization, org_id)
    if organization is None:
        return None
    session.last_seen_at = utcnow()
    return Context(user=user, organization=organization, member=member, auth_session=session, csrf_token=session.csrf_token)


def require_context(request: Request, db: OrmSession) -> Context:
    """Comme ``load_context`` mais redirige vers la connexion si nécessaire."""
    context = load_context(request, db)
    if context is None:
        next_url = request.url.path
        if request.url.query:
            next_url += "?" + request.url.query
        raise RedirectException(f"/login?next={next_url}")
    return context


def require_api_context(request: Request, db: OrmSession) -> Context:
    """Contexte exigé pour les points d'API JSON (401 au lieu d'une redirection)."""
    context = load_context(request, db)
    if context is None:
        raise AccessDenied("Session expirée ou invalide. Reconnectez-vous.")
    return context


def require_write(context: Context) -> None:
    if not context.can_write:
        raise AccessDenied("Votre rôle ne permet pas de modifier les données de l'organisation.")


def require_admin(context: Context) -> None:
    if not context.is_admin:
        raise AccessDenied("Cette action est réservée aux propriétaires et administrateurs.")


def get_scoped(db: OrmSession, model: type[ModelT], object_id: Any, organization_id: int) -> ModelT:
    """Récupère une ressource en vérifiant son appartenance à l'organisation.

    Empêche tout accès aux données d'une autre entreprise (testé dans
    ``tests/test_api_isolation.py``).
    """
    if object_id in (None, ""):
        raise NotFoundError("Ressource introuvable.")
    obj = db.get(model, int(object_id))
    scoped_org = getattr(obj, "organization_id", None) if obj is not None else None
    if obj is None or scoped_org != organization_id:
        raise NotFoundError("Ressource introuvable dans votre organisation.")
    return obj


def flash(db: OrmSession, context: Context | None, level: str, message: str) -> None:
    """Ajoute un message flash affiché à la prochaine page."""
    if context is None:
        return
    messages = list(context.auth_session.flash or [])
    messages.append({"level": level, "message": message})
    context.auth_session.flash = messages
    db.commit()


def pop_flash(db: OrmSession, context: Context | None) -> list[dict[str, str]]:
    if context is None:
        return []
    messages = list(context.auth_session.flash or [])
    if messages:
        context.auth_session.flash = []
        db.commit()
    return messages


def start_session(db: OrmSession, user: User, request: Request, organization_id: int | None = None) -> tuple[str, AuthSession]:
    """Crée une session authentifiée. Retourne (jeton en clair, session)."""
    token = new_token()
    session = AuthSession(
        id=token_hash(token),
        user_id=user.id,
        organization_id=organization_id,
        csrf_token=new_csrf_token(),
        expires_at=utcnow() + timedelta(days=settings.session_days),
        ip=(request.client.host if request.client else "")[:64],
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(session)
    db.commit()
    return token, session


def end_session(db: OrmSession, request: Request) -> None:
    session = load_session(db, request)
    if session is not None:
        db.delete(session)
        db.commit()
