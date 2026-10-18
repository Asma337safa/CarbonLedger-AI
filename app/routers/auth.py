"""Authentification : inscription, connexion, déconnexion, invitations, assistant de démarrage."""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import get_db
from ..deps import (
    CSRF_COOKIE,
    Context,
    end_session,
    flash,
    load_context,
    require_context,
    start_session,
)
from ..models import Invitation, Organization, OrganizationMember, User, utcnow
from ..security import (
    new_csrf_token,
    password_problems,
    token_hash,
    verify_password,
    hash_password,
)
from ..services import audit
from ..services.demo_data import load_demo_data
from ..web import page_context, render

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MAX_FAILED_LOGINS = 8
LOCK_MINUTES = 15


def _set_csrf_cookie(response, token: str):
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,  # double-soumission : le formulaire doit lire le cookie
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * 2,
    )
    return response


def _anonymous_render(request: Request, template: str, context: dict, *, status_code: int = 200):
    """Rend un formulaire anonyme en posant le jeton CSRF dès le premier affichage.

    Sans cela, un visiteur sans cookie ``cl_csrf`` recevrait un champ caché vide
    alors que la réponse vient de poser un cookie différent : le premier envoi
    serait toujours refusé par la protection CSRF.
    """
    existing = request.cookies.get(CSRF_COOKIE)
    token = existing or new_csrf_token()
    response = render(request, template, {**context, "csrf_token": token}, status_code=status_code)
    if not existing:
        _set_csrf_cookie(response, token)
    return response


def _login_page(request: Request, db, *, error: str = "", next_url: str = "", status_code: int = 200, email: str = ""):
    context = load_context(request, db)
    if context is not None:
        return RedirectResponse("/", status_code=303)
    return _anonymous_render(
        request,
        "auth/login.html",
        {"error": error, "next_url": next_url, "email": email},
        status_code=status_code,
    )


@router.get("/login")
def login_page(request: Request, db: OrmSession = Depends(get_db), next: str = ""):
    return _login_page(request, db, next_url=next)


@router.post("/login")
def login_submit(
    request: Request,
    db: OrmSession = Depends(get_db),
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
):
    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    generic_error = "Identifiants incorrects. Vérifiez votre e-mail et votre mot de passe."

    if user is None or not user.is_active:
        audit.log(db, action="login_failed", user_id=user.id if user else None, details={"email": email}, request=request)
        db.commit()
        return _login_page(request, db, error=generic_error, next_url=next, status_code=401, email=email)

    if user.locked_until is not None and user.locked_until > utcnow():
        audit.log(db, action="login_locked", user_id=user.id, request=request, commit=True)
        return _login_page(
            request,
            db,
            error="Compte temporairement verrouillé après plusieurs échecs. Réessayez dans quelques minutes.",
            next_url=next,
            status_code=423,
            email=email,
        )

    if not verify_password(password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        audit.log(db, action="login_failed", user_id=user.id, details={"email": email}, request=request)
        db.commit()
        return _login_page(request, db, error=generic_error, next_url=next, status_code=401, email=email)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    membership = db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.id)
    ).scalars().first()
    token, _ = start_session(db, user, request, membership.organization_id if membership else None)
    audit.log(
        db,
        action="login",
        organization_id=membership.organization_id if membership else None,
        user_id=user.id,
        request=request,
    )
    db.commit()

    destination = "/"
    if next.startswith("/") and not next.startswith("//"):
        destination = next
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        "cl_session",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * settings.session_days,
    )
    response.delete_cookie(CSRF_COOKIE)
    return response


@router.get("/register")
def register_page(request: Request, db: OrmSession = Depends(get_db)):
    if load_context(request, db) is not None:
        return RedirectResponse("/", status_code=303)
    return _anonymous_render(request, "auth/register.html", {"error": "", "form": {}})


@router.post("/register")
def register_submit(
    request: Request,
    db: OrmSession = Depends(get_db),
    full_name: str = Form(""),
    company_name: str = Form(""),
    ice: str = Form(""),
    sector: str = Form(""),
    company_size: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    form = {
        "full_name": full_name.strip(),
        "company_name": company_name.strip(),
        "ice": ice.strip(),
        "sector": sector.strip(),
        "company_size": company_size.strip(),
        "email": email.strip().lower(),
    }
    errors: list[str] = []
    if not form["full_name"]:
        errors.append("Votre nom est obligatoire.")
    if not form["company_name"]:
        errors.append("Le nom de l'entreprise est obligatoire.")
    if not EMAIL_RE.match(form["email"]):
        errors.append("L'adresse e-mail n'est pas valide.")
    if password != password_confirm:
        errors.append("Les deux mots de passe ne correspondent pas.")
    errors.extend(password_problems(password, email=form["email"]))
    if not errors:
        existing = db.execute(select(User).where(User.email == form["email"])).scalars().first()
        if existing is not None:
            errors.append("Un compte existe déjà avec cette adresse e-mail. Connectez-vous.")

    if errors:
        return _anonymous_render(
            request,
            "auth/register.html",
            {"error": " ".join(errors), "form": form},
            status_code=400,
        )

    user = User(email=form["email"], password_hash=hash_password(password), full_name=form["full_name"])
    db.add(user)
    db.flush()
    organization = Organization(
        name=form["company_name"],
        ice=form["ice"],
        sector=form["sector"],
        company_size=form["company_size"],
    )
    db.add(organization)
    db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="proprietaire"))
    db.flush()
    token, _ = start_session(db, user, request, organization.id)
    audit.log(
        db,
        action="organization_created",
        organization_id=organization.id,
        user_id=user.id,
        entity_type="organization",
        entity_id=organization.id,
        details={"nom": organization.name},
        request=request,
    )
    db.commit()

    response = RedirectResponse("/onboarding", status_code=303)
    response.set_cookie(
        "cl_session",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * settings.session_days,
    )
    response.delete_cookie(CSRF_COOKIE)
    return response


