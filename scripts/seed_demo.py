"""Création d'un compte de démonstration complet (organisation + données).

Usage :
    python scripts/seed_demo.py --email salma@atlas-agro.ma --password "MotDePasse!2026"
    python scripts/seed_demo.py --email demo@exemple.ma --password "Demo2026!" --company "Atlas Agro SARL"

Le script est idempotent : relancé avec le même e-mail, il recharge les données
de démonstration (les données de démonstration précédentes sont remplacées,
les données saisies par l'utilisateur sont conservées).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import DATABASE_URL, init_db, session_scope  # noqa: E402
from app.models import Organization, OrganizationMember, User  # noqa: E402
from app.security import hash_password, password_problems  # noqa: E402
from app.services import audit, demo_data  # noqa: E402
from app.services.factors_seed import seed_global_factors  # noqa: E402

SECTORS = ("agroalimentaire", "textile", "mecanique", "btp", "transport", "hotellerie", "services", "autre")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crée un compte de démonstration CarbonLedger AI.")
    parser.add_argument("--email", required=True, help="adresse e-mail du compte")
    parser.add_argument("--password", required=True, help="mot de passe (8 caractères minimum, un chiffre)")
    parser.add_argument("--name", default="Compte de démonstration", help="nom de l'utilisateur")
    parser.add_argument("--company", default="PME de démonstration", help="nom de l'organisation")
    parser.add_argument("--ice", default="000000000000000", help="ICE de l'entreprise (15 chiffres)")
    parser.add_argument("--sector", default="agroalimentaire", choices=SECTORS, help="secteur d'activité")
    parser.add_argument("--size", default="45", help="effectif de l'entreprise")
    args = parser.parse_args()

    problems = password_problems(args.password, email=args.email)
    if problems:
        for problem in problems:
            print(f"Mot de passe refusé : {problem}")
        return 2

    print(f"Base de données : {DATABASE_URL}")
    init_db()
    seed_global_factors()

    with session_scope() as db:
        user = db.query(User).filter(User.email == args.email.strip().lower()).first()
        if user is None:
            user = User(
                email=args.email.strip().lower(),
                password_hash=hash_password(args.password),
                full_name=args.name,
            )
            db.add(user)
            db.flush()
            print(f"Utilisateur créé : {user.email} (id {user.id})")
        else:
            user.password_hash = hash_password(args.password)
            print(f"Utilisateur existant mis à jour : {user.email} (id {user.id})")

        organization = (
            db.query(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .filter(OrganizationMember.user_id == user.id)
            .first()
        )
        if organization is None:
            organization = Organization(
                name=args.company,
                ice=args.ice,
                sector=args.sector,
                company_size=args.size,
                onboarding_done=True,
            )
            db.add(organization)
            db.flush()
            db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="proprietaire"))
            db.flush()
            print(f"Organisation créée : {organization.name} (id {organization.id})")

        counts = demo_data.load_demo_data(db, organization, user.id)
        audit.log(
            db,
            action="demo_data_seeded",
            organization_id=organization.id,
            user_id=user.id,
            entity_type="organization",
            entity_id=organization.id,
            details={key: str(value) for key, value in counts.items()},
        )
        print(
            "Données de démonstration chargées : "
            f"{counts['expenses']} dépenses, {counts['carbon_records']} enregistrements carbone, "
            f"{counts['projects']} projets de décision."
        )

    print("\nConnexion :")
    print(f"  e-mail       : {args.email}")
    print(f"  mot de passe : {args.password}")
    print("Ces identifiants sont des données de démonstration : ne les utilisez pas en production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
