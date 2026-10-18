"""Modèle de données CarbonLedger AI.

Toutes les entités métier sont rattachées à une organisation ; l'isolation
des données entre entreprises est vérifiée côté serveur pour chaque requête
(voir ``app/deps.py`` et ``app/services/access.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


def utcnow() -> datetime:
    """Horodatage UTC naïf (portable SQLite/PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


MONEY = Numeric(14, 2)
MONEY_BIG = Numeric(16, 2)
QUANTITY = Numeric(18, 4)
EMISSIONS_KG = Numeric(18, 3)
FACTOR_VALUE = Numeric(18, 6)
YEARS = Numeric(5, 1)
PCT = Numeric(6, 2)


# ---------------------------------------------------------------------------
# Comptes, organisations et sécurité
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(160), nullable=False, default="")
    locale = Column(String(8), nullable=False, default="fr")
    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    last_login_at = Column(DateTime, nullable=True)

    memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    ice = Column(String(20), nullable=False, default="")  # Identifiant Commun de l'Entreprise (Maroc)
    sector = Column(String(80), nullable=False, default="")
    company_size = Column(String(40), nullable=False, default="")
    currency = Column(String(8), nullable=False, default="MAD")
    internal_carbon_price = Column(MONEY, nullable=False, default=0)  # DH / tCO2e (hypothèse interne)
    onboarding_done = Column(Boolean, nullable=False, default=False)
    demo_data_loaded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_member_org_user"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="membre")
    created_at = Column(DateTime, nullable=False, default=utcnow)

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="membre")
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String(64), primary_key=True)  # SHA-256 du jeton de session
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    csrf_token = Column(String(64), nullable=False)
    flash = Column(JSON, nullable=True)  # messages temporaires [(niveau, message)]
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    user = relationship("User")


