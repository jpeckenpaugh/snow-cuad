SHELL := /bin/bash
CURDIR := $(shell pwd)
PY    := .venv/bin/python
SNOW  := ./scripts/snow.sh

# scripts/snow.sh loads .env, resolves which credential works, drops
# DATABASE/SCHEMA/WAREHOUSE so the connection never reaches for objects that
# may not exist yet, and execs the real CLI. Every SQL file sets them explicitly.
SQL_ENV = $(SNOW) sql -x

RENDERED := build/02_load.rendered.sql
RENDERED_DIM := build/05_dimensions.rendered.sql

.DEFAULT_GOAL := help

.PHONY: help bootstrap keypair check-env doctor download build setup load views \
        verify grants service-user verify-privileges pipeline users app sql query \
        demo-video teardown clean-stage clean

PORT ?= 8501

help: ## Show available targets
	@echo "Usage: make <target>"
	@echo
	@echo "  1. Environment"
	@echo "    bootstrap    Create .venv (Python 3.14), install deps, seed .env"
	@echo "    keypair      Generate + register your admin key pair, switch .env"
	@echo "    check-env    Validate .env locally (no network)"
	@echo "    doctor       Validate .env and test the Snowflake connection"
	@echo
	@echo "  2. Corpus"
	@echo "    download     Fetch CUADv1.json + category_descriptions.csv"
	@echo "    build        Build NDJSON load files and manifest"
	@echo "    setup        Create warehouse, database, schema, tables, stage"
	@echo "    load         Upload NDJSON and COPY INTO all eight tables"
	@echo "    views        Create register, facet, clause index, related-doc views"
	@echo "    grants       Apply STREAMLITWEB_ROLE (least privilege; re-run after DDL)"
	@echo "    service-user Create the STREAMLITWEB service user, key pair, .env.service"
	@echo "    verify       Assert counts and referential integrity"
	@echo "    verify-privileges  Assert the service identity is least-privilege"
	@echo "    pipeline     full rebuild: download -> build -> setup -> load -> views"
	@echo "                 -> grants -> service-user -> users -> verify"
	@echo
	@echo "  3. Application"
	@echo "    users        Create the three demo logins, write credentials.txt"
	@echo "    app          Run the Streamlit search UI (PORT=8501)"
	@echo
	@echo "  4. Demo asset"
	@echo "    demo-video   Build build/demo/demo-720p.mp4 (Playwright in Docker)"
	@echo
	@echo "  4. Utilities"
	@echo "    sql          Run a SQL file:  make sql FILE=sql/00_setup.sql"
	@echo "    query        Run inline SQL:  make query Q='select 1'"
	@echo "    clean-stage  Remove uploaded files from @CUAD_LOAD"
	@echo "    teardown     DROP DATABASE CUAD_DB and WAREHOUSE CUAD_WH"
	@echo "    clean        Remove .venv and build output (keeps .env, data, keys)"

# --- 1. Environment ----------------------------------------------------------

bootstrap: ## Create venv, install CLI, seed .env
	./scripts/bootstrap.sh

keypair: ## Generate + register a key pair for your admin user, switch .env to it
	$(PY) scripts/manage_keypair.py $(if $(FORCE),--force,)

check-env: ## Validate .env without connecting
	$(PY) scripts/envcheck.py

doctor: ## Validate .env and connect to Snowflake
	$(PY) scripts/envcheck.py --connect

# --- 2. Corpus ---------------------------------------------------------------

download: ## Fetch CUAD artifacts into data/cuad
	$(PY) scripts/download_cuad.py

build: ## Build NDJSON load files and navigation dimensions
	$(PY) scripts/build_load_files.py
	$(PY) scripts/build_dimensions.py

setup: ## Create warehouse, database, schema, tables, stage, users, audit log
	@$(MAKE) --no-print-directory sql FILE=sql/00_setup.sql
	@$(MAKE) --no-print-directory sql FILE=sql/01_tables.sql
	@$(MAKE) --no-print-directory sql FILE=sql/04_users.sql

