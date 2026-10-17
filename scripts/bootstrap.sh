#!/usr/bin/env bash
# Create .venv with Python 3.14, install Snowflake CLI + deps, seed .env.
#
# Idempotent: safe to re-run. Never overwrites an existing .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3.14}"
VENV="${VENV:-$ROOT/.venv}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Interpreter ----------------------------------------------------------
command -v "$PYTHON_BIN" >/dev/null 2>&1 \
  || die "$PYTHON_BIN not found. Install Python 3.14, or run: PYTHON_BIN=python3.13 make bootstrap"

"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' \
  || die "$PYTHON_BIN is $("$PYTHON_BIN" -V 2>&1); need >= 3.14. Override with PYTHON_BIN=..."

say "Interpreter: $("$PYTHON_BIN" -V 2>&1) ($(command -v "$PYTHON_BIN"))"

# --- 2. Virtualenv -----------------------------------------------------------
if [ -d "$VENV" ]; then
  say "Reusing existing venv at ${VENV#$ROOT/}"
else
  say "Creating venv at ${VENV#$ROOT/}"
  "$PYTHON_BIN" -m venv "$VENV"
fi

# --- 3. Dependencies ---------------------------------------------------------
say "Installing dependencies (requirements.txt)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r requirements.txt

# --- 4. Secret-bearing directories ------------------------------------------
mkdir -p keys data build
chmod 700 keys

# --- 5. .env -----------------------------------------------------------------
if [ -f .env ]; then
  say ".env already exists - left untouched"
else
  cp .env.example .env
  chmod 600 .env
  say "Created .env from .env.example (chmod 600) - fill in CHANGE_ME values"
fi

# --- 6. Summary --------------------------------------------------------------
say "Installed"
printf '  %-12s %s\n' "snow"      "$("$VENV/bin/snow" --version 2>/dev/null | head -1)"
printf '  %-12s %s\n' "connector" "$("$VENV/bin/python" -c 'import snowflake.connector as c; print(c.__version__)')"
printf '  %-12s %s\n' "streamlit" "$("$VENV/bin/python" -c 'import streamlit as s; print(s.__version__)')"
printf '  %-12s %s\n' "python"    "$("$VENV/bin/python" -V 2>&1)"

say "Next"
cat <<'EOF'
  1. Fill in .env:       $EDITOR .env
  2. Add a key pair:     make keypair       # registers it; your password keeps working
  3. Validate + connect: make doctor
EOF
