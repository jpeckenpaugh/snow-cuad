#!/usr/bin/env python3
"""Generate, register and activate an RSA key pair for the admin user.

`make keypair` used to print an ALTER USER statement and tell you to run it in
a worksheet, then edit .env yourself. That is two manual steps with a
lockout at the end of them. This does all three against the connection you
already have:

  1. generate the key pair (keys/snowflake_key.p8)
  2. register the public half on your user
  3. verify the key actually authenticates
  4. only then switch .env to SNOWFLAKE_JWT

Steps 3 and 4 are ordered that way on purpose. The new credentials are tested
before .env is touched, so a failure leaves you with a working password login
rather than a broken file. The old authenticator and password are kept as
comments in .env, so reverting is uncommenting two lines.

Usage:
    python scripts/manage_keypair.py [--force] [--no-switch]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

from credentials import load_or_create_key_pair  # noqa: E402

ENV_FILE = ROOT / ".env"
KEY_PATH = ROOT / "keys" / "snowflake_key.p8"


def admin_connect(**extra):
    """Connect with the *current* .env credentials.

    Deliberately not sf.connect(): onboarding has to work before CUAD_WH or
    CUAD_DB exist, and sf.connect supplies a default warehouse. No warehouse,
    database or schema is requested here.
    """
    import snowflake.connector

    load_dotenv(ENV_FILE, override=True)
    authenticator = os.getenv("SNOWFLAKE_AUTHENTICATOR", "SNOWFLAKE")

    params = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "role": os.getenv("SNOWFLAKE_ROLE") or None,
        "authenticator": authenticator,
        "login_timeout": 20,
    }
    if authenticator == "SNOWFLAKE_JWT":
        key_path = Path(os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")).expanduser()
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        params["private_key_file"] = str(key_path)
        if os.getenv("PRIVATE_KEY_PASSPHRASE"):
            params["private_key_file_pwd"] = os.environ["PRIVATE_KEY_PASSPHRASE"]
    else:
        params["password"] = os.environ["SNOWFLAKE_PASSWORD"]

    params.update(extra)
    return snowflake.connector.connect(**params)


def jwt_connect(public_key: str) -> dict:
    """Prove the new private key authenticates, using no stored credentials."""
    import snowflake.connector

    params = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "role": os.getenv("SNOWFLAKE_ROLE") or None,
        "authenticator": "SNOWFLAKE_JWT",
        "private_key_file": str(KEY_PATH),
        "login_timeout": 20,
    }
    with snowflake.connector.connect(**params) as conn:
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_ACCOUNT()")
        return dict(zip(("user", "role", "account"), cur.fetchone()))


AUTH_MARKER = "# --- Authentication"


def _capture(pattern: str, text: str) -> str | None:
    """Last non-empty value for an env key, commented or not."""
    value = None
    for line in text.splitlines():
        match = re.match(pattern, line)
        if match and match.group(1).strip():
            value = match.group(1).strip()
    return value


def switched_env_text(text: str) -> str:
    """Return .env with key-pair auth active and the password kept, commented.

    Replaces the whole authentication block rather than editing lines in
    place: a surgical rewrite left the active JWT pair sitting under the
    "B) Password" heading, which reads as a mistake.
    """
    password = _capture(r"\s*#?\s*SNOWFLAKE_PASSWORD=(.+)$", text)
    passphrase = _capture(r"\s*#?\s*PRIVATE_KEY_PASSPHRASE=(.+)$", text)

    lines = text.splitlines()
    marker = next((i for i, line in enumerate(lines) if line.startswith(AUTH_MARKER)), None)
    header = lines[:marker] if marker is not None else lines

    block = [
        AUTH_MARKER + " ------------------------------------------------------",
        "# Key-pair (active). Generated and registered by `make keypair`.",
        "# Key-pair is not password auth, so the account's MFA-for-passwords",
        "# policy does not apply - which is what lets `make` run unattended.",
        "SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT",
        "SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8",
        f"PRIVATE_KEY_PASSPHRASE={passphrase or ''}",
        "",
        "# Revert: comment the three SNOWFLAKE_*/PRIVATE_KEY lines above, then",
        "# uncomment the password pair below.",
    ]
    if password:
        block += [
            "# SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE",
            "# SNOWFLAKE_PASSWORD=" + password,
        ]
    else:
        block += [
            "# SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE",
            "# SNOWFLAKE_PASSWORD=",
        ]
    return "\n".join(header + block) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rotate the key pair")
    ap.add_argument("--no-switch", action="store_true",
                    help="generate and register, but leave .env alone")
    args = ap.parse_args()

    if not ENV_FILE.exists():
        print(f"error: {ENV_FILE} missing. Run `make bootstrap` first.", file=sys.stderr)
        return 1

    existed = KEY_PATH.exists()
    public_key = load_or_create_key_pair(KEY_PATH, force=args.force)
    print(f"{'reused' if existed and not args.force else 'generated'} {KEY_PATH.relative_to(ROOT)}")

    load_dotenv(ENV_FILE, override=True)
    user = os.environ["SNOWFLAKE_USER"]

    # 1. register the public key using whatever credentials currently work
    with admin_connect() as conn:
        cur = conn.cursor()
        cur.execute(f"ALTER USER {user} SET RSA_PUBLIC_KEY = '{public_key}'")
        cur.execute(f"DESC USER {user}")
        fingerprint = "set"
        print(f"registered public key on {user} ({fingerprint})")

    # 2. prove the new key authenticates before touching .env
    try:
        who = jwt_connect(public_key)
    except Exception as exc:  # noqa: BLE001
        print(
            f"\nverification FAILED: key-pair login did not work ({exc}).\n"
            f"{ENV_FILE.name} was left unchanged, so your password login still works.",
            file=sys.stderr,
        )
        return 1

    print(f"verified key-pair login: {who['user']} / {who['role']} / {who['account']}")

    if args.no_switch:
        print("\n--no-switch: .env left alone. To activate, set:")
        print("  SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT")
        print("  SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8")
        return 0

    # 3. switch .env, keeping the old auth as comments for a one-step revert
    original = ENV_FILE.read_text()
    updated = switched_env_text(original)
    ENV_FILE.write_text(updated)
    ENV_FILE.chmod(0o600)

    print(f"\nswitched {ENV_FILE.name} to key-pair auth")
    print("  the old authenticator and password are kept as comments")
    print(f"  private key: {KEY_PATH.relative_to(ROOT)} (mode 600)")
    print("\nrevert: uncomment the two '#' lines in .env and delete the JWT pair")
    print("verify: make doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
