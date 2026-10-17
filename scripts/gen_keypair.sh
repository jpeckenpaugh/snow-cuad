#!/usr/bin/env bash
# Generate an RSA key pair for Snowflake key-pair auth and print the
# ALTER USER statement needed to register the public key.
#
# Idempotent-ish: refuses to overwrite existing keys unless FORCE=1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KEY_DIR="keys"
PRIVATE_KEY="$KEY_DIR/snowflake_key.p8"
PUBLIC_KEY="$KEY_DIR/snowflake_key.pub"
PUBLIC_B64="$KEY_DIR/snowflake_key.pub.b64"

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || die "openssl not found"

if [ -f "$PRIVATE_KEY" ] && [ "${FORCE:-0}" != "1" ]; then
  die "$PRIVATE_KEY exists. Re-run with FORCE=1 to rotate (this invalidates the old key)."
fi

mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

# 2048-bit RSA, PKCS#8, unencrypted (Snowflake accepts this).
openssl genrsa 2048 2>/dev/null \
  | openssl pkcs8 -topk8 -inform PEM -out "$PRIVATE_KEY" -nocrypt

openssl rsa -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY" 2>/dev/null

# Snowflake wants the base64 body only, no PEM headers, no newlines.
grep -v -- '-----BEGIN PUBLIC KEY-----' "$PUBLIC_KEY" \
  | grep -v -- '-----END PUBLIC KEY-----' \
  | tr -d '\n' > "$PUBLIC_B64"

chmod 600 "$PRIVATE_KEY" "$PUBLIC_KEY" "$PUBLIC_B64"

USER_NAME="$(grep -E '^SNOWFLAKE_USER=' .env 2>/dev/null | cut -d= -f2- || true)"
[ -n "$USER_NAME" ] || USER_NAME="<YOUR_SNOWFLAKE_USER>"

cat <<EOF

Key pair written to $KEY_DIR/
  private : $PRIVATE_KEY   (chmod 600, gitignored)
  public  : $PUBLIC_B64

.env should point at it:
  SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT
  SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8

Register the public key. Run this as ACCOUNTADMIN (or a role that owns the user),
in the Snowflake worksheet / SnowSQL -- NOT through this CLI connection, since the
key is not yet trusted:

  ALTER USER $USER_NAME SET RSA_PUBLIC_KEY='$(cat "$PUBLIC_B64")';

Verify with:  make doctor
EOF
