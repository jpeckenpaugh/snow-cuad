SHELL := /bin/bash
CURDIR := $(shell pwd)
PY    := .venv/bin/python
SNOW  := .venv/bin/snow

# Export .env into the environment, then drop DATABASE/SCHEMA/WAREHOUSE so the
# connection never tries to use objects that may not exist yet. Every SQL file
# sets them explicitly.
SQL_ENV = set -a; source .env; set +a; \
          unset SNOWFLAKE_DATABASE SNOWFLAKE_SCHEMA SNOWFLAKE_WAREHOUSE; \
          $(SNOW) sql -x

RENDERED := build/02_load.rendered.sql
RENDERED_DIM := build/05_dimensions.rendered.sql

.DEFAULT_GOAL := help

.PHONY: help bootstrap keypair check-env doctor download build setup load views \
        verify pipeline users app sql query teardown clean-stage clean

PORT ?= 8501

help: ## Show available targets
	@echo "Usage: make <target>"
	@echo
	@echo "  1. Environment"
	@echo "    bootstrap    Create .venv (Python 3.14), install deps, seed .env"
	@echo "    keypair      Generate RSA key pair for key-pair auth"
	@echo "    check-env    Validate .env locally (no network)"
	@echo "    doctor       Validate .env and test the Snowflake connection"
	@echo
	@echo "  2. Corpus"
	@echo "    download     Fetch CUADv1.json + category_descriptions.csv"
	@echo "    build        Build NDJSON load files and manifest"
	@echo "    setup        Create warehouse, database, schema, tables, stage"
	@echo "    load         Upload NDJSON and COPY INTO all eight tables"
	@echo "    views        Create register, facet, clause index, related-doc views"
	@echo "    verify       Assert counts and referential integrity"
	@echo "    pipeline     download -> build -> setup -> load -> views -> verify"
	@echo
	@echo "  3. Application"
	@echo "    users        Create the three demo logins, write credentials.txt"
	@echo "    app          Run the Streamlit search UI (PORT=8501)"
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

keypair: ## Generate RSA key pair for key-pair authentication
	./scripts/gen_keypair.sh

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

setup: ## Create warehouse, database, schema, tables, stage
	@$(MAKE) --no-print-directory sql FILE=sql/00_setup.sql
	@$(MAKE) --no-print-directory sql FILE=sql/01_tables.sql

load: ## Upload and COPY INTO all eight tables
	@test -f build/manifest.json || { echo "error: build/manifest.json missing; run 'make build'"; exit 1; }
	@test -f build/dimensions.json || { echo "error: build/dimensions.json missing; run 'make build'"; exit 1; }
	@mkdir -p build
	@sed 's|__BUILD_DIR__|$(CURDIR)/build|g' sql/02_load.sql > $(RENDERED)
	@$(SQL_ENV) -f $(RENDERED)
	@sed 's|__BUILD_DIR__|$(CURDIR)/build|g' sql/05_dimensions.sql > $(RENDERED_DIM)
	@$(SQL_ENV) -f $(RENDERED_DIM)

views: ## Create the register, facet, clause index and related-doc views
	@$(MAKE) --no-print-directory sql FILE=sql/03_views.sql
	@$(MAKE) --no-print-directory sql FILE=sql/06_dimension_views.sql

verify: ## Assert row counts and referential integrity
	$(PY) scripts/verify_load.py

pipeline: ## Run the whole corpus load end to end
	@$(MAKE) --no-print-directory download
	@$(MAKE) --no-print-directory build
	@$(MAKE) --no-print-directory setup
	@$(MAKE) --no-print-directory load
	@$(MAKE) --no-print-directory views
	@$(MAKE) --no-print-directory verify

# --- 3. Application ----------------------------------------------------------

users: ## Create the three demo logins (FORCE=1 to rotate passwords)
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

clean: ## Remove .venv and build output
	rm -rf .venv build
	@echo "removed .venv build (kept .env, keys/, data/)"
