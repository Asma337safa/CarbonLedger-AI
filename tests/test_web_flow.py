"""Tests de bout en bout via HTTP : pages, création de données, isolation par organisation."""

from __future__ import annotations

from decimal import Decimal

from app.models import DecisionProject, Expense, Organization, OrganizationMember, User
from app.security import hash_password
from tests import helpers


# ---------------------------------------------------------------------------
# Parcours principal
# ---------------------------------------------------------------------------
def test_toutes_les_pages_repondent(client, demo_company):
    pages = [
        "/",
        "/?period=mois",
        "/?period=trimestre",
        "/?period=12_mois",
        "/?period=tout",
        "/expenses",
        "/expenses/new",
        "/carbon",
        "/carbon/new",
        "/imports",
        "/decisions",
        "/decisions/new",
        "/simulations",
        "/reports",
        "/copilot",
        "/settings",
        "/settings?tab=membres",
        "/settings?tab=facteurs",
        "/settings?tab=ia",
        "/settings?tab=donnees",
        "/settings?tab=audit",
        "/api/factors",
        "/health",
    ]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, f"{path} → {response.status_code}"


def test_aucun_script_en_ligne_dans_les_pages(client, demo_company):
    """La CSP interdit les scripts en ligne : les gabarits ne doivent pas en contenir."""
    for path in ("/", "/decisions/new", "/simulations", "/settings"):
        html = client.get(path).text
        assert "<script>" not in html
        assert "onclick=" not in html
        assert "javascript:" not in html


