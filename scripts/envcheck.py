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

    # Either or: a key pair, a password, or both. Both is the intended state.
    key_setting = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    key_path = None
    if key_setting:
        key_path = Path(key_setting).expanduser()
        if not key_path.is_absolute():
            key_path = ROOT / key_path

    key_usable = bool(key_path and key_path.exists())
    password_set = bool(os.getenv("SNOWFLAKE_PASSWORD"))

    if not key_usable and not password_set:
        errors.append(
            "no usable credentials: set SNOWFLAKE_PASSWORD and/or "
            "SNOWFLAKE_PRIVATE_KEY_PATH (run `make keypair`)"
        )
    if key_setting and not key_usable:
        print(f"  note: {key_path} not found; the password will be used", file=sys.stderr)

    print("\nconfiguration")
    for key in [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
        "SNOWFLAKE_PRIVATE_KEY_PATH",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_AUTHENTICATOR",
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
        sys.path.insert(0, str(ROOT / "scripts"))
        from sf import connect as sf_connect

        with sf_connect() as conn:
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