load: ## Upload and COPY INTO all eight tables
	@test -f build/manifest.json || { echo "error: build/manifest.json missing; run 'make build'"; exit 1; }
	@test -f build/dimensions.json || { echo "error: build/dimensions.json missing; run 'make build'"; exit 1; }
	@mkdir -p build
	@sed 's|__BUILD_DIR__|$(CURDIR)/build|g' sql/02_load.sql > $(RENDERED)
	@$(SQL_ENV) -f $(RENDERED)
	@sed 's|__BUILD_DIR__|$(CURDIR)/build|g' sql/05_dimensions.sql > $(RENDERED_DIM)
	@$(SQL_ENV) -f $(RENDERED_DIM)

views: ## Create the register, facet, clause index, related-doc views and audit log
	@$(MAKE) --no-print-directory sql FILE=sql/03_views.sql
	@$(MAKE) --no-print-directory sql FILE=sql/06_dimension_views.sql
	@$(MAKE) --no-print-directory sql FILE=sql/07_audit.sql

verify: ## Assert row counts and referential integrity
	$(PY) scripts/verify_load.py

grants: ## Apply the STREAMLITWEB_ROLE grants (safe to re-run)
	@$(MAKE) --no-print-directory sql FILE=sql/08_grants.sql

service-user: ## Create the STREAMLITWEB service user, key pair and .env.service
	$(PY) scripts/create_service_user.py $(if $(FORCE),--force,)

verify-privileges: ## Assert the service identity can do only what it should
	$(PY) scripts/verify_privileges.py

pipeline: ## Full rebuild: corpus, service identity, logins, verification
	@$(MAKE) --no-print-directory download
	@$(MAKE) --no-print-directory build
	@$(MAKE) --no-print-directory setup
	@$(MAKE) --no-print-directory load
	@$(MAKE) --no-print-directory views
	@$(MAKE) --no-print-directory grants
	@$(MAKE) --no-print-directory service-user
	@$(MAKE) --no-print-directory users
	@$(MAKE) --no-print-directory verify

# --- 3. Application ----------------------------------------------------------

users: ## Seed the demo logins (FORCE=1 to rotate passwords)
	@$(MAKE) --no-print-directory sql FILE=sql/04_users.sql
	$(PY) scripts/create_users.py $(if $(FORCE),--force,)

app: ## Run the Streamlit search UI
	$(PY) -m streamlit run app/streamlit_app.py --server.port $(PORT)

# --- 4. Utilities ------------------------------------------------------------

sql: ## Run a SQL file through the snow CLI
	@test -n "$(FILE)" || { echo "usage: make sql FILE=sql/00_setup.sql"; exit 1; }
	@test -f "$(FILE)" || { echo "no such file: $(FILE)"; exit 1; }
	@$(SQL_ENV) -f "$(FILE)"

query: ## Run one SQL statement
	@test -n "$(Q)" || { echo "usage: make query Q='select current_user()'"; exit 1; }
	@$(SQL_ENV) -q "$(Q)"

clean-stage: ## Remove uploaded load files from the stage
	@$(SQL_ENV) -q "REMOVE @CUAD_DB.CORPUS.CUAD_LOAD"

teardown: ## Drop the database and warehouse
	@$(MAKE) --no-print-directory sql FILE=sql/99_teardown.sql

DEMO_IMAGE := cuad-demo-builder
DEMO_DIR   := build/demo

demo-video: ## Build the 720p side-by-side demo video (needs Docker + credentials.txt)
	@command -v docker >/dev/null || { echo "error: docker not found"; exit 1; }
	@test -f .env || { echo "error: .env not found; run make bootstrap"; exit 1; }
	@test -f credentials.txt || { echo "error: credentials.txt not found; run make users"; exit 1; }
	@mkdir -p $(DEMO_DIR)
	docker build -q -t $(DEMO_IMAGE) demo
	docker run --rm --init \
	  -v "$(CURDIR):/workspace" \
	  -v "$(CURDIR)/$(DEMO_DIR):/artifacts" \
	  $(DEMO_IMAGE)
	@echo
	@ls -lh $(DEMO_DIR)/demo-720p.mp4

clean: ## Remove .venv and build output
	rm -rf .venv build
	@echo "removed .venv build (kept .env, keys/, data/)"
