-- CarbonLedger AI — schéma de base de données
-- Fichier généré par `python scripts/dump_schema.py` : ne pas modifier à la main.
-- Dialecte de référence : sqlite
-- URL utilisée lors de la génération : sqlite:///D:/CarbonLedger/data/carbonledger.db
--
-- Les migrations Alembic (alembic/versions/*.py) restent la référence pour les
-- évolutions de schéma ; ce fichier documente l'état courant des tables.


CREATE TABLE organizations (
	id INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	ice VARCHAR(20) NOT NULL, 
	sector VARCHAR(80) NOT NULL, 
	company_size VARCHAR(40) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	internal_carbon_price NUMERIC(14, 2) NOT NULL, 
	onboarding_done BOOLEAN NOT NULL, 
	demo_data_loaded BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	full_name VARCHAR(160) NOT NULL, 
	locale VARCHAR(8) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	failed_login_count INTEGER NOT NULL, 
	locked_until DATETIME, 
	created_at DATETIME NOT NULL, 
	last_login_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	organization_id INTEGER, 
	user_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	entity_type VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(40) NOT NULL, 
	details JSON, 
	ip VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_org_created ON audit_logs (organization_id, created_at);
CREATE INDEX ix_audit_logs_organization_id ON audit_logs (organization_id);

CREATE TABLE auth_sessions (
	id VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	organization_id INTEGER, 
	csrf_token VARCHAR(64) NOT NULL, 
	flash JSON, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_seen_at DATETIME, 
	ip VARCHAR(64), 
	user_agent VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);

CREATE TABLE decision_projects (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	horizon_years INTEGER NOT NULL, 
	discount_rate_pct NUMERIC(6, 2) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	internal_carbon_price NUMERIC(14, 2) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	chosen_option_id INTEGER, 
	is_demo BOOLEAN NOT NULL, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_projects_chosen_option FOREIGN KEY(chosen_option_id) REFERENCES decision_options (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_projects_org_status ON decision_projects (organization_id, status);
CREATE INDEX ix_decision_projects_organization_id ON decision_projects (organization_id);

CREATE TABLE emission_factors (
	id INTEGER NOT NULL, 
	organization_id INTEGER, 
	code VARCHAR(60) NOT NULL, 
	label VARCHAR(200) NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	unit VARCHAR(24) NOT NULL, 
	scope VARCHAR(4) NOT NULL, 
	method VARCHAR(20) NOT NULL, 
	kgco2e_per_unit NUMERIC(18, 6) NOT NULL, 
	source_name VARCHAR(200) NOT NULL, 
	source_url VARCHAR(400) NOT NULL, 
	source_version VARCHAR(60) NOT NULL, 
	geography VARCHAR(16) NOT NULL, 
	valid_from DATE, 
	valid_until DATE, 
	confidence VARCHAR(12) NOT NULL, 
	calculation_note TEXT NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_factor_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_factors_unit ON emission_factors (unit);
CREATE INDEX ix_emission_factors_organization_id ON emission_factors (organization_id);

CREATE TABLE import_batches (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	user_id INTEGER, 
	filename VARCHAR(255) NOT NULL, 
	stored_path VARCHAR(500) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	mapping JSON, 
	summary JSON, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_import_batches_organization_id ON import_batches (organization_id);

CREATE TABLE invitations (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	accepted_at DATETIME, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	UNIQUE (token_hash), 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_invitations_organization_id ON invitations (organization_id);
CREATE INDEX ix_invitations_email ON invitations (email);

CREATE TABLE organization_members (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_member_org_user UNIQUE (organization_id, user_id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_organization_members_user_id ON organization_members (user_id);
CREATE INDEX ix_organization_members_organization_id ON organization_members (organization_id);

CREATE TABLE decision_options (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	supplier VARCHAR(200) NOT NULL, 
	purchase_cost NUMERIC(16, 2) NOT NULL, 
	transport_cost NUMERIC(16, 2) NOT NULL, 
	annual_opex NUMERIC(16, 2) NOT NULL, 
	annual_energy_share_pct NUMERIC(6, 2), 
	annual_maintenance NUMERIC(16, 2) NOT NULL, 
	annual_savings NUMERIC(16, 2) NOT NULL, 
	useful_life_years NUMERIC(5, 1), 
	annual_emissions_kg NUMERIC(18, 3), 
	emissions_basis VARCHAR(16), 
	emission_factor_id INTEGER, 
	emissions_source_note TEXT NOT NULL, 
	confidence VARCHAR(12) NOT NULL, 
	notes TEXT NOT NULL, 
	sort_order INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES decision_projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(emission_factor_id) REFERENCES emission_factors (id) ON DELETE SET NULL
);

CREATE INDEX ix_decision_options_project_id ON decision_options (project_id);

CREATE TABLE expenses (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	expense_date DATE NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	supplier VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	amount_ht NUMERIC(16, 2) NOT NULL, 
	vat_amount NUMERIC(16, 2) NOT NULL, 
	amount_ttc NUMERIC(16, 2) NOT NULL, 
	quantity NUMERIC(18, 4), 
	unit VARCHAR(24), 
	emission_factor_id INTEGER, 
	carbon_source_note TEXT NOT NULL, 
	verification_status VARCHAR(20) NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(emission_factor_id) REFERENCES emission_factors (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_expenses_org_date ON expenses (organization_id, expense_date);
CREATE INDEX ix_expenses_organization_id ON expenses (organization_id);
CREATE INDEX ix_expenses_org_category ON expenses (organization_id, category);

CREATE TABLE reports (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	project_id INTEGER, 
	kind VARCHAR(12) NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	period_start DATE, 
	period_end DATE, 
	file_path VARCHAR(500) NOT NULL, 
	payload JSON, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(project_id) REFERENCES decision_projects (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_reports_organization_id ON reports (organization_id);

CREATE TABLE scenarios (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	parameters JSON NOT NULL, 
	notes TEXT NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES decision_projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_scenarios_project_id ON scenarios (project_id);

CREATE TABLE carbon_records (
	id INTEGER NOT NULL, 
	organization_id INTEGER NOT NULL, 
	expense_id INTEGER, 
	option_id INTEGER, 
	category VARCHAR(40) NOT NULL, 
	period_start DATE NOT NULL, 
	period_end DATE NOT NULL, 
	activity_quantity NUMERIC(18, 4) NOT NULL, 
	activity_unit VARCHAR(24) NOT NULL, 
	emission_factor_id INTEGER, 
	method VARCHAR(20) NOT NULL, 
	kgco2e NUMERIC(18, 3) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	confidence VARCHAR(12) NOT NULL, 
	notes TEXT NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(expense_id) REFERENCES expenses (id) ON DELETE CASCADE, 
	FOREIGN KEY(option_id) REFERENCES decision_options (id) ON DELETE CASCADE, 
	FOREIGN KEY(emission_factor_id) REFERENCES emission_factors (id) ON DELETE SET NULL
);

CREATE INDEX ix_carbon_records_expense_id ON carbon_records (expense_id);
CREATE INDEX ix_carbon_records_option_id ON carbon_records (option_id);
CREATE INDEX ix_carbon_records_organization_id ON carbon_records (organization_id);
CREATE INDEX ix_carbon_org_period ON carbon_records (organization_id, period_start);

CREATE TABLE recommendations (
	id INTEGER NOT NULL, 
	project_id INTEGER NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	carbon_price NUMERIC(14, 2) NOT NULL, 
	summary TEXT NOT NULL, 
	details JSON NOT NULL, 
	chosen_option_id INTEGER, 
	created_by_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES decision_projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(chosen_option_id) REFERENCES decision_options (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_recommendations_project_id ON recommendations (project_id);

-- Contraintes d'unicité et clés étrangères : voir les définitions de tables ci-dessus.
