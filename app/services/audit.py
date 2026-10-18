"""Journal d'audit des opérations sensibles."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session as OrmSession

from ..models import AuditLog


def log(
    db: OrmSession,
    *,
    action: str,
    organization_id: int | None = None,
    user_id: int | None = None,
    entity_type: str = "",
    entity_id: str | int | None = "",
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> None:
    """Enregistre une opération (connexion, import, suppression, rapport…)."""
    entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        details=details or {},
        ip=(request.client.host if request and request.client else "")[:64],
    )
    db.add(entry)
    if commit:
        db.commit()
