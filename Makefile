SHELL := /bin/bash
PY    := .venv/bin/python
SNOW  := .venv/bin/snow

.DEFAULT_GOAL := help

.PHONY: help bootstrap check-env doctor keypair sql query snow-version clean

help: ## Show available targets
	@echo "Usage: make <target>"
	@echo
	@echo "  bootstrap    Create .venv (Python 3.14), install deps, seed .env"
	@echo "  keypair      Generate RSA key pair for key-pair auth"
	@echo "  check-env    Validate .env locally (no network)"
	@echo "  doctor       Validate .env and test the Snowflake connection"
	@echo "  sql          Run a SQL file:      make sql FILE=sql/00_setup.sql"
	@echo "  query        Run inline SQL:      make query Q='select 1'"
	@echo "  snow-version Show the installed snow CLI version"
	@echo "  clean        Remove .venv and build artifacts (keeps .env, keys, data)"

bootstrap: ## Create venv, install CLI, seed .env
	./scripts/bootstrap.sh

keypair: ## Generate RSA key pair for key-pair authentication
	./scripts/gen_keypair.sh

check-env: ## Validate .env without connecting
	$(PY) scripts/envcheck.py

doctor: ## Validate .env and connect to Snowflake
	$(PY) scripts/envcheck.py --connect

snow-version: ## Print the snow CLI version
	@$(SNOW) --version

sql: ## Run a SQL file through the snow CLI (env-driven, no config.toml needed)
	@test -n "$(FILE)" || { echo "usage: make sql FILE=sql/00_setup.sql"; exit 1; }
	@test -f "$(FILE)" || { echo "no such file: $(FILE)"; exit 1; }
	@set -a; source .env; set +a; $(SNOW) sql -x -f "$(FILE)"

query: ## Run one SQL statement
	@test -n "$(Q)" || { echo "usage: make query Q='select current_user()'"; exit 1; }
	@set -a; source .env; set +a; $(SNOW) sql -x -q "$(Q)"

clean: ## Remove .venv and build output
	rm -rf .venv build
	@echo "removed .venv build (kept .env, keys/, data/)"
