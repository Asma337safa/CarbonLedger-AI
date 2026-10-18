"""CarbonLedger AI — application Streamlit multi-utilisateurs.

Application complète sur Streamlit Community Cloud : page d'accueil, création
de compte, connexion, **un espace par entreprise** (données enregistrées en
base et isolées par organisation), page de paramètres et fonctionnalités de
pilotage : tableau de bord, dépenses, comptabilité carbone, comparateur de
décisions et simulations.

Principe : **aucun chiffre n'est recalculé à la main ici**. L'application
réutilise la couche métier de l'application FastAPI (dossier ``app/`` :
``app.calc``, ``app.services``, ``app.models``, ``app.security``), y compris
le hachage des mots de passe (scrypt), le jeu de démonstration officiel et
les mêmes moteurs de calcul financier et carbone.

Un nouvel utilisateur démarre avec un **espace vide** : le jeu de
démonstration (25 dépenses, 18 enregistrements carbone, 3 projets) ne se
charge que sur action volontaire, depuis le tableau de bord ou les
paramètres, et se supprime en un clic.

Base de données : SQLite par défaut (fichier local créé automatiquement).
Pour une sauvegarde permanente sur Streamlit Community Cloud, définir le
secret ``CARBONLEDGER_DATABASE_URL`` (PostgreSQL) — voir ``DEPLOYMENT.md``.

Lancement local : ``streamlit run streamlit_app.py``
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="CarbonLedger AI",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _streamlit_secret(name: str) -> str:
    """Lit un secret Streamlit sans échouer si aucun fichier de secrets n'existe."""
    try:
        value = st.secrets.get(name, "")
    except Exception:  # pas de secrets configurés (mode local)
        return ""
    return str(value or "")


# Le secret éventuel doit être posé AVANT l'import de la configuration.
if _streamlit_secret("CARBONLEDGER_DATABASE_URL"):
    os.environ.setdefault("CARBONLEDGER_DATABASE_URL", _streamlit_secret("CARBONLEDGER_DATABASE_URL"))

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.calc.dashboard import (  # noqa: E402
    category_breakdown,
    emissions_breakdown,
    resolve_period,
    summarize_expenses,
)
from app.calc.decision import ZERO, OptionInput  # noqa: E402
from app.calc.emissions import compute_emissions_kg, status_from_method  # noqa: E402
from app.calc.formatting import (  # noqa: E402
    fmt_date,
    fmt_kg,
    fmt_money,
    fmt_number,
    fmt_tco2e,
    to_decimal,
)
from app.config import settings  # noqa: E402
from app.db import init_db, is_postgres, session_scope  # noqa: E402
from app.enums import (  # noqa: E402
    CARBON_CATEGORIES,
    CARBON_STATUSES,
    EMISSION_METHODS,
    EXPENSE_CATEGORIES,
    MEMBER_ROLES,
    PRIORITIES,
    SCOPES,
    VERIFICATION_STATUSES,
)
from app.errors import ValidationError  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    CarbonRecord,
    DecisionOption,
    DecisionProject,
    EmissionFactor,
    Expense,
    Organization,
    OrganizationMember,
    User,
    utcnow,
)
from app.security import (  # noqa: E402
    hash_password,
    new_csrf_token,
    new_token,
    password_problems,
    token_hash,
    verify_password,
)
from app.services import audit  # noqa: E402
from app.services.compute import analyze, key_figures  # noqa: E402
from app.services.demo_data import delete_demo_data, load_demo_data  # noqa: E402
from app.services.factors_seed import seed_global_factors  # noqa: E402
from app.services.project_service import analyze_project  # noqa: E402


@st.cache_resource(show_spinner=False)
def _bootstrap() -> None:
    """Crée le schéma si besoin et garantit le catalogue global de facteurs."""
    init_db()
    seed_global_factors()


_bootstrap()

