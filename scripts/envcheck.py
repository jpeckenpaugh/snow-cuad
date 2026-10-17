#!/usr/bin/env python3
"""Validate .env and (optionally) prove the Snowflake connection works.

Usage:
    python scripts/envcheck.py            # validate only, no network
    python scripts/envcheck.py --connect  # validate, then connect + run 3 queries

Exit codes: 0 ok, 1 missing/invalid config, 2 connection/auth failure.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

SECRET_KEYS = {"SNOWFLAKE_PASSWORD", "PRIVATE_KEY_PASSPHRASE"}
PLACEHOLDER_PREFIXES = ("CHANGE_ME", "ORGNAME-", "YOUR_")

REQUIRED = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
]


def redact(key: str, value: str) -> str:
    if key not in SECRET_KEYS or not value:
        return value
    return "*" * min(len(value), 8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", action="store_true", help="attempt a real connection")
    args = ap.parse_args()

    if not ENV_FILE.exists():
        print(f"error: {ENV_FILE} not found. Run `make bootstrap` first.", file=sys.stderr)
        return 1

    load_dotenv(ENV_FILE, override=True)

    errors: list[str] = []

    print(f"env file: {ENV_FILE}  (mode {oct(ENV_FILE.stat().st_mode)[-3:]})")
    if ENV_FILE.stat().st_mode & 0o077:
        print("  warning: .env is readable by group/others; expected 600", file=sys.stderr)

    for key in REQUIRED:
        val = os.getenv(key, "")
        if not val:
            errors.append(f"{key} is empty")
        elif val.startswith(PLACEHOLDER_PREFIXES):
            errors.append(f"{key} still holds the placeholder {val!r}")

    auth = os.getenv("SNOWFLAKE_AUTHENTICATOR", "SNOWFLAKE")
    if auth == "SNOWFLAKE_JWT":
        key_path = Path(os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")).expanduser()
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        if not key_path.exists():
            errors.append(f"SNOWFLAKE_PRIVATE_KEY_PATH not found: {key_path} (run `make keypair`)")
    elif auth in ("SNOWFLAKE", "USERNAME_PASSWORD_MFA"):
        if not os.getenv("SNOWFLAKE_PASSWORD"):
            errors.append("SNOWFLAKE_PASSWORD is required for password auth")
    else:
        errors.append(f"unsupported SNOWFLAKE_AUTHENTICATOR={auth!r}")

    print("\nconfiguration")
    for key in [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
        "SNOWFLAKE_AUTHENTICATOR",
        "SNOWFLAKE_PRIVATE_KEY_PATH",
        "SNOWFLAKE_PASSWORD",
    ]:
        val = os.getenv(key)
        if val is not None:
            print(f"  {key:<28} {redact(key, val)}")

    if errors:
        sys.stdout.flush()
        print("\nproblems:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("\nenv OK")
    if not args.connect:
        print("(skipping connection test; pass --connect to run it)")
        return 0

    try:
        import snowflake.connector as sf

        params = {
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "role": os.environ["SNOWFLAKE_ROLE"],
            "database": os.environ["SNOWFLAKE_DATABASE"],
            "schema": os.environ["SNOWFLAKE_SCHEMA"],
            "authenticator": auth,
            "login_timeout": 20,
        }
        if auth == "SNOWFLAKE_JWT":
            p = Path(os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")).expanduser()
            params["private_key_file"] = str(p if p.is_absolute() else ROOT / p)
            if os.getenv("PRIVATE_KEY_PASSPHRASE"):
                params["private_key_file_pwd"] = os.environ["PRIVATE_KEY_PASSPHRASE"]
        else:
            params["password"] = os.environ["SNOWFLAKE_PASSWORD"]

        with sf.connect(**params) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_ACCOUNT(), "
                "CURRENT_VERSION(), CURRENT_REGION()"
            )
            user, role, account, version, region = cur.fetchone()
            print("\nconnection OK")
            print(f"  user      {user}")
            print(f"  role      {role}")
            print(f"  account   {account}")
            print(f"  region    {region}")
            print(f"  version   {version}")

            cur.execute(
                f"SHOW DATABASES LIKE '{os.environ['SNOWFLAKE_DATABASE']}'"
            )
            if cur.fetchall():
                print(f"  {os.environ['SNOWFLAKE_DATABASE']} already exists")
            else:
                print(f"  {os.environ['SNOWFLAKE_DATABASE']} does not exist yet (expected before setup)")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface the driver error verbatim
        print(f"\nconnection FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
