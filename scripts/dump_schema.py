"""Export du schéma SQL réel (fichier ``docs/schema.sql``).

Usage :
    python scripts/dump_schema.py            # écrit docs/schema.sql
    python scripts/dump_schema.py --stdout   # affiche le schéma

Le fichier produit sert de référence documentaire : il est généré depuis les
modèles SQLAlchemy, donc toujours cohérent avec le code. Les migrations
Alembic (dossier ``alembic/``) restent la source de vérité pour les évolutions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.dialects import postgresql, sqlite  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app import models  # noqa: E402  (enregistre les mappings)
from app.db import DATABASE_URL, Base  # noqa: E402

HEADER = """-- CarbonLedger AI — schéma de base de données
-- Fichier généré par `python scripts/dump_schema.py` : ne pas modifier à la main.
-- Dialecte de référence : {dialect}
-- URL utilisée lors de la génération : {url}
--
-- Les migrations Alembic (alembic/versions/*.py) restent la référence pour les
-- évolutions de schéma ; ce fichier documente l'état courant des tables.
"""


def render(dialect_name: str) -> str:
    dialect = postgresql.dialect() if dialect_name == "postgresql" else sqlite.dialect()
    lines = [HEADER.format(dialect=dialect_name, url=DATABASE_URL), ""]
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        lines.append("")
        for index in table.indexes:
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        if table.indexes:
            lines.append("")
    lines.append("-- Contraintes d'unicité et clés étrangères : voir les définitions de tables ci-dessus.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporte le schéma SQL dans docs/schema.sql.")
    parser.add_argument("--stdout", action="store_true", help="affiche le schéma au lieu d'écrire le fichier")
    parser.add_argument(
        "--dialect",
        default="sqlite",
        choices=("sqlite", "postgresql"),
        help="dialecte SQL cible (sqlite par défaut, postgresql pour la production)",
    )
    args = parser.parse_args()

    sql = render(args.dialect)
    if args.stdout:
        print(sql)
        return 0

    target = ROOT / "docs" / "schema.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sql, encoding="utf-8")
    tables = len(Base.metadata.sorted_tables)
    print(f"{tables} table(s) écrites dans {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
