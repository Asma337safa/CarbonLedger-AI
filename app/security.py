"""Sécurité : hachage des mots de passe, jetons de session et CSRF."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Paramètres scrypt (bibliothèque standard, aucun paquet natif requis).
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str) -> str:
    """Hache un mot de passe avec scrypt (sel aléatoire par utilisateur)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Vérifie un mot de passe en temps constant."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64d(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_b64d(digest_b64)),
        )
        return hmac.compare_digest(digest, _b64d(digest_b64))
    except Exception:
        return False


def password_problems(password: str, *, email: str = "") -> list[str]:
    """Vérifications minimales du mot de passe (messages en français)."""
    problems: list[str] = []
    if password is None or len(password) < 8:
        problems.append("Le mot de passe doit contenir au moins 8 caractères.")
    if password and password.lower() == password and password.upper() == password:
        problems.append("Le mot de passe doit contenir au moins une lettre.")
    if password and not any(char.isdigit() for char in password):
        problems.append("Le mot de passe doit contenir au moins un chiffre.")
    if email and password and email.lower() in password.lower():
        problems.append("Le mot de passe ne doit pas contenir l'adresse e-mail.")
    return problems


def new_token(nbytes: int = 32) -> str:
    """Jeton aléatoire (session, invitation, export)."""
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Empreinte SHA-256 d'un jeton (jamais stocké en clair)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def safe_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(str(a), str(b))