GITHUB_URL = "https://github.com/Asma337safa/CarbonLedger-AI"
PAGES = [
    "Tableau de bord",
    "Dépenses",
    "Comptabilité carbone",
    "Comparateur de décisions",
    "Simulations",
    "Paramètres",
]
COMPANY_SIZES = ["", "1–9", "10–49", "50–249", "250+"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MAX_FAILED_LOGINS = 8
LOCK_MINUTES = 15


# ---------------------------------------------------------------------------
# Design — palette et composants repris de la feuille de style d'origine
# ---------------------------------------------------------------------------
CSS = """
<style>
:root{
  --cl-vert:#176B4D; --cl-vert-clair:#DDF3E4; --cl-nuit:#172B4D;
  --cl-fond:#F8FAF9; --cl-gris:#64748B; --cl-bordure:#E2E8F0;
  --cl-ambre:#F4B942; --cl-rouge:#D9534F;
  --cl-ombre:0 1px 2px rgba(23,43,77,.06), 0 4px 12px rgba(23,43,77,.05);
}
html, body, [class*="st-"]{
  font-family:"Inter","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
}
.stApp{ background:var(--cl-fond); }

/* Barre latérale bleu nuit (design d'origine) */
[data-testid="stSidebar"]{ background:var(--cl-nuit); }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3{ color:#fff; }
[data-testid="stSidebar"] p{ color:#A9B6CC; }
[data-testid="stSidebar"] .cl-brand__name{ color:#fff; }
[data-testid="stSidebar"] hr{ border-color:rgba(255,255,255,.12); }
[data-testid="stSidebar"] [role="radiogroup"]{ gap:2px; }
[data-testid="stSidebar"] [role="radiogroup"] label{
  display:flex; align-items:center; width:100%; padding:8px 10px; margin:0;
  border-radius:7px; border:1px solid transparent; cursor:pointer;
  transition:background .15s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ background:rgba(255,255,255,.07); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:rgba(23,107,77,.85); border-color:rgba(221,243,228,.35);
}
[data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child{ display:none; }
[data-testid="stSidebar"] [role="radiogroup"] p{ color:#C6D2E3; font-size:14px; margin:0; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{ color:#fff; font-weight:600; }

/* Cartes, KPI et badges */
.cl-brand{ display:flex; align-items:center; gap:10px; margin:2px 0 14px; }
.cl-brand__mark{
  width:38px; height:38px; border-radius:9px; background:var(--cl-vert); color:#fff;
  display:inline-flex; align-items:center; justify-content:center;
  font-weight:700; font-size:15px; flex:0 0 auto;
}
.cl-brand__name{ font-weight:700; font-size:15px; line-height:1.15; }
.cl-brand__sub{ font-size:11.5px; color:#A9B6CC; }
.cl-hero{
  background:linear-gradient(135deg,#172B4D 0%,#1C3A5E 55%,#176B4D 140%);
  border-radius:16px; padding:36px 34px 30px; box-shadow:var(--cl-ombre);
}
.cl-hero h1{ color:#fff; font-size:30px; line-height:1.2; margin:14px 0 10px; letter-spacing:-.01em; }
.cl-hero p{ color:#C7D4E6; font-size:15px; max-width:760px; margin:0; }
.cl-hero__brand{ display:flex; align-items:center; gap:10px; }
.cl-hero__brandname{ color:#fff; font-weight:650; font-size:15px; }
.cl-card{
  background:#fff; border:1px solid var(--cl-bordure); border-radius:11px;
  box-shadow:var(--cl-ombre); padding:16px 18px; height:100%;
}
.cl-card h3{ margin:0 0 6px; font-size:15.5px; color:var(--cl-nuit); }
.cl-card p{ margin:0; color:var(--cl-gris); font-size:13.5px; line-height:1.5; }
.cl-kpi{
  background:#fff; border:1px solid var(--cl-bordure); border-left:4px solid var(--cl-vert);
  border-radius:11px; box-shadow:var(--cl-ombre); padding:13px 15px; height:100%;
}
.cl-kpi--nuit{ border-left-color:var(--cl-nuit); }
.cl-kpi--ambre{ border-left-color:var(--cl-ambre); }
.cl-kpi--rouge{ border-left-color:var(--cl-rouge); }
.cl-kpi__label{
  font-size:11.5px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--cl-gris); font-weight:600; margin-bottom:4px;
}
.cl-kpi__value{ font-size:21px; font-weight:700; color:var(--cl-nuit); overflow-wrap:anywhere; }
.cl-kpi__sub{ font-size:12.5px; color:var(--cl-gris); margin-top:3px; }
.cl-badge{
  display:inline-block; padding:2px 10px; border-radius:99px; font-size:11.5px;
  font-weight:650; border:1px solid transparent; margin-bottom:8px;
}
.cl-badge--demo{ background:#FFF4DB; color:#8A5B00; border-color:#F4D89B; }
.cl-badge--ok{ background:var(--cl-vert-clair); color:var(--cl-vert); border-color:#BEE7CC; }
.cl-empty{
  background:#fff; border:1px dashed #C9D4E2; border-radius:11px;
  padding:24px 22px; color:var(--cl-gris);
}
.cl-empty h3{ color:var(--cl-nuit); margin:0 0 6px; font-size:16px; }
.cl-empty p{ margin:0; font-size:13.5px; line-height:1.55; }
.cl-steps{ display:flex; gap:12px; flex-wrap:wrap; }
.cl-step{
  flex:1 1 210px; background:#fff; border:1px solid var(--cl-bordure);
  border-radius:11px; box-shadow:var(--cl-ombre); padding:14px 16px;
}
.cl-step__num{
  width:26px; height:26px; border-radius:50%; background:var(--cl-vert-clair);
  color:var(--cl-vert); display:inline-flex; align-items:center; justify-content:center;
  font-weight:700; font-size:13px; margin-bottom:8px;
}
.cl-step strong{ display:block; color:var(--cl-nuit); font-size:13.5px; margin-bottom:3px; }
.cl-step span{ color:var(--cl-gris); font-size:12.5px; }
.cl-footer{ color:var(--cl-gris); font-size:12px; margin-top:14px; }
.stButton > button{ border-radius:7px; font-weight:600; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Authentification : session navigateur (jeton), inscription, connexion
# ---------------------------------------------------------------------------
FLASH_KEY = "_flash"


@dataclass
class Espace:
    """Utilisateur connecté + organisation courante (instantané de session)."""

    user_id: int
    user_name: str
    user_email: str
    org_id: int
    org_name: str
    org_role: str
    demo_loaded: bool


def _flash(level: str, message: str) -> None:
    st.session_state[FLASH_KEY] = (level, message)


def _show_flash() -> None:
    item = st.session_state.pop(FLASH_KEY, None)
    if not item:
        return
    level, message = item
    {"success": st.success, "warning": st.warning, "error": st.error}.get(level, st.info)(message)


def _query_token() -> str:
    try:
        return str(st.query_params.get("s", "") or "")
    except Exception:
        return ""


def _set_query_token(token: str) -> None:
    try:
        st.query_params["s"] = token
    except Exception:
        pass


def _clear_query_token() -> None:
    try:
        if "s" in st.query_params:
            del st.query_params["s"]
    except Exception:
        pass


def _forget_login() -> None:
    for key in ("user_id", "org_id", "token"):
        st.session_state.pop(key, None)


def _new_db_session(db, user_id: int, organization_id: int) -> str:
    """Ouvre une session navigateur : jeton aléatoire, empreinte SHA-256 en base."""
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    token = new_token()
    db.add(
        AuthSession(
            id=token_hash(token),
            user_id=user_id,
            organization_id=organization_id,
            csrf_token=new_csrf_token(),
            expires_at=utcnow() + timedelta(days=settings.session_days),
        )
    )
    return token


def _apply_login(user_id: int, organization_id: int, token: str) -> None:
    st.session_state["user_id"] = user_id
    st.session_state["org_id"] = organization_id
    st.session_state["token"] = token
    _set_query_token(token)


def _restore_from_token() -> None:
    """Restaure la session après un rafraîchissement du navigateur (jeton en URL)."""
    if st.session_state.get("user_id"):
        return
    token = _query_token()
    if not token:
        return
    restored = False
    with session_scope() as db:
        row = db.get(AuthSession, token_hash(token))
        if row is not None and row.expires_at > utcnow():
            st.session_state["user_id"] = row.user_id
            st.session_state["org_id"] = row.organization_id
            st.session_state["token"] = token
            row.last_seen_at = utcnow()
            restored = True
        elif row is not None:
            db.delete(row)
    if not restored:
        _clear_query_token()


def espace_courant() -> Espace | None:
    """Utilisateur + organisation courants, ou ``None`` si non connecté."""
    _restore_from_token()
    user_id = st.session_state.get("user_id")
    if not user_id:
        return None
    with session_scope() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            _forget_login()
            _clear_query_token()
            return None
        memberships = (
            db.execute(
                select(OrganizationMember)
                .where(OrganizationMember.user_id == user.id)
                .order_by(OrganizationMember.id)
            )
            .scalars()
            .all()
        )
        preferred = st.session_state.get("org_id")
        membership = next((m for m in memberships if m.organization_id == preferred), None)
        if membership is None and memberships:
            membership = memberships[0]
        if membership is None:
            organization = Organization(name=f"Espace de {user.full_name or user.email}")
            db.add(organization)
            db.flush()
            membership = OrganizationMember(
                organization_id=organization.id, user_id=user.id, role="proprietaire"
            )
            db.add(membership)
            db.flush()
        organization = db.get(Organization, membership.organization_id)
        st.session_state["org_id"] = organization.id
        return Espace(
            user_id=user.id,
            user_name=user.full_name or user.email,
            user_email=user.email,
            org_id=organization.id,
            org_name=organization.name,
            org_role=membership.role,
            demo_loaded=bool(organization.demo_data_loaded),
        )


def deconnexion() -> None:
    token = st.session_state.pop("token", None)
    with session_scope() as db:
        if token:
            row = db.get(AuthSession, token_hash(token))
            if row is not None:
                audit.log(
                    db,
                    action="logout",
                    organization_id=st.session_state.get("org_id"),
                    user_id=st.session_state.get("user_id"),
                    details={"via": "streamlit"},
                )
                db.delete(row)
    _forget_login()
    _clear_query_token()
    st.session_state["auth_view"] = "accueil"


def inscrire(
    full_name: str,
    company: str,
    ice: str,
    sector: str,
    size: str,
    email: str,
    password: str,
    password_confirm: str,
) -> list[str]:
    """Inscription : crée l'utilisateur, son organisation et sa session."""
    errors: list[str] = []
    full_name = (full_name or "").strip()
    company = (company or "").strip()
    email = (email or "").strip().lower()
    if not full_name:
        errors.append("Indiquez votre nom.")
    if not company:
        errors.append("Indiquez le nom de votre entreprise.")
    if not email or not EMAIL_RE.match(email):
        errors.append("Adresse e-mail invalide.")
    if password != password_confirm:
        errors.append("Les deux mots de passe ne correspondent pas.")
    errors.extend(password_problems(password, email=email))
    if errors:
        return errors
    with session_scope() as db:
        existing = db.execute(select(User.id).where(User.email == email)).scalar_one_or_none()
        if existing is not None:
            return ["Un compte existe déjà avec cette adresse e-mail. Connectez-vous."]
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            last_login_at=utcnow(),
        )
        db.add(user)
        db.flush()
        organization = Organization(
            name=company,
            ice=(ice or "").strip(),
            sector=(sector or "").strip(),
            company_size=(size or "").strip(),
            onboarding_done=True,
        )
        db.add(organization)
        db.flush()
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="proprietaire"))
        db.flush()
        token = _new_db_session(db, user.id, organization.id)
        audit.log(
            db,
            action="organization_created",
            organization_id=organization.id,
            user_id=user.id,
            details={"email": email, "via": "streamlit"},
        )
        _apply_login(user.id, organization.id, token)
    return []


def connecter(email: str, password: str) -> tuple[bool, str]:
    """Connexion : mêmes règles que l'application FastAPI (verrouillage compris)."""
    email = (email or "").strip().lower()
    if not email or not password:
        return False, "Indiquez votre adresse e-mail et votre mot de passe."
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == email)).scalars().first()
        if user is None:
            audit.log(db, action="login_failed", details={"email": email, "via": "streamlit"})
            return False, "Adresse e-mail ou mot de passe incorrect."
        if user.locked_until and user.locked_until > utcnow():
            return False, (
                "Trop de tentatives : compte temporairement verrouillé. "
                "Réessayez dans quelques minutes."
            )
        if not user.is_active:
            return False, "Ce compte est désactivé."
        if not verify_password(password, user.password_hash):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
                user.failed_login_count = 0
            audit.log(db, action="login_failed", user_id=user.id, details={"email": email, "via": "streamlit"})
            return False, "Adresse e-mail ou mot de passe incorrect."
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        membership = (
            db.execute(
                select(OrganizationMember)
                .where(OrganizationMember.user_id == user.id)
                .order_by(OrganizationMember.id)
            )
            .scalars()
            .first()
        )
        organization_id = membership.organization_id if membership else None
        if organization_id is None:
            organization = Organization(name=f"Espace de {user.full_name or email}")
            db.add(organization)
            db.flush()
            db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="proprietaire"))
            db.flush()
            organization_id = organization.id
        token = _new_db_session(db, user.id, organization_id)
        audit.log(db, action="login", organization_id=organization_id, user_id=user.id, details={"via": "streamlit"})
        _apply_login(user.id, organization_id, token)
    return True, ""


# ---------------------------------------------------------------------------
# Accès aux données — chaque requête est filtrée par organisation (isolation)
# ---------------------------------------------------------------------------
def _org_row(org_id: int) -> dict:
    with session_scope() as db:
        organization = db.get(Organization, org_id)
        if organization is None:
            return {}
        return {
            "name": organization.name,
            "ice": organization.ice,
            "sector": organization.sector,
            "company_size": organization.company_size,
            "internal_carbon_price": organization.internal_carbon_price or ZERO,
            "demo_loaded": bool(organization.demo_data_loaded),
        }


def _counts(org_id: int) -> dict[str, int]:
    with session_scope() as db:
        return {
            "expenses": db.execute(
                select(func.count()).select_from(Expense).where(Expense.organization_id == org_id)
            ).scalar_one(),
            "records": db.execute(
                select(func.count()).select_from(CarbonRecord).where(CarbonRecord.organization_id == org_id)
            ).scalar_one(),
            "projects": db.execute(
                select(func.count()).select_from(DecisionProject).where(DecisionProject.organization_id == org_id)
            ).scalar_one(),
        }