@router.post("/logout")
def logout(request: Request, db: OrmSession = Depends(get_db)):
    context = load_context(request, db)
    if context is not None:
        audit.log(db, action="logout", organization_id=context.organization.id, user_id=context.user.id, request=request)
    end_session(db, request)
    db.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("cl_session")
    return response


# ---------------------------------------------------------------------------
# Assistant de première connexion
# ---------------------------------------------------------------------------
@router.get("/onboarding")
def onboarding_page(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    if context.organization.onboarding_done:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "onboarding.html",
        page_context(request, db, context, "dashboard"),
    )


@router.post("/onboarding")
def onboarding_submit(
    request: Request,
    db: OrmSession = Depends(get_db),
    sector: str = Form(""),
    company_size: str = Form(""),
    action: str = Form("skip"),
):
    context = require_context(request, db)
    organization = context.organization
    organization.sector = sector.strip() or organization.sector
    organization.company_size = company_size.strip() or organization.company_size
    organization.onboarding_done = True
    if action == "demo":
        summary = load_demo_data(db, organization, context.user.id)
        flash(
            db,
            context,
            "success",
            f"Données de démonstration chargées : {summary['expenses']} dépenses, "
            f"{summary['carbon_records']} enregistrements carbone, {summary['projects']} projets de décision "
            "(clairement identifiés « Démonstration »).",
        )
        audit.log(
            db,
            action="demo_data_loaded",
            organization_id=organization.id,
            user_id=context.user.id,
            details=summary,
            request=request,
        )
    else:
        flash(db, context, "info", "Bienvenue ! Commencez par enregistrer une dépense ou créer une décision à comparer.")
    db.commit()
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------
def _find_invitation(db: OrmSession, token: str) -> Invitation | None:
    invitation = db.execute(
        select(Invitation).where(Invitation.token_hash == token_hash(token))
    ).scalars().first()
    if invitation is None or invitation.accepted_at is not None or invitation.expires_at < utcnow():
        return None
    return invitation


@router.get("/invite/{token}")
def invite_page(token: str, request: Request, db: OrmSession = Depends(get_db)):
    invitation = _find_invitation(db, token)
    if invitation is None:
        return _anonymous_render(
            request,
            "auth/invite.html",
            {"invitation": None, "error": "Cette invitation est invalide ou expirée."},
            status_code=410,
        )
    organization = db.get(Organization, invitation.organization_id)
    existing = db.execute(select(User).where(User.email == invitation.email)).scalars().first()
    return _anonymous_render(
        request,
        "auth/invite.html",
        {
            "invitation": invitation,
            "organization": organization,
            "existing_user": existing is not None,
            "error": "",
        },
    )


@router.post("/invite/{token}")
def invite_submit(
    token: str,
    request: Request,
    db: OrmSession = Depends(get_db),
    full_name: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    invitation = _find_invitation(db, token)
    if invitation is None:
        return _anonymous_render(
            request,
            "auth/invite.html",
            {"invitation": None, "error": "Cette invitation est invalide ou expirée."},
            status_code=410,
        )
    user = db.execute(select(User).where(User.email == invitation.email)).scalars().first()
    error = ""
    if user is None:
        error_list = []
        if password != password_confirm:
            error_list.append("Les deux mots de passe ne correspondent pas.")
        error_list.extend(password_problems(password, email=invitation.email))
        if error_list:
            error = " ".join(error_list)
        else:
            user = User(
                email=invitation.email,
                password_hash=hash_password(password),
                full_name=full_name.strip() or invitation.email.split("@")[0],
            )
            db.add(user)
            db.flush()
    if error:
        organization = db.get(Organization, invitation.organization_id)
        return _anonymous_render(
            request,
            "auth/invite.html",
            {
                "invitation": invitation,
                "organization": organization,
                "existing_user": False,
                "error": error,
            },
            status_code=400,
        )

    membership = db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == invitation.organization_id,
            OrganizationMember.user_id == user.id,
        )
    ).scalars().first()
    if membership is None:
        db.add(OrganizationMember(organization_id=invitation.organization_id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = utcnow()
    session_token, _ = start_session(db, user, request, invitation.organization_id)
    audit.log(
        db,
        action="invitation_accepted",
        organization_id=invitation.organization_id,
        user_id=user.id,
        entity_type="invitation",
        entity_id=invitation.id,
        request=request,
    )
    db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "cl_session",
        session_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * settings.session_days,
    )
    response.delete_cookie(CSRF_COOKIE)
    return response
