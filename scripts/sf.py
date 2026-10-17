"""Shared Snowflake connection helper (reads .env, no config.toml)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def connect(**overrides):
    """Open a connection using values from .env.

    Any keyword override (database, schema, warehouse, role) wins over .env.
    """
    load_dotenv(ROOT / ".env", override=True)

    authenticator = os.getenv("SNOWFLAKE_AUTHENTICATOR", "SNOWFLAKE")
    params: dict = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "role": os.getenv("SNOWFLAKE_ROLE"),
        "authenticator": authenticator,
        "login_timeout": 20,
        "client_session_keep_alive": False,
    }

    for key in ("database", "schema", "warehouse"):
        env_key = f"SNOWFLAKE_{key.upper()}"
        value = os.getenv(env_key)
        if value:
            params[key] = value

    if authenticator == "SNOWFLAKE_JWT":
        key_path = Path(os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")).expanduser()
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        params["private_key_file"] = str(key_path)
        if os.getenv("PRIVATE_KEY_PASSPHRASE"):
            params["private_key_file_pwd"] = os.environ["PRIVATE_KEY_PASSPHRASE"]
    elif authenticator in ("SNOWFLAKE", "USERNAME_PASSWORD_MFA"):
        params["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    else:
        raise SystemExit(f"unsupported SNOWFLAKE_AUTHENTICATOR={authenticator!r}")

    params = {k: v for k, v in params.items() if v is not None}
    params.update({k: v for k, v in overrides.items() if v is not None})
    params = {k: v for k, v in params.items() if v is not None}

    import snowflake.connector as sf

    return sf.connect(**params)
