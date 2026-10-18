"""Initialisation de la base de données CarbonLedger AI.

Usage :
    python scripts/init_db.py                 # crée les tables manquantes + catalogue de facteurs
    python scripts/init_db.py --reset --yes   # supprime toutes les tables puis recrée (destructif)
    python scripts/init_db.py --demo          # ajoute en plus une organisation de démonstration

Le script fonctionne avec SQLite (par défaut) comme avec PostgreSQL
(``CARBONLEDGER_DATABASE_URL``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402  (enregistre les mappings)
from app.config import settings  # noqa: E402
from app.db import DATABASE_URL, Base, engine  # noqa: E402
from app.services.factors_seed import seed_global_factors  # noqa: E402


def _table_counts() -> list[tuple[str, int]]:
    from sqlalchemy import func, select

    rows: list[tuple[str, int]] = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            count = connection.execute(select(func.count()).select_from(table)).scalar_one()
            rows.append((table.name, int(count)))
    return rows


def reset_database() -> None:
    """Supprime toutes les tables de l'application (données perdues)."""
    Base.metadata.drop_all(engine)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialise la base CarbonLedger AI.")
    parser.add_argument("--reset", action="store_true", help="supprime toutes les tables avant de les recréer")
    parser.add_argument("--yes", action="store_true", help="confirme la suppression (obligatoire avec --reset)")
    parser.add_argument("--demo", action="store_true", help="crée aussi une organisation de démonstration")
    parser.add_argument("--demo-email", default="demo@carbonledger.ma", help="e-mail du compte de démonstration")
    parser.add_argument("--demo-password", default="DemoCarbon2026", help="mot de passe du compte de démonstration")
    args = parser.parse_args()

    print(f"Base de données : {DATABASE_URL}")
    print(f"Dossier de données : {settings.data_dir}")

    if args.reset:
        if not args.yes:
            print("Refusé : --reset supprime toutes les données. Ajoutez --yes pour confirmer.")
            return 2
        reset_database()
        print("Tables supprimées.")

    Base.metadata.create_all(engine)
    created = inspect(engine).get_table_names()
    print(f"Tables présentes : {len(created)}")

    inserted = seed_global_factors()
    print(f"Catalogue de facteurs d'émission : {inserted} entrée(s) ajoutée(s).")

    if args.demo:
        from app.services import demo_data
        from app.db import session_scope
        from app.models import Organization, OrganizationMember, User
        from app.security import hash_password

        with session_scope() as db:
            user = db.query(User).filter(User.email == args.demo_email).first()
            if user is None:
                user = User(
                    email=args.demo_email,
                    password_hash=hash_password(args.demo_password),
                    full_name="Compte de démonstration",
                )
                db.add(user)
                db.flush()
            organization = (
                db.query(Organization)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .filter(OrganizationMember.user_id == user.id)
                .first()
            )
            if organization is None:
                organization = Organization(
                    name="PME de démonstration",
                    ice="000000000000000",
                    sector="agroalimentaire",
                    company_size="45",
                    onboarding_done=True,
                )
                db.add(organization)
                db.flush()
                db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="proprietaire"))
                db.flush()
            counts = demo_data.load_demo_data(db, organization, user.id)
            print(
                "Données de démonstration : "
                f"{counts['expenses']} dépenses, {counts['carbon_records']} enregistrements carbone, "
                f"{counts['projects']} projets."
            )
            print(f"Connexion : {args.demo_email} / {args.demo_password}")

    print("\nContenu des tables :")
    for name, count in _table_counts():
        print(f"  - {name:<22} {count:>6} ligne(s)")
    print("\nBase prête.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
