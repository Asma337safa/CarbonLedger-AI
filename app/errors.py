"""Erreurs applicatives partagées."""

from __future__ import annotations


class AppError(Exception):
    """Erreur métier affichable à l'utilisateur."""

    def __init__(self, message: str, *, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}


class ValidationError(AppError):
    """Données invalides (formulaires, imports, API)."""


class NotFoundError(AppError):
    """Ressource inexistante ou hors du périmètre de l'organisation."""


class AccessDenied(AppError):
    """Action non autorisée pour le rôle de l'utilisateur."""


class UnitError(ValueError):
    """Unités incompatibles ou inconnues."""
