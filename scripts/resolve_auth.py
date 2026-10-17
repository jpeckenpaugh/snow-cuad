#!/usr/bin/env python3
"""Decide which credential the `snow` CLI should use, and say so in shell.

The Python connector (scripts/sf.py) tries key-pair then password on its own.
The Snowflake CLI cannot: given a private key path and no authenticator it
refuses with "Private Key authentication requires authenticator set to
SNOWFLAKE_JWT", and given both it will not fall back either.

So the Makefile asks this script once per `snow` invocation, and exports
exactly the credential that works. Prints shell assignments to stdout:

    unset SNOWFLAKE_PASSWORD; export SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT

Usage:
    eval "$(python scripts/resolve_auth.py)"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

from sf import attempts  # noqa: E402


def emit(*lines: str) -> None:
    print("; ".join(lines))


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)

    candidates = attempts()
    if not candidates:
        print(
            "echo 'no credentials in .env: set SNOWFLAKE_PASSWORD and/or "
            "SNOWFLAKE_PRIVATE_KEY_PATH' >&2; false"
        )
        return 0

    import snowflake.connector as sf

    failures = []
    for label, extra in candidates:
        params = {
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "role": os.getenv("SNOWFLAKE_ROLE") or None,
            "login_timeout": 15,
        }
        params.update(extra)
        try:
            sf.connect(**params).close()
        except Exception as exc:  # noqa: BLE001 - try the next credential
            failures.append(f"{label}: {str(exc).splitlines()[0][:90]}")
            continue

        if failures:
            print(
                f"note: snow CLI using {label} auth "
                f"({failures[0].split(':')[0]} unavailable)",
                file=sys.stderr,
            )
        if label == "key-pair":
            emit("unset SNOWFLAKE_PASSWORD", "export SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT")
        else:
            emit("unset SNOWFLAKE_PRIVATE_KEY_PATH", "export SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE")
        return 0

    joined = "; ".join(failures).replace("'", "")
    print(f"echo 'could not authenticate with any .env credential: {joined}' >&2; false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