def _load_overview(org_id: int, period_key: str) -> dict:
    resolved = resolve_period(period_key, today=date.today())
    with session_scope() as db:
        expenses = (
            db.execute(
                select(Expense)
                .where(
                    Expense.organization_id == org_id,
                    Expense.expense_date >= resolved.start,
                    Expense.expense_date <= resolved.end,
                )
                .order_by(Expense.expense_date.desc(), Expense.id.desc())
            )
            .scalars()
            .all()
        )
        records = (
            db.execute(
                select(CarbonRecord)
                .options(selectinload(CarbonRecord.emission_factor))
                .where(
                    CarbonRecord.organization_id == org_id,
                    CarbonRecord.period_start <= resolved.end,
                    CarbonRecord.period_end >= resolved.start,
                )
            )
            .scalars()
            .all()
        )
        project_count = db.execute(
            select(func.count()).select_from(DecisionProject).where(DecisionProject.organization_id == org_id)
        ).scalar_one()
        expense_summary = summarize_expenses(expenses)
        emission_summary, emission_rows = emissions_breakdown(records)
        spend_rows = category_breakdown(expenses)
        recent = [
            {
                "Date": fmt_date(expense.expense_date),
                "Fournisseur": expense.supplier or "—",
                "Catégorie": EXPENSE_CATEGORIES.get(expense.category, expense.category),
                "Montant HT": fmt_money(expense.amount_ht),
                "Statut": VERIFICATION_STATUSES.get(expense.verification_status, expense.verification_status),
            }
            for expense in expenses[:6]
        ]
        return {
            "period_label": resolved.label,
            "period_bounds": (
                "toutes les données enregistrées"
                if resolved.key == "tout"
                else f"{fmt_date(resolved.start)} → {fmt_date(resolved.end)}"
            ),
            "expense_summary": expense_summary,
            "emission_summary": emission_summary,
            "spend_rows": spend_rows,
            "emission_rows": emission_rows,
            "recent": recent,
            "project_count": project_count,
            "expenses_count": len(expenses),
            "records_count": len(records),
        }


def _load_expenses(org_id: int) -> pd.DataFrame:
    with session_scope() as db:
        expenses = (
            db.execute(
                select(Expense)
                .where(Expense.organization_id == org_id)
                .order_by(Expense.expense_date.desc(), Expense.id.desc())
            )
            .scalars()
            .all()
        )
        rows = [
            {
                "_id": expense.id,
                "_date": expense.expense_date,
                "_ht": expense.amount_ht or ZERO,
                "Date": fmt_date(expense.expense_date),
                "Fournisseur": expense.supplier or "—",
                "Catégorie": EXPENSE_CATEGORIES.get(expense.category, expense.category),
                "Description": expense.description or "",
                "Montant HT": fmt_money(expense.amount_ht),
                "TVA": fmt_money(expense.vat_amount),
                "Montant TTC": fmt_money(expense.amount_ttc),
                "Statut": VERIFICATION_STATUSES.get(expense.verification_status, expense.verification_status),
            }
            for expense in expenses
        ]
    return pd.DataFrame(rows)


def _load_carbon(org_id: int) -> dict:
    with session_scope() as db:
        records = (
            db.execute(
                select(CarbonRecord)
                .options(selectinload(CarbonRecord.emission_factor))
                .where(CarbonRecord.organization_id == org_id)
                .order_by(CarbonRecord.period_start.desc(), CarbonRecord.id.desc())
            )
            .scalars()
            .all()
        )
        summary, category_rows = emissions_breakdown(records)
        by_scope: dict[str, Decimal] = {}
        by_status: dict[str, Decimal] = {}
        rows = []
        for record in records:
            factor = record.emission_factor
            scope = factor.scope if factor else ""
            by_scope[scope] = by_scope.get(scope, ZERO) + (record.kgco2e or ZERO)
            status = record.status or "calcule"
            by_status[status] = by_status.get(status, ZERO) + (record.kgco2e or ZERO)
            rows.append(
                {
                    "Période": f"{fmt_date(record.period_start)} → {fmt_date(record.period_end)}",
                    "Poste": CARBON_CATEGORIES.get(record.category, record.category),
                    "Activité": f"{fmt_number(record.activity_quantity)} {record.activity_unit}",
                    "Facteur": factor.label if factor else "—",
                    "kg CO₂e": fmt_number(record.kgco2e, 1),
                    "Méthode": EMISSION_METHODS.get(record.method, record.method),
                    "Statut": CARBON_STATUSES.get(status, status),
                    "Source": (factor.source_name if factor else "") or "—",
                }
            )
        return {
            "summary": summary,
            "category_rows": category_rows,
            "by_scope": by_scope,
            "by_status": by_status,
            "rows": rows,
            "count": len(records),
        }


def _load_factors(org_id: int) -> list[dict]:
    """Facteurs globaux documentés + facteurs personnalisés de l'organisation."""
    with session_scope() as db:
        factors = (
            db.execute(
                select(EmissionFactor)
                .where(
                    (EmissionFactor.organization_id.is_(None))
                    | (EmissionFactor.organization_id == org_id)
                )
                .order_by(EmissionFactor.scope, EmissionFactor.code)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": factor.id,
                "code": factor.code,
                "label": factor.label,
                "unit": factor.unit,
                "scope": factor.scope,
                "method": factor.method,
                "confidence": factor.confidence,
                "kgco2e_per_unit": factor.kgco2e_per_unit,
                "source_name": factor.source_name,
            }
            for factor in factors
        ]


