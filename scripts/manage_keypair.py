#!/usr/bin/env python3
"""Generate, register and activate an RSA key pair for the admin user.

Order matters more than anything else in this script.

The obvious implementation - generate the key, then connect and register it -
is broken in JWT mode, because `.env` points at the very file you just
overwrote. The new key is not registered yet, so the connection that is
supposed to register it cannot authenticate: "JWT token is invalid".

So:

  1. connect with the credentials we have NOW, before touching key material
  2. generate a new key into a staging file (the live key keeps working)
  3. put the new public key in the spare slot, RSA_PUBLIC_KEY_2
  4. verify the staged key authenticates
  5. promote slot 2 to RSA_PUBLIC_KEY, free slot 2, install the key file
  6. rewrite .env last

Steps 3-5 use Snowflake's two key slots, so a rotation that fails to verify
leaves the existing key working instead of locking you out.

If connecting with .env fails - typically because a previous run left `.env`
on JWT pointing at a key that was never registered - the script falls back to
the password kept as a comment in `.env`, and repairs the account.

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
STAGING_PATH = ROOT / "keys" / "snowflake_key.new.p8"

AUTH_MARKER = "# --- Authentication"


# --- .env parsing ------------------------------------------------------------

def env_value(name: str, *, active_only: bool = False) -> str | None:
    """Last non-empty value for an env key; commented lines count as fallback."""
    if not ENV_FILE.exists():
        return None
    pattern = rf"^\s*({'' if active_only else '#' + '?'}\s*){name}=(.*)$"
    value = None
    for line in ENV_FILE.read_text().splitlines():
        match = re.match(pattern, line)
        if match and match.group(2).strip():
            value = match.group(2).strip()
    return value


def _capture(pattern: str, text: str) -> str | None:
    value = None
    for line in text.splitlines():
        match = re.match(pattern, line)
        if match and match.group(1).strip():
            value = match.group(1).strip()
    return value


def either_or_env_text(text: str) -> str:
    """Return .env carrying BOTH credentials, neither replacing the other.

    The password is not commented out: it stays active and valid, so a key
    that is rotated, unregistered or missing degrades to the password rather
    than locking you out.
    """
    password = _capture(r"\s*#?\s*SNOWFLAKE_PASSWORD=(.+)$", text)
    passphrase = _capture(r"\s*#?\s*PRIVATE_KEY_PASSPHRASE=(.+)$", text)

    lines = text.splitlines()
    marker = next((i for i, line in enumerate(lines) if line.startswith(AUTH_MARKER)), None)
    header = lines[:marker] if marker is not None else lines

    block = [
        AUTH_MARKER + " (either or) ---------------------------------",
        "# Both credentials are kept and both stay valid in Snowflake.",
        "# The tooling tries key-pair first, then the password, so a rotated or",
        "# unregistered key degrades to a slower login instead of a lockout.",
        "SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8",
    ]
    if passphrase:
        block.append(f"PRIVATE_KEY_PASSPHRASE={passphrase}")
    if password:
        block.append(f"SNOWFLAKE_PASSWORD={password}")
    block += [
        "",
        "# Optional: SNOWFLAKE_AUTHENTICATOR only sets which is tried FIRST.",
        "# It is not a filter - the other credential is still attempted.",
        "# SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT",
    ]
    return "\n".join(header + block) + "\n"


# --- connections -------------------------------------------------------------

def _raw_connect(authenticator: str, secret: str) -> "object":
    """Connect with no warehouse, database or schema.

    Onboarding has to work before CUAD_WH or CUAD_DB exist, and before the
    objects this script provisions exist at all.
    """
    import snowflake.connector

    params = {
        "account": env_value("SNOWFLAKE_ACCOUNT", active_only=True),
        "user": env_value("SNOWFLAKE_USER", active_only=True),
        "role": env_value("SNOWFLAKE_ROLE", active_only=True),
        "authenticator": authenticator,
        "login_timeout": 20,
    }
    if authenticator == "SNOWFLAKE_JWT":
        params["private_key_file"] = secret
    else:
        params["password"] = secret
    return snowflake.connector.connect(**{k: v for k, v in params.items() if v})


def admin_connect():
    """Connect with .env, falling back to the commented password if JWT fails.

    Returns (connection, how). The fallback exists so a half-finished rotation
    is recoverable without hand-editing files.
    """
    load_dotenv(ENV_FILE, override=True)
    authenticator = env_value("SNOWFLAKE_AUTHENTICATOR", active_only=True) or "SNOWFLAKE"

    if authenticator == "SNOWFLAKE_JWT":
        key_path = Path(env_value("SNOWFLAKE_PRIVATE_KEY_PATH", active_only=True) or "")
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        try:
            return _raw_connect("SNOWFLAKE_JWT", str(key_path)), "key-pair"
        except Exception as primary_error:  # noqa: BLE001
            password = env_value("SNOWFLAKE_PASSWORD")
            if not password:
                raise
            print(f"  key-pair login failed ({str(primary_error).splitlines()[0][:70]})")
            print("  falling back to the password kept in .env, to repair the account")
            return _raw_connect("SNOWFLAKE", password), "password fallback"

    password = env_value("SNOWFLAKE_PASSWORD", active_only=True) or env_value("SNOWFLAKE_PASSWORD")
    return _raw_connect("SNOWFLAKE", password), "password"


def verify_jwt(key_path: Path) -> dict:
    """Prove a private key authenticates, using nothing from .env's auth block."""
    load_dotenv(ENV_FILE, override=True)
    with _raw_connect("SNOWFLAKE_JWT", str(key_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_ACCOUNT()")
        return dict(zip(("user", "role", "account"), cur.fetchone()))


# --- main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rotate the key pair")
    ap.add_argument("--no-switch", action="store_true",
                    help="generate and register, but leave .env alone")
    args = ap.parse_args()

    if not ENV_FILE.exists():
        print(f"error: {ENV_FILE} missing. Run `make bootstrap` first.", file=sys.stderr)
        return 1

    user = env_value("SNOWFLAKE_USER", active_only=True)
    if not user:
        print("error: SNOWFLAKE_USER is not set in .env", file=sys.stderr)
        return 1

    # 1. Connect BEFORE touching any key material.
    try:
        conn, how = admin_connect()
    except Exception as exc:  # noqa: BLE001
        print(
            f"\ncannot connect with the current .env ({str(exc).splitlines()[0][:90]}).\n"
            "If .env is on JWT and the key was never registered, uncomment the\n"
            "SNOWFLAKE_PASSWORD lines in .env and re-run `make keypair`.",
            file=sys.stderr,
        )
        return 1
    print(f"connected as {user} ({how})")

    existing = KEY_PATH.exists() and not args.force

    with conn:
        cur = conn.cursor()
        cur.execute(f"DESC USER {user}")
        properties = {row[0].upper(): row[1] for row in cur.fetchall()}
        has_key = bool(properties.get("RSA_PUBLIC_KEY_FP"))

        # 2. New keys are staged; the live key file keeps working until the
        #    replacement is proven.
        if existing:
            path = KEY_PATH
            public_key = load_or_create_key_pair(KEY_PATH, force=False)
            print(f"reused {KEY_PATH.relative_to(ROOT)}")
        else:
            path = STAGING_PATH
            public_key = load_or_create_key_pair(STAGING_PATH, force=True)
            print(f"generated {STAGING_PATH.relative_to(ROOT)}")

        # 3-5. Register in the spare slot, verify, then promote.
        slot = "RSA_PUBLIC_KEY_2" if has_key else "RSA_PUBLIC_KEY"
        cur.execute(f"ALTER USER {user} SET {slot} = '{public_key}'")
        print(f"registered public key in {slot}")

        try:
            who = verify_jwt(path)
        except Exception as exc:  # noqa: BLE001
            cur.execute(f"ALTER USER {user} UNSET {slot}")
            if path != KEY_PATH and path.exists():
                path.unlink()
            print(
                f"\nverification FAILED: the new key did not authenticate "
                f"({str(exc).splitlines()[0][:70]}).\n"
                f"Rolled back: {slot} unset, key file removed, .env untouched.",
                file=sys.stderr,
            )
            return 1
        print(f"verified key-pair login: {who['user']} / {who['role']} / {who['account']}")

        if has_key:
            cur.execute(f"ALTER USER {user} SET RSA_PUBLIC_KEY = '{public_key}'")
            cur.execute(f"ALTER USER {user} UNSET RSA_PUBLIC_KEY_2")
            print("promoted to RSA_PUBLIC_KEY and freed the spare slot")

    # 6. Install the staged key and switch .env, last.
    if not existing:
        STAGING_PATH.replace(KEY_PATH)
        STAGING_PATH.with_suffix(".pub").replace(KEY_PATH.with_suffix(".pub"))
        KEY_PATH.chmod(0o600)
        print(f"installed {KEY_PATH.relative_to(ROOT)}")

    if args.no_switch:
        print("\n--no-switch: .env left alone. To activate, set:")
        print("  SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT")
        print("  SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8")
        return 0

    ENV_FILE.write_text(either_or_env_text(ENV_FILE.read_text()))
    ENV_FILE.chmod(0o600)
    print(f"\n{ENV_FILE.name} now carries both credentials")
    print("  key-pair is tried first; the password stays valid as fallback")
    print("revert: uncomment the two '#' lines in .env, delete the JWT pair")
    print("verify: make doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
