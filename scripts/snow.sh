#!/usr/bin/env bash
# `snow` wrapper: load .env, resolve which credential actually works, then
# hand the CLI exactly one of them.
#
# The CLI has no fallback of its own - it errors on a private key with no
# authenticator, and will not retry with a password. The Python connector
# does fall back, so we ask it (scripts/resolve_auth.py) and export the
# answer. See scripts/sf.py for the either-or rule.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

set -a
# shellcheck disable=SC1091
source .env
set +a

# Every SQL file sets these explicitly.
unset SNOWFLAKE_DATABASE SNOWFLAKE_SCHEMA SNOWFLAKE_WAREHOUSE

eval "$("$ROOT/.venv/bin/python" "$ROOT/scripts/resolve_auth.py")"

exec "$ROOT/.venv/bin/snow" "$@"