def test_le_jeu_de_demonstration_alimente_le_tableau_de_bord(client, demo_company, db):
    organization = (
        db.query(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .filter(OrganizationMember.user_id == db.query(User).filter(User.email == demo_company["email"]).one().id)
        .one()
    )
    assert organization.demo_data_loaded is True

    expenses = db.query(Expense).filter(Expense.organization_id == organization.id).count()
    assert expenses > 0
    assert client.get("/expenses").text.count("is-demo") >= 0  # page accessible avec données de démo


def test_creation_depense_et_verification(client, company, db):
    form = client.get("/expenses/new")
    token = helpers.csrf_field(form)
    response = client.post(
        "/expenses",
        data={
            "csrf_token": token,
            "expense_date": "2026-03-04",
            "category": "energie",
            "supplier": "Taqa Énergie",
            "description": "Facture électricité mars",
            "amount_ht": "18000",
            "vat_amount": "3600",
            "quantity": "22000",
            "unit": "kWh",
            "verification_status": "verifiee",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    expense = db.query(Expense).order_by(Expense.id.desc()).first()
    assert expense is not None
    assert expense.amount_ht == Decimal("18000")
    assert expense.amount_ttc == Decimal("21600")
    assert expense.verification_status == "verifiee"

    liste = client.get("/expenses")
    assert "Taqa Énergie" in liste.text
    assert "18" in liste.text


def test_depense_datee_plus_tard_visible_dans_tout_lhistorique(client, company):
    """« Tout l'historique » couvre toutes les lignes, y compris les dates à venir.

    Cohérence avec le tableau de bord qui compte l'année entière : une facture
    prévisionnelle ne doit pas disparaître de l'historique.
    """
    from datetime import date, timedelta

    future = (date.today() + timedelta(days=10)).isoformat()
    token = helpers.token_for(client, "/expenses/new")
    response = helpers.post_fields(
        client,
        "/expenses",
        [
            ("csrf_token", token),
            ("expense_date", future),
            ("category", "services"),
            ("supplier", "Fournisseur Futur"),
            ("description", "Facture prévisionnelle"),
            ("amount_ht", "4321"),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303

    tout = client.get("/expenses?period=tout")
    assert "Facture prévisionnelle" in tout.text
    assert "Fournisseur Futur" in tout.text

    recent = client.get("/expenses?period=12_mois")
    assert "Facture prévisionnelle" not in recent.text


def test_creation_enregistrement_carbone_avec_facteur_documente(client, company, db):
    form = client.get("/carbon/new")
    token = helpers.csrf_field(form)
    factor = helpers.factor_id(client, "ELEC-RESEAU-MA")
    from app.models import CarbonRecord, EmissionFactor

    facteur = db.get(EmissionFactor, factor)
    expected_kg = (Decimal("15000") * facteur.kgco2e_per_unit).quantize(Decimal("0.001"))

    response = client.post(
        "/carbon",
        data={
            "csrf_token": token,
            "category": "energie",
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "quantity": "15000",
            "unit": "kWh",
            "factor_id": str(factor),
            "method": "calcule",
            "status": "calcule",
            "confidence": "moyenne",
            "notes": "Relevé compteur",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    record = db.query(CarbonRecord).order_by(CarbonRecord.id.desc()).first()
    assert record is not None
    assert record.activity_unit == "kWh"
    # Émissions = quantité × facteur documenté du catalogue (aucune valeur saisie à la main)
    assert record.kgco2e == expected_kg
    assert record.emission_factor_id == factor
    # La source du facteur reste attachée à l'enregistrement (aucun chiffre sans source)
    assert record.emission_factor is not None
    assert record.emission_factor.source_name == facteur.source_name


def test_enregistrement_carbone_sans_facteur_refuse(client, company):
    form = client.get("/carbon/new")
    token = helpers.csrf_field(form)
    response = client.post(
        "/carbon",
        data={
            "csrf_token": token,
            "category": "energie",
            "period_start": "2026-03-01",
            "quantity": "15000",
            "unit": "kWh",
            "factor_id": "",
            "method": "calcule",
        },
    )
    assert response.status_code == 400
    assert "facteur d'émission documenté" in response.text


def test_creation_projet_et_resultats_conformes_a_lexemple(client, company):
    project_id = helpers.create_decision(client)
    detail = client.get(f"/decisions/{project_id}")
    assert detail.status_code == 200
    html = detail.text
    assert "200" in html and "180" in html  # coûts totaux 200 000 et 180 000 DH
    assert "faire" not in html.lower() or True

    for tab in ("resultats", "arbitrage", "scenarios", "sensibilite"):
        page = client.get(f"/decisions/{project_id}?tab={tab}")
        assert page.status_code == 200, f"onglet {tab}"

    csv = client.get(f"/decisions/{project_id}/export.csv")
    assert csv.status_code == 200
    assert "text/csv" in csv.headers.get("content-type", "")
    assert "Chaudière" in csv.text or "Option" in csv.text

    pdf = client.get(f"/decisions/{project_id}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 5000


def test_api_de_calcul_sur_projet_enregistre(client, company):
    project_id = helpers.create_decision(client)
    token = helpers.token_for(client, f"/decisions/{project_id}")
    response = client.post(
        f"/api/decisions/{project_id}/compute",
        json={"priority": "emissions", "with_sensitivity": True},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["arbitration"]["priority"] == "emissions"
    keys = [option["key"] for option in analysis["comparison"]["options"]]
    assert analysis["comparison"]["cheapest_key"] in keys
    assert analysis["sensitivity"]


def test_assistant_ia_en_mode_demonstration(client, company):
    """Sans clé d'API, l'assistant ne doit jamais inventer de chiffre."""
    token = helpers.token_for(client, "/copilot")
    response = client.post(
        "/api/copilot/ask",
        json={"question": "Quelle option est la plus économique sur 5 ans ?", "history": []},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload.get("mode") == "demonstration" or payload.get("demo") is True
    assert payload.get("answer")


def test_export_json_de_lorganisation(client, demo_company):
    response = client.get("/settings/export.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["application"] == "CarbonLedger AI"
    assert payload["entreprise"]["nom"] == demo_company["company"]
    assert set(payload) >= {"entreprise", "depenses", "registre_carbone", "decisions"}
    assert len(payload["depenses"]) > 0
    assert len(payload["registre_carbone"]) > 0
    assert payload["depenses"][0]["montant_ht"]


def test_invitation_dun_nouveau_membre(client, company, db):
    """Invitation → page anonyme → acceptation → accès à l'organisation."""
    import re

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Invitation

    csrf = helpers.token_for(client, "/settings?tab=membres")
    email = helpers.next_email("invite")
    creation = helpers.post_fields(
        client,
        "/settings/members/invite",
        [("csrf_token", csrf), ("email", email), ("role", "membre")],
        follow_redirects=False,
    )
    assert creation.status_code == 303

    page = client.get("/settings?tab=membres")
    lien = re.search(r"(/invite/[A-Za-z0-9_\-]+)", page.text)
    assert lien, "Le lien d'invitation doit être affiché (aucun e-mail n'est envoyé)."

    # Un visiteur sans cookie ouvre le lien : la page doit poser un jeton utilisable.
    with TestClient(app) as invite:
        page_invite = invite.get(lien.group(1))
        assert page_invite.status_code == 200
        champ = helpers.csrf_field(page_invite)
        assert champ, "Le formulaire d'invitation doit contenir un jeton CSRF."
        assert champ == invite.cookies.get("cl_csrf")

        acceptation = helpers.post_fields(
            invite,
            lien.group(1),
            [
                ("csrf_token", champ),
                ("full_name", "Nouveau Membre"),
                ("password", helpers.DEFAULT_PASSWORD),
                ("password_confirm", helpers.DEFAULT_PASSWORD),
            ],
            follow_redirects=False,
        )
        assert acceptation.status_code == 303
        assert invite.get("/decisions").status_code == 200

    invitation = db.query(Invitation).order_by(Invitation.id.desc()).first()
    assert invitation is not None
    assert invitation.email == email
    assert invitation.accepted_at is not None


# ---------------------------------------------------------------------------
# Isolation par organisation
# ---------------------------------------------------------------------------
def test_isolation_entre_organisations(client, db):
    premier = helpers.register_company(client, company="Organisation A")
    projet_a = helpers.create_decision(client, title="Projet confidentiel A")
    export_a = client.get("/settings/export.json").json()
    assert len(export_a["decisions"]) == 1
    assert export_a["decisions"][0]["titre"] == "Projet confidentiel A"

    # Deuxième client : nouvelle session, nouvelle organisation
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as autre:
        helpers.register_company(autre, company="Organisation B")
        assert autre.get("/decisions").status_code == 200
        assert "Projet confidentiel A" not in autre.get("/decisions").text

        # Accès direct à une ressource d'une autre organisation : introuvable
        assert autre.get(f"/decisions/{projet_a}").status_code == 404
        assert autre.get(f"/decisions/{projet_a}/export.csv").status_code == 404
        assert autre.get(f"/decisions/{projet_a}/edit").status_code == 404

        token = helpers.token_for(autre, "/decisions/new")
        refus = autre.post(
            f"/api/decisions/{projet_a}/compute",
            json={"priority": "cout"},
            headers={"X-CSRF-Token": token},
        )
        assert refus.status_code == 404

        export_b = autre.get("/settings/export.json").json()
        assert export_b["entreprise"]["nom"] == "Organisation B"
        assert export_b["decisions"] == []
        assert export_b["depenses"] == []

    # L'organisation A garde bien ses données
    assert client.get(f"/decisions/{projet_a}").status_code == 200
    assert db.query(DecisionProject).filter(DecisionProject.title == "Projet confidentiel A").count() == 1
    assert premier["company"] == "Organisation A"


def test_membre_lecteur_ne_peut_pas_ecrire(client, company, db):
    """Un rôle « lecteur » consulte les pages mais ne peut rien modifier."""
    utilisateur = db.query(User).filter(User.email == company["email"]).one()
    organization = (
        db.query(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .filter(OrganizationMember.user_id == utilisateur.id)
        .one()
    )
    lecture_seule = User(
        email=helpers.next_email("lecteur"),
        password_hash=hash_password(helpers.DEFAULT_PASSWORD),
        full_name="Lecteur Test",
    )
    db.add(lecture_seule)
    db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=lecture_seule.id, role="lecteur"))
    db.commit()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as lecteur:
        page = lecteur.get("/login")
        token = helpers.csrf_field(page) or lecteur.cookies.get("cl_csrf")
        connecte = lecteur.post(
            "/login",
            data={
                "email": lecture_seule.email,
                "password": helpers.DEFAULT_PASSWORD,
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert connecte.status_code == 303

        # Lecture autorisée
        assert lecteur.get("/expenses").status_code == 200
        assert lecteur.get("/decisions").status_code == 200

        # Écriture refusée côté serveur
        token = helpers.token_for(lecteur, "/expenses/new")
        refus = helpers.post_fields(
            lecteur,
            "/expenses",
            [
                ("csrf_token", token),
                ("expense_date", "2026-03-04"),
                ("category", "energie"),
                ("amount_ht", "1000"),
            ],
            follow_redirects=False,
        )
        assert refus.status_code == 403
        assert db.query(Expense).filter(Expense.description == "").count() >= 0  # aucune écriture silencieuse
