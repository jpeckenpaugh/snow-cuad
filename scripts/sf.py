"""Shared Snowflake connection helper (reads an env file, no config.toml).

Authentication is "either or": a password and a key pair can both be present,
both stay valid in Snowflake, and this helper tries key-pair first and falls
back to the password. Nothing is ever swapped out, so an unregistered or
rotated key degrades to a slower login instead of a lockout.

SNOWFLAKE_AUTHENTICATOR is optional and only expresses a preference for which
is tried first. It is not a filter: if it names a method whose credentials are
missing or broken, the other one is still attempted.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Used when neither the env file nor an override names a warehouse.
FALLBACK_WAREHOUSE = "CUAD_WH"


def _key_attempt() -> tuple[str, dict] | None:
    configured = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if not configured:
        return None
    key_path = Path(configured).expanduser()
    if not key_path.is_absolute():
        key_path = ROOT / key_path
    if not key_path.exists():
        print(f"note: {key_path} not found; skipping key-pair auth", file=sys.stderr)
        return None

    attempt = {"authenticator": "SNOWFLAKE_JWT", "private_key_file": str(key_path)}
    if os.getenv("PRIVATE_KEY_PASSPHRASE"):
        attempt["private_key_file_pwd"] = os.environ["PRIVATE_KEY_PASSPHRASE"]
    return "key-pair", attempt


def _password_attempt() -> tuple[str, dict] | None:
    password = os.getenv("SNOWFLAKE_PASSWORD")
    if not password:
        return None
    return "password", {"authenticator": "SNOWFLAKE", "password": password}


def attempts() -> list[tuple[str, dict]]:
    """Every usable credential, preferred method first."""
    found = [a for a in (_key_attempt(), _password_attempt()) if a]
    preference = os.getenv("SNOWFLAKE_AUTHENTICATOR", "").upper()
    if preference in ("SNOWFLAKE", "USERNAME_PASSWORD_MFA"):
        found.sort(key=lambda a: a[0] != "password")
    return found


def connect(env_file: str = ".env", **overrides):
    """Open a connection using values from env_file (default .env).

    Any keyword override (database, schema, warehouse, role, autocommit) wins
    over the env file. Pass env_file=".env.service" to connect as the
    least-privilege STREAMLITWEB service identity.
    """
    load_dotenv(ROOT / env_file, override=True)

    base: dict = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "login_timeout": 15,
        "client_session_keep_alive": False,
        # Pin the session to UTC so CREATED_AT and ACCESS_LOG.EVENT_TS are
        # comparable with UTC cutoffs, instead of inheriting the account's
        # default session timezone.
        "session_parameters": {"TIMEZONE": "UTC"},
    }
    for key in ("database", "schema", "warehouse"):
        value = os.getenv(f"SNOWFLAKE_{key.upper()}")
        if value:
            base[key] = value

    candidates = attempts()
    if not candidates:
        raise RuntimeError(
            f"no credentials in {env_file}: set SNOWFLAKE_PASSWORD and/or "
            "SNOWFLAKE_PRIVATE_KEY_PATH"
        )

    import snowflake.connector as sf

    failures: list[str] = []
    for label, extra in candidates:
        params = {k: v for k, v in base.items() if v is not None}
        params.update(extra)
        params.update({k: v for k, v in overrides.items() if v is not None})
        if not params.get("warehouse"):
            params["warehouse"] = FALLBACK_WAREHOUSE
        try:
            connection = sf.connect(**params)
        except Exception as exc:  # noqa: BLE001 - try the next credential
            failures.append(f"{label}: {str(exc).splitlines()[0][:110]}")
            continue
        if failures:
            # Surface the fallback: a silently-degraded credential means you
            # never find out your key is broken.
            print(
                f"warning: fell back to {label} auth ({failures[0]})",
                file=sys.stderr,
            )
        return connection

    raise RuntimeError(f"could not connect using {env_file} ({'; '.join(failures)})")
