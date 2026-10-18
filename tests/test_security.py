"""Tests de sécurité : mots de passe, sessions, protection CSRF et rôles."""

from __future__ import annotations

from app.security import hash_password, new_token, password_problems, safe_equal, token_hash, verify_password
from tests import helpers


# ---------------------------------------------------------------------------
# Mots de passe et jetons
# ---------------------------------------------------------------------------
def test_mot_de_passe_hache_et_verifie():
    stocke = hash_password("MotDePasse!2026")
    assert stocke != "MotDePasse!2026"
    assert "MotDePasse" not in stocke
    assert verify_password("MotDePasse!2026", stocke) is True
    assert verify_password("mauvais-mot-de-passe", stocke) is False
    assert verify_password("", stocke) is False


def test_hachage_avec_sel_unique():
    premier = hash_password("MotDePasse!2026")
    second = hash_password("MotDePasse!2026")
    assert premier != second  # sel aléatoire : pas d'empreinte partagée
    assert verify_password("MotDePasse!2026", premier)
    assert verify_password("MotDePasse!2026", second)


def test_jetons_aleatoires_et_empreintes():
    premier, second = new_token(), new_token()
    assert premier != second
    assert len(token_hash(premier)) == 64
    assert token_hash(premier) == token_hash(premier)
    assert token_hash(premier) != token_hash(second)


def test_safe_equal():
    assert safe_equal("abc", "abc") is True
    assert safe_equal("abc", "abd") is False
    assert safe_equal(None, "abc") is False
    assert safe_equal("", "") is False


def test_regles_de_mot_de_passe():
    assert password_problems("MotDePasse!2026") == []
    assert any("8 caractères" in message for message in password_problems("court1"))
    assert any("chiffre" in message for message in password_problems("SansChiffre"))
    # Un mot de passe ne doit pas contenir l'adresse e-mail complète
    problemes = password_problems("salma@exemple.ma2026", email="salma@exemple.ma")
    assert any("e-mail" in message for message in problemes)


# ---------------------------------------------------------------------------
# Protection CSRF
# ---------------------------------------------------------------------------
def test_post_sans_jeton_refuse(client, company):
    response = client.post(
        "/expenses",
        data={"expense_date": "2026-03-04", "amount_ht": "1000", "category": "energie"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "Jeton de sécurité" in response.text


def test_post_avec_jeton_invalide_refuse(client, company):
    response = client.post(
        "/expenses",
        data={"csrf_token": "jeton-bidon", "expense_date": "2026-03-04", "amount_ht": "1000"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_api_sans_jeton_renvoie_du_json(client, company):
    response = client.post("/api/projects/compute", json={"options": []})
    assert response.status_code == 403
    payload = response.json()
    assert payload["ok"] is False
    assert "Jeton de sécurité" in payload["error"]


def test_api_avec_jeton_dans_entete_acceptee(client, company):
    token = helpers.token_for(client, "/decisions/new")
    response = client.post(
        "/api/projects/compute",
        json={
            "horizon_years": 5,
            "options": [
                {"key": "a", "name": "A", "purchase_cost": 80000, "annual_opex": 24000, "annual_emissions_kg": 45000},
                {"key": "b", "name": "B", "purchase_cost": 95000, "annual_opex": 17000, "annual_emissions_kg": 40000},
            ],
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["analysis"]["comparison"]["cheapest_key"] == "b"


def test_cle_etrangere_csrf_ne_suffit_pas(client):
    """Le cookie de double soumission ne remplace pas le jeton de session."""
    page = client.get("/login")
    assert page.status_code == 200
    response = client.post("/login", data={"email": "x@y.ma", "password": "z", "csrf_token": "faux"})
    assert response.status_code == 403


def test_formulaire_anonyme_jeton_des_le_premier_affichage(client):
    """Premier affichage : le champ caché doit égaler le cookie posé par cette réponse.

    Sans cela, le premier envoi d'un visiteur sans cookie ``cl_csrf`` (navigateur
    vierge) est systématiquement refusé par la protection CSRF.
    """
    page = client.get("/login")
    hidden = helpers.csrf_field(page)
    cookie = client.cookies.get("cl_csrf")
    assert hidden, "Le formulaire de connexion doit contenir un jeton CSRF."
    assert hidden == cookie, "Le champ caché doit correspondre au cookie posé."

    # Jeton accepté (401 : identifiants refusés, pas 403 : jeton refusé).
    response = client.post(
        "/login",
        data={"email": "inconnu@exemple.ma", "password": "MotDePasse!2026", "csrf_token": hidden},
        follow_redirects=False,
    )
    assert response.status_code == 401

    register = client.get("/register")
    champ = helpers.csrf_field(register)
    assert champ and champ == client.cookies.get("cl_csrf")


# ---------------------------------------------------------------------------
# Session et en-têtes de sécurité
# ---------------------------------------------------------------------------
def test_cookie_de_session_protege(client):
    page = client.get("/register")
    token = client.cookies.get("cl_csrf") or helpers.csrf_field(page)
    response = client.post(
        "/register",
        data={
            "full_name": "Utilisateur Test",
            "company_name": "PME Cookie SARL",
            "ice": "001234567000013",
            "sector": "services",
            "company_size": "10",
            "email": helpers.next_email(),
            "password": helpers.DEFAULT_PASSWORD,
            "password_confirm": helpers.DEFAULT_PASSWORD,
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    cookie = response.headers.get("set-cookie", "")
    assert "cl_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Lax" in cookie or "lax" in cookie
    # Le cookie de double soumission est supprimé : le jeton de session fait foi
    assert "cl_csrf=;" in cookie or "cl_csrf=\"\"" in cookie


def test_en_tetes_de_securite(client):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp       # aucun script en ligne autorisé
    assert "frame-ancestors 'none'" in csp


def test_deconnexion_detruit_la_session(client, company):
    token = helpers.token_for(client, "/")
    response = helpers.post_fields(client, "/logout", [("csrf_token", token)], follow_redirects=False)
    assert response.status_code == 303
    suivante = client.get("/", follow_redirects=False)
    assert suivante.status_code == 303
    assert suivante.headers.get("location", "").startswith("/login")


def test_acces_anonyme_redirige_vers_la_connexion(client):
    page = client.get("/expenses", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")

    api = client.get("/api/factors", follow_redirects=False)
    assert api.status_code in (401, 403)