def _load_projects(org_id: int) -> list[dict]:
    with session_scope() as db:
        projects = (
            db.execute(
                select(DecisionProject)
                .options(selectinload(DecisionProject.options))
                .where(DecisionProject.organization_id == org_id)
                .order_by(DecisionProject.id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": project.id,
                "title": project.title,
                "horizon": project.horizon_years,
                "option_count": len(project.options),
                "priority": project.priority,
                "is_demo": bool(project.is_demo),
            }
            for project in projects
        ]


def _analyze_project(project_id: int, org_id: int, priority: str, with_scenarios: bool):
    """Analyse d'un projet — double filtre (id + organisation) par sécurité."""
    with session_scope() as db:
        project = (
            db.execute(
                select(DecisionProject)
                .options(selectinload(DecisionProject.options))
                .where(
                    DecisionProject.id == project_id,
                    DecisionProject.organization_id == org_id,
                )
            )
            .scalar_one()
        )
        return analyze_project(
            project,
            priority=priority,
            with_scenarios=with_scenarios,
            with_sensitivity=not with_scenarios,
            with_charts=True,
        )


def _load_demo(ctx: Espace) -> None:
    with session_scope() as db:
        organization = db.get(Organization, ctx.org_id)
        if organization is None:
            return
        summary = load_demo_data(db, organization, created_by_id=ctx.user_id)
        audit.log(
            db,
            action="demo_data_loaded",
            organization_id=organization.id,
            user_id=ctx.user_id,
            details={**summary, "via": "streamlit"},
        )
    _flash(
        "success",
        f"Jeu de démonstration chargé : {summary['expenses']} dépenses, "
        f"{summary['carbon_records']} données carbone, {summary['projects']} projets. "
        "Supprimable à tout moment depuis les Paramètres.",
    )


def _delete_demo(ctx: Espace) -> None:
    with session_scope() as db:
        organization = db.get(Organization, ctx.org_id)
        if organization is None:
            return
        summary = delete_demo_data(db, organization)
        audit.log(
            db,
            action="demo_data_deleted",
            organization_id=organization.id,
            user_id=ctx.user_id,
            details={**summary, "via": "streamlit"},
        )
    _flash("success", "Données de démonstration supprimées. Vos données personnelles sont conservées.")


# ---------------------------------------------------------------------------
# Petits blocs d'interface (style CarbonLedger)
# ---------------------------------------------------------------------------
def _kpi(column, title: str, value: str, subtitle: str = "", tone: str = "") -> None:
    tone_class = f" cl-kpi--{tone}" if tone else ""
    sub = f'<div class="cl-kpi__sub">{subtitle}</div>' if subtitle else ""
    column.markdown(
        f'<div class="cl-kpi{tone_class}">'
        f'<div class="cl-kpi__label">{title}</div>'
        f'<div class="cl-kpi__value">{value}</div>{sub}</div>',
        unsafe_allow_html=True,
    )


def _svg(markup: str) -> None:
    if markup:
        st.markdown(markup, unsafe_allow_html=True)


def _delta_money(value, is_base: bool) -> str:
    if is_base or value is None:
        return "—"
    return fmt_money(value, sign=True)


def _delta_t(value, is_base: bool) -> str:
    if is_base or value is None:
        return "—"
    return f"{fmt_number(value, 2)} t"


def _brand(subtitle: str) -> None:
    st.sidebar.markdown(
        '<div class="cl-brand"><span class="cl-brand__mark">CL</span>'
        f'<div><div class="cl-brand__name">CarbonLedger AI</div>'
        f'<div class="cl-brand__sub">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def _goto_page(page: str) -> None:
    """Callback de bouton : change la page de navigation sans conflit de widget."""
    st.session_state["nav"] = page


def priority_selector(key: str, default: str = "equilibre") -> str:
    labels = list(PRIORITIES.values())
    label_by_code = {code: label for code, label in PRIORITIES.items()}
    chosen = st.radio(
        "Priorité de décision",
        labels,
        index=labels.index(label_by_code.get(default, label_by_code["equilibre"])),
        key=key,
    )
    return {label: code for label, code in zip(labels, PRIORITIES.keys())}[chosen]


def _parse_montants(ht_text: str, vat_text: str, ttc_text: str) -> tuple[list[str], dict | None]:
    """Contrôle et complète les montants HT / TVA / TTC (logique d'origine)."""
    errors: list[str] = []

    def _val(text: str, label: str):
        text = (text or "").strip()
        if not text:
            return None
        value = to_decimal(text)
        if value is None or value < 0:
            errors.append(f"Montant « {label} » invalide (exemple : 12 500,00).")
            return None
        return value

    ht = _val(ht_text, "HT")
    vat = _val(vat_text, "TVA")
    ttc = _val(ttc_text, "TTC")
    if errors:
        return errors, None
    if ht is None and ttc is None:
        return ["Saisissez au moins un montant HT ou TTC."], None
    vat = vat if vat is not None else ZERO
    if ttc is None:
        ttc = ht + vat
    if ht is None:
        ht = ttc - vat
    return [], {"ht": ht, "vat": vat, "ttc": ttc}


def render_analysis(analysis) -> None:
    """Affichage commun d'une analyse : chiffres clés, tableau, arbitrage, graphiques."""
    comparison = analysis.comparison
    arbitration = analysis.arbitration
    figures = key_figures(analysis)

    cols = st.columns(4)
    _kpi(
        cols[0],
        "Coût total le plus faible",
        fmt_money(figures["cheapest_cost"]) if figures["cheapest_cost"] else "—",
        f"« {figures['cheapest_name']} »" if figures["cheapest_name"] else "",
    )
    _kpi(
        cols[1],
        "Émissions cumulées les plus faibles",
        fmt_tco2e(figures["greenest_emissions_t"]) if figures["greenest_emissions_t"] else "non renseignées",
        f"« {figures['greenest_name']} »" if figures["greenest_name"] else "",
        tone="nuit",
    )
    if figures["cost_per_tonne_avoided"] is not None:
        suffix = "économisés (gain double)" if figures["double_gain"] else "de surcoût"
        subtitle = f"{fmt_tco2e(figures['avoided_t'])} évitées" if figures["avoided_t"] else ""
        _kpi(
            cols[2],
            "Coût par tonne évitée",
            f"{fmt_money(abs(Decimal(figures['cost_per_tonne_avoided'])))} /t",
            f"{suffix} · {subtitle}" if subtitle else suffix,
            tone="ambre",
        )
    else:
        _kpi(cols[2], "Coût par tonne évitée", "non disponible", "émissions manquantes", tone="ambre")
    if figures["break_even_years"]:
        _kpi(
            cols[3],
            "Délai de rattrapage",
            f"≈ {fmt_number(figures['break_even_years'], 1)} ans",
            "surcoût initial compensé par les coûts annuels",
        )
    else:
        _kpi(cols[3], "Horizon de comparaison", f"{comparison.horizon_years} ans", "")

    st.caption(f"Règle de calcul — {analysis.formula}")

    table = pd.DataFrame(
        [
            {
                "Option": result.name,
                "Mise de fonds": fmt_money(result.initial_outlay),
                f"Coût total ({comparison.horizon_years} ans)": fmt_money(result.total_cost),
                "Émissions cumulées": fmt_tco2e(result.total_emissions_t)
                if result.total_emissions_t is not None
                else "non renseignées",
                "Économies déclarées": fmt_money(result.total_savings),
            }
            for result in comparison.results
        ]
    )
    st.dataframe(table)

    left, right = st.columns(2)
    with left:
        st.markdown("**Coût total et mise de fonds par option**")
        _svg(analysis.charts.get("cost_totals", ""))
        st.markdown("**Coûts cumulés année par année**")
        _svg(analysis.charts.get("cost_curve", ""))
    with right:
        st.markdown("**Émissions cumulées par option**")
        _svg(analysis.charts.get("emissions_totals", ""))
        st.markdown("**Émissions cumulées année par année**")
        _svg(analysis.charts.get("emissions_curve", ""))

    st.markdown(f"### {arbitration.recommendation_title}")
    for paragraph in arbitration.recommendation_paragraphs:
        st.markdown(paragraph)
    st.caption(arbitration.method_note)

    with st.expander("Évaluation détaillée par option"):
        for assessment in arbitration.ranking:
            st.markdown(f"**{assessment.rank}. {assessment.name}**")
            for advantage in assessment.advantages:
                st.markdown(f"- ✅ {advantage}")
            for drawback in assessment.disadvantages:
                st.markdown(f"- ⚠️ {drawback}")
            for fact in assessment.facts:
                st.markdown(f"- {fact}")

    if analysis.sensitivity_lines:
        with st.expander("Sensibilité aux hypothèses (± 10 %, une à la fois)"):
            for line in analysis.sensitivity_lines:
                st.markdown(f"- {line}")

    if arbitration.caveats:
        with st.expander("Limites et avertissements"):
            for caveat in arbitration.caveats:
                st.markdown(f"- {caveat}")

    for check in analysis.missing_data:
        if check["level"] == "attention":
            st.warning(check["message"])
        else:
            st.info(check["message"])


# ---------------------------------------------------------------------------
# Pages publiques : accueil, inscription, connexion
# ---------------------------------------------------------------------------
HERO_HTML = """
<div class="cl-hero">
  <div class="cl-hero__brand"><span class="cl-brand__mark">CL</span>
  <span class="cl-hero__brandname">CarbonLedger AI</span></div>
  <h1>La décision financière et carbone, sur la même base.</h1>
  <p>CarbonLedger AI aide les PME marocaines à piloter leurs coûts et leurs émissions
  dans un même espace : dépenses en dirhams, registre carbone vérifiable
  (quantité × facteur documenté), comparateur de décisions avec arbitrage expliqué —
  sans jamais inventer de chiffre.</p>
</div>
"""


def page_accueil() -> None:
    st.markdown(HERO_HTML, unsafe_allow_html=True)
    st.write("")
    cta_left, cta_right, _spacer = st.columns([1, 1, 1.6])
    with cta_left:
        if st.button("Créer un compte entreprise", key="go_register", type="primary", use_container_width=True):
            st.session_state["auth_view"] = "inscription"
            st.rerun()
    with cta_right:
        if st.button("Se connecter", key="go_login", use_container_width=True):
            st.session_state["auth_view"] = "connexion"
            st.rerun()

    st.write("")
    cards = [
        (
            "Coûts et carbone réunis",
            "Chaque effort est chiffré en dirhams et en kg CO₂e : deux lectures d'une même décision, "
            "avec le coût par tonne évitée et le délai de rattrapage.",
        ),
        (
            "Des chiffres vérifiables",
            "Facteurs d'émission documentés (source, unité, périmètre), statut mesuré / calculé / estimé. "
            "Une donnée absente reste affichée comme absente : aucune estimation silencieuse.",
        ),
        (
            "Un espace par entreprise",
            "Un compte = une organisation : vos données sont enregistrées et isolées des autres entreprises. "
            "Vous démarrez avec un espace vide — la démonstration se charge uniquement à votre demande.",
        ),
    ]
    columns = st.columns(3)
    for column, (title, text) in zip(columns, cards):
        column.markdown(
            f'<div class="cl-card"><h3>{title}</h3><p>{text}</p></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown("##### Comment ça marche")
    steps = [
        ("1", "Créez votre compte", "Votre organisation est créée automatiquement — aucune carte bancaire, aucun prérequis."),
        ("2", "Saisissez vos données", "Dépenses et données carbone, ou chargez le jeu de démonstration pour explorer l'application."),
        ("3", "Décidez avec méthode", "Comparez vos options : coût complet, émissions cumulées, arbitrage expliqué selon votre priorité."),
    ]
    step_html = "".join(
        f'<div class="cl-step"><div class="cl-step__num">{num}</div>'
        f"<strong>{title}</strong><span>{text}</span></div>"
        for num, title, text in steps
    )
    st.markdown(f'<div class="cl-steps">{step_html}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="cl-footer">Moteurs de calcul à découvert · montants en MAD (DH) · '
        f'<a href="{GITHUB_URL}">code source sur GitHub</a></div>',
        unsafe_allow_html=True,
    )


def page_inscription() -> None:
    _spacer_left, middle, _spacer_right = st.columns([1, 1.35, 1])
    with middle:
        st.markdown("## Créer votre compte entreprise")
        st.caption("Un compte = une organisation. Vos données restent isolées des autres entreprises.")
        with st.container(border=True):
            name = st.text_input("Votre nom *", key="reg_name", placeholder="Ex. Amina Berrada")
            company = st.text_input(
                "Nom de l'entreprise *", key="reg_company", placeholder="Ex. Atlas Confection SARL"
            )
            col_a, col_b = st.columns(2)
            with col_a:
                ice = st.text_input("ICE (Maroc)", key="reg_ice", placeholder="Identifiant Commun de l'Entreprise")
                sector = st.text_input("Secteur d'activité", key="reg_sector", placeholder="Ex. agroalimentaire, textile…")
            with col_b:
                size = st.selectbox("Taille de l'entreprise", COMPANY_SIZES, key="reg_size")
                email = st.text_input("Adresse e-mail *", key="reg_email", placeholder="vous@entreprise.ma")
            password = st.text_input(
                "Mot de passe *",
                type="password",
                key="reg_password",
                help="8 caractères minimum, avec au moins une lettre et un chiffre ; différent de l'adresse e-mail.",
            )
            password_confirm = st.text_input("Confirmation du mot de passe *", type="password", key="reg_password2")
            if st.button("Créer mon compte", key="reg_submit", type="primary", use_container_width=True):
                errors = inscrire(name, company, ice, sector, size, email, password, password_confirm)
                if errors:
                    for message in errors:
                        st.error(message)
                else:
                    _flash(
                        "success",
                        f"Bienvenue {name.strip()} ! Votre espace « {company.strip()} » est prêt — il est vide. "
                        "Saisissez vos premières données ou chargez le jeu de démonstration depuis le tableau de bord.",
                    )
                    st.rerun()
        st.write("")
        row_left, row_right = st.columns(2)
        with row_left:
            if st.button("J'ai déjà un compte", key="reg_to_login", use_container_width=True):
                st.session_state["auth_view"] = "connexion"
                st.rerun()
        with row_right:
            if st.button("← Accueil", key="reg_home", use_container_width=True):
                st.session_state["auth_view"] = "accueil"
                st.rerun()


def page_connexion() -> None:
    _spacer_left, middle, _spacer_right = st.columns([1, 1.35, 1])
    with middle:
        st.markdown("## Connexion")
        st.caption("Accédez au pilotage de vos coûts et de vos émissions.")
        with st.container(border=True):
            email = st.text_input("Adresse e-mail", key="log_email", placeholder="vous@entreprise.ma")
            password = st.text_input("Mot de passe", type="password", key="log_password")
            if st.button("Se connecter", key="log_submit", type="primary", use_container_width=True):
                ok, message = connecter(email, password)
                if not ok:
                    st.error(message)
                else:
                    _flash("success", "Connexion réussie — bienvenue !")
                    st.rerun()
        st.write("")
        row_left, row_right = st.columns(2)
        with row_left:
            if st.button("Créer un compte entreprise", key="log_to_register", use_container_width=True):
                st.session_state["auth_view"] = "inscription"
                st.rerun()
        with row_right:
            if st.button("← Accueil", key="log_home", use_container_width=True):
                st.session_state["auth_view"] = "accueil"
                st.rerun()


# ---------------------------------------------------------------------------
# Pages de l'espace de travail
# ---------------------------------------------------------------------------
def page_dashboard(ctx: Espace) -> None:
    st.title("Tableau de bord")
    if ctx.demo_loaded:
        st.markdown(
            '<span class="cl-badge cl-badge--demo">Données de démonstration chargées — supprimables dans Paramètres</span>',
            unsafe_allow_html=True,
        )
    st.caption(f"Espace « {ctx.org_name} » — montants en dirhams (DH), émissions en kg CO₂e.")

    counts = _counts(ctx.org_id)
    if counts["expenses"] == 0 and counts["records"] == 0 and counts["projects"] == 0:
        st.markdown(
            '<div class="cl-empty"><h3>Votre espace est vide — c\'est normal !</h3>'
            "<p>Saisissez vos premières données depuis « Dépenses » et « Comptabilité carbone », ou créez une "
            "décision dans le « Comparateur ». Vous pouvez aussi charger le jeu de démonstration pour explorer "
            "l'application : 25 dépenses, 18 données carbone et 3 projets d'exemple, supprimables en un clic "
            "depuis les Paramètres.</p></div>",
            unsafe_allow_html=True,
        )
        st.write("")
        c_left, c_right, _pad = st.columns([1.1, 1.1, 1])
        with c_left:
            if st.button("Charger le jeu de démonstration", key="dash_load_demo", type="primary", use_container_width=True):
                _load_demo(ctx)
                st.rerun()
        with c_right:
            st.button(
                "Saisir ma première dépense",
                key="dash_go_expenses",
                use_container_width=True,
                on_click=_goto_page,
                args=("Dépenses",),
            )
        return

    period_label = st.radio(
        "Période analysée",
        ["Année en cours", "Tout l'historique"],
        horizontal=True,
        key="dash_period",
    )
    data = _load_overview(ctx.org_id, "annee" if period_label.startswith("Année") else "tout")
    expense_summary = data["expense_summary"]
    emission_summary = data["emission_summary"]

    st.caption(f"{data['period_label']} — {data['period_bounds']}")

    cols = st.columns(4)
    _kpi(cols[0], "Dépenses HT", fmt_money(expense_summary.total_ht), f"{data['expenses_count']} ligne(s)")
    _kpi(
        cols[1],
        "TVA",
        fmt_money(expense_summary.total_vat),
        f"TTC : {fmt_money(expense_summary.total_ttc)}",
        tone="nuit",
    )
    _kpi(
        cols[2],
        "Émissions",
        fmt_tco2e(emission_summary.total_t),
        f"{data['records_count']} enregistrement(s) · estimé : {fmt_number(emission_summary.estimated_share_pct, 1)} %",
    )
    _kpi(cols[3], "Projets de décision", str(data["project_count"]), "comparateur disponible", tone="ambre")

    qual = st.columns(3)
    _kpi(
        qual[0],
        "Dépenses à vérifier",
        str(expense_summary.unverified_count),
        f"part vérifiée : {fmt_number(expense_summary.verified_share_pct, 1)} %",
    )
    _kpi(
        qual[1],
        "Lignes sans facteur d'émission",
        str(expense_summary.without_factor_count),
        f"{fmt_money(expense_summary.without_factor_amount)} non estimés",
        tone="nuit",
    )
    scope_parts = [
        f"Scope {scope} : {fmt_tco2e(emission_summary.by_scope[scope] / 1000)}"
        for scope in ("1", "2", "3")
        if scope in emission_summary.by_scope
    ]
    _kpi(qual[2], "Répartition par scope", " · ".join(scope_parts) if scope_parts else "—", "", tone="ambre")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("**Dépenses par catégorie (HT)**")
        if data["spend_rows"]:
            chart = pd.DataFrame(
                {
                    "Catégorie": [row["label"] for row in data["spend_rows"]],
                    "DH": [float(row["ht"]) for row in data["spend_rows"]],
                }
            ).set_index("Catégorie")
            st.bar_chart(chart)
        else:
            st.info("Aucune dépense sur la période.")
    with right:
        st.markdown("**Émissions par catégorie (kg CO₂e)**")
        if data["emission_rows"]:
            chart = pd.DataFrame(
                {
                    "Catégorie": [row["label"] for row in data["emission_rows"]],
                    "kg CO₂e": [float(row["kg"]) for row in data["emission_rows"]],
                }
            ).set_index("Catégorie")
            st.bar_chart(chart)
        else:
            st.info("Aucun enregistrement carbone sur la période.")

    st.markdown("**Derniers enregistrements**")
    st.dataframe(pd.DataFrame(data["recent"]))


def page_expenses(ctx: Espace) -> None:
    st.title("Dépenses")
    st.caption("Montants en dirhams (DH). Chaque ligne est enregistrée dans votre espace et visible de votre entreprise uniquement.")

    frame = _load_expenses(ctx.org_id)
    with st.expander("＋ Enregistrer une nouvelle dépense", expanded=frame.empty):
        row1 = st.columns([1, 1, 1])
        with row1[0]:
            exp_date = st.date_input("Date de la dépense *", value=date.today(), key="exp_date")
        with row1[1]:
            exp_category = st.selectbox(
                "Catégorie *",
                list(EXPENSE_CATEGORIES.keys()),
                format_func=lambda code: EXPENSE_CATEGORIES[code],
                key="exp_category",
            )
        with row1[2]:
            exp_status = st.selectbox(
                "Statut de vérification",
                list(VERIFICATION_STATUSES.keys()),
                format_func=lambda code: VERIFICATION_STATUSES[code],
                key="exp_status",
            )
        row2 = st.columns([1, 1])
        with row2[0]:
            exp_supplier = st.text_input("Fournisseur", key="exp_supplier", placeholder="Ex. Marjane Pro")
        with row2[1]:
            exp_description = st.text_input("Description", key="exp_description", placeholder="Ex. Facture d'électricité mars")
        row3 = st.columns(3)
        with row3[0]:
            exp_ht = st.text_input("Montant HT (DH)", key="exp_ht", placeholder="Ex. 12 500,00")
        with row3[1]:
            exp_vat = st.text_input("TVA (DH)", key="exp_vat", placeholder="Ex. 2 500,00")
        with row3[2]:
            exp_ttc = st.text_input("Montant TTC (DH)", key="exp_ttc", placeholder="Laisser vide pour calculer")
        st.caption(
            "Indiquez au moins le montant HT ou TTC : l'autre montant est complété à partir de la TVA. "
            "Aucun TTC n'est inventé sans base."
        )
        if st.button("Enregistrer la dépense", key="exp_save", type="primary"):
            errors, amounts = _parse_montants(exp_ht, exp_vat, exp_ttc)
            if errors:
                for message in errors:
                    st.error(message)
            else:
                with session_scope() as db:
                    db.add(
                        Expense(
                            organization_id=ctx.org_id,
                            expense_date=exp_date,
                            category=exp_category,
                            supplier=(exp_supplier or "").strip(),
                            description=(exp_description or "").strip(),
                            amount_ht=amounts["ht"],
                            vat_amount=amounts["vat"],
                            amount_ttc=amounts["ttc"],
                            verification_status=exp_status,
                            created_by_id=ctx.user_id,
                        )
                    )
                    audit.log(
                        db,
                        action="expense_created",
                        organization_id=ctx.org_id,
                        user_id=ctx.user_id,
                        details={"montant_ttc": str(amounts["ttc"])},
                    )
                _flash("success", "Dépense enregistrée.")
                st.rerun()

    if frame.empty:
        st.info(
            "Aucune dépense enregistrée pour le moment. Utilisez le formulaire ci-dessus, "
            "ou chargez le jeu de démonstration depuis les Paramètres."
        )
        return

    period_label = st.radio(
        "Période",
        ["Année en cours", "Tout l'historique"],
        horizontal=True,
        key="dep_period",
    )
    resolved = resolve_period("annee" if period_label.startswith("Année") else "tout", today=date.today())
    subset = frame[(frame["_date"] >= resolved.start) & (frame["_date"] <= resolved.end)]

    filter_cols = st.columns([2, 2, 3])
    categories = sorted(subset["Catégorie"].unique().tolist())
    chosen_categories = filter_cols[0].multiselect("Catégorie", categories)
    chosen_status = filter_cols[1].selectbox("Statut", ["Tous"] + list(VERIFICATION_STATUSES.values()))
    search = filter_cols[2].text_input("Recherche (fournisseur, description)")

    if chosen_categories:
        subset = subset[subset["Catégorie"].isin(chosen_categories)]
    if chosen_status != "Tous":
        subset = subset[subset["Statut"] == chosen_status]
    if search.strip():
        needle = search.strip().lower()
        mask = subset["Fournisseur"].str.lower().str.contains(needle, regex=False) | subset[
            "Description"
        ].str.lower().str.contains(needle, regex=False)
        subset = subset[mask]

    totals = st.columns(2)
    _kpi(totals[0], "Lignes affichées", str(len(subset)), f"sur {len(frame)} au total")
    _kpi(totals[1], "Total HT (sélection)", fmt_money(subset["_ht"].sum() if len(subset) else ZERO), "", tone="nuit")

    st.dataframe(
        subset[
            [
                "Date",
                "Fournisseur",
                "Catégorie",
                "Description",
                "Montant HT",
                "TVA",
                "Montant TTC",
                "Statut",
            ]
        ]
    )

    with st.expander("Supprimer une dépense"):
        options = {
            f"{row['Date']} — {row['Fournisseur']} — {row['Montant TTC']}": int(row["_id"])
            for _, row in frame.iterrows()
        }
        choice = st.selectbox("Dépense à supprimer", list(options.keys()), key="exp_delete_choice")
        st.caption("Suppression définitive, journalisée dans le journal d'audit.")
        if st.button("Supprimer", key="exp_delete_confirm"):
            with session_scope() as db:
                row = db.get(Expense, options[choice])
                if row is not None and row.organization_id == ctx.org_id:
                    db.delete(row)
                    audit.log(
                        db,
                        action="expense_deleted",
                        organization_id=ctx.org_id,
                        user_id=ctx.user_id,
                        details={"expense_id": options[choice]},
                    )
            _flash("success", "Dépense supprimée.")
            st.rerun()


def page_carbon(ctx: Espace) -> None:
    st.title("Comptabilité carbone")
    st.caption(
        "Émissions = quantité d'activité × facteur documenté. Le statut (mesuré / calculé / estimé) "
        "suit la méthode du facteur : aucune donnée absente n'est remplacée par une estimation silencieuse."
    )

    factors = _load_factors(ctx.org_id)
    data = _load_carbon(ctx.org_id)
    if factors:
        with st.expander("＋ Enregistrer une donnée carbone", expanded=(data["count"] == 0)):
            factor_labels = [
                f"{factor['code']} — {factor['label']} "
                f"({fmt_number(factor['kgco2e_per_unit'], 4)} kg CO₂e / {factor['unit']})"
                for factor in factors
            ]
            row1 = st.columns([1, 2])
            with row1[0]:
                carb_category = st.selectbox(
                    "Poste carbone *",
                    list(CARBON_CATEGORIES.keys()),
                    format_func=lambda code: CARBON_CATEGORIES[code],
                    key="carb_category",
                )
            with row1[1]:
                chosen_factor = st.selectbox("Facteur d'émission documenté *", factor_labels, key="carb_factor")
            factor = factors[factor_labels.index(chosen_factor)]
            row2 = st.columns([1, 1, 1])
            with row2[0]:
                carb_start = st.date_input(
                    "Début de période *", value=date.today().replace(day=1), key="carb_start"
                )
            with row2[1]:
                carb_end = st.date_input("Fin de période *", value=date.today(), key="carb_end")
            with row2[2]:
                carb_quantity = st.number_input(
                    f"Quantité d'activité * ({factor['unit']})",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    key="carb_quantity",
                )
            preview_kg = compute_emissions_kg(Decimal(str(carb_quantity)), factor["kgco2e_per_unit"])
            st.caption(
                f"Émissions calculées : {fmt_kg(preview_kg)} — méthode : "
                f"{EMISSION_METHODS.get(factor['method'], factor['method'])} · "
                f"statut : {CARBON_STATUSES.get(status_from_method(factor['method']), status_from_method(factor['method']))} · "
                f"source : {factor['source_name'] or '—'}"
            )
            carb_notes = st.text_input("Note de contexte (optionnel)", key="carb_notes")
            if st.button("Enregistrer la donnée carbone", key="carb_save", type="primary"):
                errors = []
                if carb_quantity <= 0:
                    errors.append("La quantité d'activité doit être supérieure à zéro.")
                if carb_end < carb_start:
                    errors.append("La fin de période doit être postérieure au début.")
                if errors:
                    for message in errors:
                        st.error(message)
                else:
                    quantity = Decimal(str(carb_quantity))
                    kg = compute_emissions_kg(quantity, factor["kgco2e_per_unit"])
                    with session_scope() as db:
                        db.add(
                            CarbonRecord(
                                organization_id=ctx.org_id,
                                category=carb_category,
                                period_start=carb_start,
                                period_end=carb_end,
                                activity_quantity=quantity,
                                activity_unit=factor["unit"],
                                emission_factor_id=factor["id"],
                                method=factor["method"],
                                kgco2e=kg,
                                status=status_from_method(factor["method"]),
                                confidence=factor["confidence"],
                                notes=(carb_notes or "").strip(),
                            )
                        )
                        audit.log(
                            db,
                            action="carbon_record_created",
                            organization_id=ctx.org_id,
                            user_id=ctx.user_id,
                            details={"facteur": factor["code"], "kgco2e": str(kg)},
                        )
                    _flash("success", "Donnée carbone enregistrée.")
                    st.rerun()
    else:
        st.warning("Aucun facteur d'émission disponible : lancez l'initialisation du catalogue.")

    summary = data["summary"]
    if data["count"] == 0:
        st.info(
            "Aucune donnée carbone pour le moment. Utilisez le formulaire ci-dessus — chaque enregistrement "
            "s'appuie sur un facteur documenté (source, unité, périmètre)."
        )
        return

    cols = st.columns(4)
    _kpi(cols[0], "Émissions totales", fmt_tco2e(summary.total_t), f"{data['count']} enregistrement(s)")
    _kpi(cols[1], "Mesuré", fmt_tco2e(summary.measured_kg / 1000), f"{summary.measured_count} enregistrement(s)", tone="nuit")
    _kpi(cols[2], "Calculé (facteurs documentés)", fmt_tco2e(summary.calculated_kg / 1000), "", tone="ambre")
    _kpi(
        cols[3],
        "Estimé",
        fmt_tco2e(summary.estimated_kg / 1000),
        f"{fmt_number(summary.estimated_share_pct, 1)} % du total",
        tone="rouge",
    )

    scope_cols = st.columns(3)
    for index, scope in enumerate(("1", "2", "3")):
        total_kg = data["by_scope"].get(scope, ZERO) / 1000
        _kpi(scope_cols[index], SCOPES[scope], fmt_tco2e(total_kg))

    st.divider()
    st.markdown("**Émissions par catégorie (kg CO₂e)**")
    if data["category_rows"]:
        chart = pd.DataFrame(
            {
                "Catégorie": [row["label"] for row in data["category_rows"]],
                "kg CO₂e": [float(row["kg"]) for row in data["category_rows"]],
            }
        ).set_index("Catégorie")
        st.bar_chart(chart)
    else:
        st.info("Aucun enregistrement.")

    st.markdown("**Registre des activités**")
    st.dataframe(pd.DataFrame(data["rows"]))
    st.caption(
        "Les facteurs indicatifs doivent être remplacés par vos valeurs documentées avant tout usage "
        "contractuel ou réglementaire."
    )


def _project_form(ctx: Espace) -> None:
    st.caption(
        "Deux options à comparer sur un horizon commun. Laissez les émissions vides si elles sont inconnues : "
        "l'analyse les signalera comme « non renseignées »."
    )
    proj_title = st.text_input(
        "Intitulé du projet *", key="proj_title", placeholder="Ex. Rénovation de la ligne de conditionnement"
    )
    row = st.columns(3)
    with row[0]:
        proj_horizon = st.number_input("Horizon (années)", min_value=1, max_value=30, value=5, key="proj_horizon")
    with row[1]:
        proj_priority = priority_selector("proj_priority")
    with row[2]:
        proj_carbon_price = st.number_input(
            "Prix interne du carbone (DH / t — 0 = non appliqué)",
            min_value=0.0,
            max_value=2000.0,
            value=0.0,
            step=50.0,
            key="proj_carbon_price",
        )

    left, right = st.columns(2)
    with left:
        st.markdown("**Option A**")
        a_name = st.text_input("Nom (A) *", key="proj_a_name", placeholder="Ex. Réparer la machine existante")
        a_purchase = st.number_input("Acquisition (DH)", min_value=0.0, value=0.0, step=1000.0, key="proj_a_purchase")
        a_opex = st.number_input("Fonctionnement annuel (DH)", min_value=0.0, value=0.0, step=1000.0, key="proj_a_opex")
        a_maintenance = st.number_input("Maintenance annuelle (DH)", min_value=0.0, value=0.0, step=500.0, key="proj_a_maintenance")
        a_savings = st.number_input("Économies annuelles déclarées (DH)", min_value=0.0, value=0.0, step=500.0, key="proj_a_savings")
        a_emissions = st.number_input(
            "Émissions annuelles (kg CO₂e — vide si inconnu)",
            min_value=0.0,
            value=None,
            step=100.0,
            key="proj_a_emissions",
        )
    with right:
        st.markdown("**Option B**")
        b_name = st.text_input("Nom (B) *", key="proj_b_name", placeholder="Ex. Remplacer par un modèle économe")
        b_purchase = st.number_input("Acquisition (DH)", min_value=0.0, value=0.0, step=1000.0, key="proj_b_purchase")
        b_opex = st.number_input("Fonctionnement annuel (DH)", min_value=0.0, value=0.0, step=1000.0, key="proj_b_opex")
        b_maintenance = st.number_input("Maintenance annuelle (DH)", min_value=0.0, value=0.0, step=500.0, key="proj_b_maintenance")
        b_savings = st.number_input("Économies annuelles déclarées (DH)", min_value=0.0, value=0.0, step=500.0, key="proj_b_savings")
        b_emissions = st.number_input(
            "Émissions annuelles (kg CO₂e — vide si inconnu)",
            min_value=0.0,
            value=None,
            step=100.0,
            key="proj_b_emissions",
        )

    if st.button("Enregistrer le projet", key="proj_save", type="primary"):
        errors = []
        title = (proj_title or "").strip()
        if not title:
            errors.append("Indiquez l'intitulé du projet.")
        if (a_purchase + a_opex + a_maintenance) <= 0:
            errors.append("Renseignez au moins un coût pour l'option A (acquisition, fonctionnement ou maintenance).")
        if (b_purchase + b_opex + b_maintenance) <= 0:
            errors.append("Renseignez au moins un coût pour l'option B (acquisition, fonctionnement ou maintenance).")
        if errors:
            for message in errors:
                st.error(message)
            return
        with session_scope() as db:
            project = DecisionProject(
                organization_id=ctx.org_id,
                title=title,
                horizon_years=int(proj_horizon),
                priority=proj_priority,
                internal_carbon_price=Decimal(str(proj_carbon_price)),
                status="enregistree",
                created_by_id=ctx.user_id,
            )
            db.add(project)
            db.flush()
            options = [
                ("A", a_name, a_purchase, a_opex, a_maintenance, a_savings, a_emissions),
                ("B", b_name, b_purchase, b_opex, b_maintenance, b_savings, b_emissions),
            ]
            for order, (letter, name, purchase, opex, maintenance, savings, emissions) in enumerate(options):
                db.add(
                    DecisionOption(
                        project_id=project.id,
                        name=(name or "").strip() or f"Option {letter}",
                        purchase_cost=Decimal(str(purchase)),
                        transport_cost=ZERO,
                        annual_opex=Decimal(str(opex)),
                        annual_maintenance=Decimal(str(maintenance)),
                        annual_savings=Decimal(str(savings)),
                        annual_emissions_kg=(Decimal(str(emissions)) if emissions is not None else None),
                        confidence="moyenne",
                        sort_order=order,
                    )
                )
            audit.log(
                db,
                action="project_created",
                organization_id=ctx.org_id,
                user_id=ctx.user_id,
                details={"titre": title, "via": "streamlit"},
            )
        _flash(
            "success",
            f"Projet « {title} » enregistré — retrouvez l'analyse complète dans l'onglet « Mes projets ».",
        )
        st.rerun()


def _calculator() -> None:
    st.caption(
        "Comparez librement deux options (aucune écriture en base). Les valeurs par défaut reproduisent "
        "l'exemple du cahier des charges : 200 000 DH contre 180 000 DH sur 5 ans, 25 t CO₂e évitées, "
        "−800 DH par tonne évitée (gain double)."
    )
    horizon = st.slider("Horizon de comparaison (années)", 1, 30, 5, key="calc_horizon")
    carbon_price = st.number_input(
        "Prix interne du carbone (DH / t CO₂e — 0 = non appliqué)",
        min_value=0.0,
        max_value=2000.0,
        value=0.0,
        step=50.0,
        key="calc_carbon_price",
    )
    priority = priority_selector("calc_priority")

    column_a, column_b = st.columns(2)
    with column_a:
        st.markdown("**Option A**")
        name_a = st.text_input("Nom (A)", "Option A — rénover la presse", key="calc_a_name")
        purchase_a = st.number_input("Acquisition (DH) (A)", min_value=0.0, value=80000.0, step=1000.0, key="calc_a_purchase")
        transport_a = st.number_input("Transport (DH) (A)", min_value=0.0, value=0.0, step=500.0, key="calc_a_transport")
        opex_a = st.number_input("Fonctionnement annuel (DH) (A)", min_value=0.0, value=24000.0, step=1000.0, key="calc_a_opex")
        maintenance_a = st.number_input("Maintenance annuelle (DH) (A)", min_value=0.0, value=0.0, step=500.0, key="calc_a_maintenance")
        savings_a = st.number_input("Économies annuelles déclarées (DH) (A)", min_value=0.0, value=0.0, step=500.0, key="calc_a_savings")
        emissions_a = st.number_input("Émissions annuelles (kg CO₂e) (A)", min_value=0.0, value=12000.0, step=100.0, key="calc_a_emissions")
    with column_b:
        st.markdown("**Option B**")
        name_b = st.text_input("Nom (B)", "Option B — remplacer la presse", key="calc_b_name")
        purchase_b = st.number_input("Acquisition (DH) (B)", min_value=0.0, value=95000.0, step=1000.0, key="calc_b_purchase")
        transport_b = st.number_input("Transport (DH) (B)", min_value=0.0, value=0.0, step=500.0, key="calc_b_transport")
        opex_b = st.number_input("Fonctionnement annuel (DH) (B)", min_value=0.0, value=17000.0, step=1000.0, key="calc_b_opex")
        maintenance_b = st.number_input("Maintenance annuelle (DH) (B)", min_value=0.0, value=0.0, step=500.0, key="calc_b_maintenance")
        savings_b = st.number_input("Économies annuelles déclarées (DH) (B)", min_value=0.0, value=0.0, step=500.0, key="calc_b_savings")
        emissions_b = st.number_input("Émissions annuelles (kg CO₂e) (B)", min_value=0.0, value=7000.0, step=100.0, key="calc_b_emissions")

    options = [
        OptionInput.from_dict(
            {
                "name": name_a or "Option A",
                "purchase_cost": str(purchase_a),
                "transport_cost": str(transport_a),
                "annual_opex": str(opex_a),
                "annual_maintenance": str(maintenance_a),
                "annual_savings": str(savings_a),
                "annual_emissions_kg": str(emissions_a),
                "confidence": "haute",
            },
            key="a",
        ),
        OptionInput.from_dict(
            {
                "name": name_b or "Option B",
                "purchase_cost": str(purchase_b),
                "transport_cost": str(transport_b),
                "annual_opex": str(opex_b),
                "annual_maintenance": str(maintenance_b),
                "annual_savings": str(savings_b),
                "annual_emissions_kg": str(emissions_b),
                "confidence": "haute",
            },
            key="b",
        ),
    ]
    try:
        analysis = analyze(
            options,
            horizon,
            priority=priority,
            carbon_price=str(carbon_price),
            with_scenarios=False,
            with_sensitivity=False,
            with_charts=True,
        )
    except ValidationError as error:
        st.error(str(error))
    else:
        render_analysis(analysis)


def page_comparator(ctx: Espace) -> None:
    st.title("Comparateur de décisions")
    st.caption(
        "Le cœur du produit : coût complet et émissions cumulées sur un horizon commun, frontière de "
        "compromis et arbitrage expliqué — sans jamais inventer de chiffre."
    )
    projects = _load_projects(ctx.org_id)
    tab_list, tab_new, tab_calc = st.tabs(["Mes projets", "Nouveau projet", "Calculateur libre"])

    with tab_list:
        if not projects:
            st.info(
                "Aucun projet de décision pour le moment. Créez-en un dans l'onglet « Nouveau projet », "
                "ou chargez le jeu de démonstration depuis les Paramètres."
            )
        else:
            titles = [
                f"{project['title']} — {project['option_count']} options, horizon {project['horizon']} ans"
                + (" · démonstration" if project["is_demo"] else "")
                for project in projects
            ]
            chosen = st.selectbox("Projet", titles, index=0, key="cmp_project")
            project = projects[titles.index(chosen)]
            priority = priority_selector("cmp_priority", default=project["priority"] or "equilibre")
            try:
                analysis = _analyze_project(project["id"], ctx.org_id, priority, False)
            except ValidationError as error:
                st.error(str(error))
            else:
                render_analysis(analysis)

    with tab_new:
        _project_form(ctx)

    with tab_calc:
        _calculator()


def page_simulations(ctx: Espace) -> None:
    st.title("Simulations")
    st.caption(
        "Scénarios prédéfinis (base, optimiste, défavorable) sur vos projets : mêmes moteurs que le "
        "comparateur, aucune donnée modifiée en base."
    )
    projects = _load_projects(ctx.org_id)
    if not projects:
        st.info(
            "Aucun projet à simuler pour le moment. Créez un projet dans le comparateur, ou chargez le "
            "jeu de démonstration depuis les Paramètres."
        )
        return
    titles = [f"{project['title']} — horizon {project['horizon']} ans" for project in projects]
    chosen = st.selectbox("Projet", titles, key="sim_project")
    project = projects[titles.index(chosen)]
    try:
        analysis = _analyze_project(project["id"], ctx.org_id, "equilibre", True)
    except ValidationError as error:
        st.error(str(error))
        return

    for outcome in analysis.scenarios:
        is_base = outcome.kind == "base"
        with st.expander(outcome.label, expanded=is_base):
            st.markdown(outcome.description)
            rows = [
                {
                    "Option": result.name,
                    "Coût total": fmt_money(result.total_cost),
                    "Δ vs base": _delta_money(outcome.cost_deltas.get(result.key), is_base),
                    "Émissions cumulées": fmt_tco2e(result.total_emissions_t)
                    if result.total_emissions_t is not None
                    else "non renseignées",
                    "Δ émissions": _delta_t(outcome.emissions_deltas.get(result.key), is_base),
                }
                for result in outcome.comparison.results
            ]
            st.dataframe(pd.DataFrame(rows))
            for line in outcome.summary_lines:
                st.markdown(f"- {line}")


def page_settings(ctx: Espace) -> None:
    st.title("Paramètres")
    counts = _counts(ctx.org_id)
    org = _org_row(ctx.org_id)
    col_left, col_right = st.columns(2)

    with col_left:
        with st.container(border=True):
            st.markdown("**Entreprise**")
            st.caption("Ces informations identifient votre organisation dans l'application.")
            org_name = st.text_input("Nom de l'entreprise *", value=org.get("name", ""), key="org_name")
            org_ice = st.text_input("ICE (Maroc)", value=org.get("ice", ""), key="org_ice")
            org_sector = st.text_input("Secteur d'activité", value=org.get("sector", ""), key="org_sector")
            size_options = COMPANY_SIZES
            current_size = org.get("company_size", "")
            org_size = st.selectbox(
                "Taille de l'entreprise",
                size_options,
                index=size_options.index(current_size) if current_size in size_options else 0,
                key="org_size",
            )
            org_carbon_price = st.number_input(
                "Prix interne du carbone (DH / t CO₂e — 0 = non appliqué)",
                min_value=0.0,
                max_value=2000.0,
                value=float(org.get("internal_carbon_price") or 0),
                step=50.0,
                key="org_carbon_price",
            )
            if st.button("Enregistrer", key="org_save", type="primary"):
                if not (org_name or "").strip():
                    st.error("Le nom de l'entreprise est requis.")
                else:
                    with session_scope() as db:
                        organization = db.get(Organization, ctx.org_id)
                        if organization is not None:
                            organization.name = org_name.strip()
                            organization.ice = (org_ice or "").strip()
                            organization.sector = (org_sector or "").strip()
                            organization.company_size = org_size
                            organization.internal_carbon_price = Decimal(str(org_carbon_price))
                            audit.log(
                                db,
                                action="organization_updated",
                                organization_id=organization.id,
                                user_id=ctx.user_id,
                                details={"via": "streamlit"},
                            )
                    _flash("success", "Informations de l'entreprise mises à jour.")
                    st.rerun()

        with st.container(border=True):
            st.markdown("**Compte**")
            st.caption(f"{ctx.user_name} — {ctx.user_email}")
            st.caption(f"Rôle : {MEMBER_ROLES.get(ctx.org_role, ctx.org_role)}")
            if st.button("Se déconnecter", key="settings_logout"):
                deconnexion()
                _flash("success", "Vous êtes déconnecté.")
                st.rerun()

    with col_right:
        with st.container(border=True):
            st.markdown("**Données**")
            st.caption(
                f"Actuellement : {counts['expenses']} dépenses, {counts['records']} données carbone, "
                f"{counts['projects']} projets de décision."
            )
            if ctx.demo_loaded:
                st.markdown(
                    '<span class="cl-badge cl-badge--demo">Jeu de démonstration chargé</span>',
                    unsafe_allow_html=True,
                )
                if st.button("Supprimer les données de démonstration", key="settings_delete_demo"):
                    _delete_demo(ctx)
                    st.rerun()
                st.caption("Seules les lignes marquées « démonstration » sont supprimées ; vos données restent intactes.")
            else:
                if st.button("Charger le jeu de démonstration", key="settings_load_demo"):
                    _load_demo(ctx)
                    st.rerun()
                st.caption(
                    "25 dépenses, 18 données carbone et 3 projets d'exemple — à titre pédagogique, "
                    "supprimables d'un clic. Vos données restent prioritaires."
                )

        with st.container(border=True):
            st.markdown("**Stockage des données**")
            if is_postgres():
                st.markdown("Base **PostgreSQL** — vos données sont conservées de façon permanente côté serveur.")
            else:
                st.markdown(
                    "Base **SQLite** servie localement. Sur Streamlit Community Cloud, le fichier peut être "
                    "réinitialisé lors d'un redéploiement : pour une sauvegarde permanente, définissez le secret "
                    "`CARBONLEDGER_DATABASE_URL` (PostgreSQL, par ex. Neon) — voir `DEPLOYMENT.md` § 4.4."
                )
            st.caption(
                "Isolation : chaque requête est filtrée par votre identifiant d'organisation ; "
                "aucune donnée d'une autre entreprise n'est accessible depuis votre espace."
            )

        with st.container(border=True):
            st.markdown("**À propos**")
            st.markdown(
                f"CarbonLedger AI — aide à la décision coûts & carbone pour PME marocaines. "
                f"Code source : [dépôt GitHub]({GITHUB_URL})."
            )
            st.caption(
                "Rigueur : facteurs d'émission indicatifs et documentés, à remplacer par vos valeurs avant "
                "tout usage contractuel."
            )


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
def _app_sidebar(ctx: Espace) -> str:
    _brand("Pilotage coûts &amp; carbone")
    page = st.sidebar.radio("Navigation", PAGES, key="nav", label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.markdown(
        f'<div class="cl-brand__name">{ctx.org_name}</div>'
        f'<div class="cl-brand__sub">{ctx.user_name} · {MEMBER_ROLES.get(ctx.org_role, ctx.org_role)}</div>',
        unsafe_allow_html=True,
    )
    if ctx.demo_loaded:
        st.sidebar.caption("Données de démonstration chargées")
    if st.sidebar.button("Se déconnecter", key="logout", use_container_width=True):
        deconnexion()
        _flash("success", "Vous êtes déconnecté.")
        st.rerun()
    st.sidebar.caption("Montants en MAD (DH) · émissions en kg CO₂e")
    return page


def _guest_sidebar() -> None:
    _brand("Décision coûts &amp; carbone<br/>pour PME marocaines")
    st.sidebar.caption("Créez votre compte pour accéder à votre espace — ou connectez-vous.")


def main() -> None:
    espace = espace_courant()
    _show_flash()
    if espace is None:
        _guest_sidebar()
        view = st.session_state.get("auth_view", "accueil")
        {"accueil": page_accueil, "inscription": page_inscription, "connexion": page_connexion}.get(
            view, page_accueil
        )()
        return
    page = _app_sidebar(espace)
    pages = {
        "Tableau de bord": page_dashboard,
        "Dépenses": page_expenses,
        "Comptabilité carbone": page_carbon,
        "Comparateur de décisions": page_comparator,
        "Simulations": page_simulations,
        "Paramètres": page_settings,
    }
    pages.get(page, page_dashboard)(espace)


main()