# ---------------------------------------------------------------------------
# Dépenses et données carbone
# ---------------------------------------------------------------------------
class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_org_date", "organization_id", "expense_date"),
        Index("ix_expenses_org_category", "organization_id", "category"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    expense_date = Column(Date, nullable=False)
    category = Column(String(40), nullable=False, default="autres")
    supplier = Column(String(160), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    amount_ht = Column(MONEY_BIG, nullable=False, default=0)
    vat_amount = Column(MONEY_BIG, nullable=False, default=0)
    amount_ttc = Column(MONEY_BIG, nullable=False, default=0)
    quantity = Column(QUANTITY, nullable=True)
    unit = Column(String(24), nullable=True)
    emission_factor_id = Column(Integer, ForeignKey("emission_factors.id", ondelete="SET NULL"), nullable=True)
    carbon_source_note = Column(Text, nullable=False, default="")
    verification_status = Column(String(20), nullable=False, default="a_verifier")
    is_demo = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    emission_factor = relationship("EmissionFactor")
    carbon_records = relationship("CarbonRecord", back_populates="expense", cascade="all, delete-orphan")


class EmissionFactor(Base):
    """Facteur d'émission documenté : source, unité, périmètre, validité, version.

    ``organization_id`` NULL = facteur du catalogue global (lecture seule pour les
    organisations) ; sinon facteur personnalisé propre à l'organisation.
    """

    __tablename__ = "emission_factors"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_factor_org_code"),
        Index("ix_factors_unit", "unit"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    code = Column(String(60), nullable=False)
    label = Column(String(200), nullable=False)
    category = Column(String(40), nullable=False, default="autres")
    unit = Column(String(24), nullable=False)
    scope = Column(String(4), nullable=False, default="3")
    method = Column(String(20), nullable=False, default="calcule")
    kgco2e_per_unit = Column(FACTOR_VALUE, nullable=False)
    source_name = Column(String(200), nullable=False, default="")
    source_url = Column(String(400), nullable=False, default="")
    source_version = Column(String(60), nullable=False, default="")
    geography = Column(String(16), nullable=False, default="")
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    confidence = Column(String(12), nullable=False, default="moyenne")
    calculation_note = Column(Text, nullable=False, default="")
    is_demo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CarbonRecord(Base):
    """Enregistrement du registre carbone : quantité d'activité x facteur d'émission."""

    __tablename__ = "carbon_records"
    __table_args__ = (Index("ix_carbon_org_period", "organization_id", "period_start"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=True, index=True)
    option_id = Column(Integer, ForeignKey("decision_options.id", ondelete="CASCADE"), nullable=True, index=True)
    category = Column(String(40), nullable=False, default="autres")
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    activity_quantity = Column(QUANTITY, nullable=False)
    activity_unit = Column(String(24), nullable=False)
    emission_factor_id = Column(Integer, ForeignKey("emission_factors.id", ondelete="SET NULL"), nullable=True)
    method = Column(String(20), nullable=False, default="calcule")
    kgco2e = Column(EMISSIONS_KG, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="calcule")  # mesure | calcule | estime
    confidence = Column(String(12), nullable=False, default="moyenne")
    notes = Column(Text, nullable=False, default="")
    is_demo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    expense = relationship("Expense", back_populates="carbon_records")
    emission_factor = relationship("EmissionFactor")


# ---------------------------------------------------------------------------
# Décisions, scénarios, recommandations
# ---------------------------------------------------------------------------
class DecisionProject(Base):
    __tablename__ = "decision_projects"
    __table_args__ = (Index("ix_projects_org_status", "organization_id", "status"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    category = Column(String(40), nullable=False, default="equipements")
    horizon_years = Column(Integer, nullable=False, default=5)  # période commune de comparaison
    discount_rate_pct = Column(PCT, nullable=False, default=0)  # 0 = hors actualisation (hypothèse affichée)
    priority = Column(String(20), nullable=False, default="equilibre")
    internal_carbon_price = Column(MONEY, nullable=False, default=0)  # DH / tCO2e
    status = Column(String(16), nullable=False, default="brouillon")
    chosen_option_id = Column(
        Integer,
        # use_alter : évite la dépendance circulaire decision_projects <-> decision_options
        # lors de la création des tables (SQLAlchemy émet alors un ALTER TABLE).
        ForeignKey("decision_options.id", ondelete="SET NULL", use_alter=True, name="fk_projects_chosen_option"),
        nullable=True,
    )
    is_demo = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    options = relationship(
        "DecisionOption",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="DecisionOption.sort_order",
        foreign_keys="DecisionOption.project_id",
    )
    scenarios = relationship("Scenario", back_populates="project", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="project", cascade="all, delete-orphan")


class DecisionOption(Base):
    __tablename__ = "decision_options"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("decision_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    supplier = Column(String(200), nullable=False, default="")
    purchase_cost = Column(MONEY_BIG, nullable=False, default=0)
    transport_cost = Column(MONEY_BIG, nullable=False, default=0)
    annual_opex = Column(MONEY_BIG, nullable=False, default=0)
    annual_energy_share_pct = Column(PCT, nullable=True)  # part énergie dans les coûts de fonctionnement
    annual_maintenance = Column(MONEY_BIG, nullable=False, default=0)
    annual_savings = Column(MONEY_BIG, nullable=False, default=0)
    useful_life_years = Column(YEARS, nullable=True)
    annual_emissions_kg = Column(EMISSIONS_KG, nullable=True)
    emissions_basis = Column(String(16), nullable=True)  # mesure | calcule | estime
    emission_factor_id = Column(Integer, ForeignKey("emission_factors.id", ondelete="SET NULL"), nullable=True)
    emissions_source_note = Column(Text, nullable=False, default="")
    confidence = Column(String(12), nullable=False, default="moyenne")
    notes = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)

    project = relationship("DecisionProject", back_populates="options", foreign_keys=[project_id])
    emission_factor = relationship("EmissionFactor")


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("decision_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    kind = Column(String(16), nullable=False, default="personnalise")
    parameters = Column(JSON, nullable=False, default=dict)
    notes = Column(Text, nullable=False, default="")
    is_demo = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    project = relationship("DecisionProject", back_populates="scenarios")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("decision_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(String(20), nullable=False)
    carbon_price = Column(MONEY, nullable=False, default=0)
    summary = Column(Text, nullable=False, default="")
    details = Column(JSON, nullable=False, default=dict)  # matrice détaillée + chiffres clés
    chosen_option_id = Column(Integer, ForeignKey("decision_options.id", ondelete="SET NULL"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    project = relationship("DecisionProject", back_populates="recommendations")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("decision_projects.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(12), nullable=False, default="pdf")  # pdf | csv | xlsx
    scope = Column(String(20), nullable=False, default="periode")  # projet | periode | global
    title = Column(String(200), nullable=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    file_path = Column(String(500), nullable=False, default="")
    payload = Column(JSON, nullable=True)  # instantané des chiffres clés du rapport
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class ImportBatch(Base):
    """Suivi d'une importation de dépenses (fichier CSV/Excel)."""

    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default="en_attente")
    mapping = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(40), nullable=False, default="")
    entity_id = Column(String(40), nullable=False, default="")
    details = Column(JSON, nullable=True)
    ip = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)
