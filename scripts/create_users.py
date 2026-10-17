#!/usr/bin/env python3
"""Create the three demo logins for the Streamlit app.

Generates a random password per user, stores only a salted PBKDF2-SHA256
hash in CUAD_DB.CORPUS.APP_USERS, and writes the plaintext once to
credentials.txt (gitignored, mode 600).

Idempotent: existing users are left alone unless --force rotates them.

Usage:
    python scripts/create_users.py [--force] [--iterations N]
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sf import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS = ROOT / "credentials.txt"

USERS = [
    ("lawyer-001", "Ada Whitfield"),
    ("lawyer-002", "Marcus Iyer"),
    ("lawyer-003", "Noor Castellanos"),
]

DEFAULT_ITERATIONS = 200_000
ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 16) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_password(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rotate passwords for existing users")
    ap.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    args = ap.parse_args()

    created: list[tuple[str, str, str]] = []
    kept: list[tuple[str, str]] = []

    with connect(warehouse="CUAD_WH", database="CUAD_DB", schema="CORPUS") as conn:
        cur = conn.cursor()
        cur.execute("SELECT USERNAME FROM APP_USERS")
        existing = {row[0] for row in cur.fetchall()}

        for username, display_name in USERS:
            if username in existing and not args.force:
                kept.append((username, display_name))
                continue

            password = generate_password()
            salt = secrets.token_bytes(16)
            digest = hash_password(password, salt, args.iterations)

            cur.execute(
                """
                MERGE INTO APP_USERS t
                USING (SELECT %s AS USERNAME, %s AS DISPLAY_NAME, %s AS SALT,
                              %s AS PWD_HASH, %s AS ITERATIONS) s
                ON t.USERNAME = s.USERNAME
                WHEN MATCHED THEN UPDATE SET
                  t.DISPLAY_NAME = s.DISPLAY_NAME,
                  t.SALT         = s.SALT,
                  t.PWD_HASH     = s.PWD_HASH,
                  t.ITERATIONS   = s.ITERATIONS,
                  t.CREATED_AT   = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT
                  (USERNAME, DISPLAY_NAME, SALT, PWD_HASH, ITERATIONS)
                  VALUES (s.USERNAME, s.DISPLAY_NAME, s.SALT, s.PWD_HASH, s.ITERATIONS)
                """,
                (username, display_name, salt.hex(), digest, args.iterations),
            )
            created.append((username, display_name, password))

        cur.execute("SELECT USERNAME, DISPLAY_NAME, CREATED_AT FROM APP_USERS ORDER BY USERNAME")
        rows = cur.fetchall()

    if created:
        lines = [
            "CUAD POC demo logins",
            f"generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            "",
            "Do not commit this file. Rotate with: FORCE=1 make users",
            "",
            f"{'username':<14} {'password':<20} name",
            "-" * 58,
        ]
        lines += [f"{u:<14} {p:<20} {n}" for u, n, p in created]
        if kept:
            lines += ["", "unchanged this run (password from an earlier file):"]
            lines += [f"  {u:<14} {n}" for u, n in kept]
        CREDENTIALS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        CREDENTIALS.chmod(0o600)

    print(f"APP_USERS now holds {len(rows)} login(s):")
    for username, display_name, created_at in rows:
        print(f"  {username:<14} {display_name:<18} created {created_at}")

    if created:
        print(f"\n{len(created)} password(s) written to {CREDENTIALS.relative_to(ROOT)} (mode 600)")
        for u, n, p in created:
            print(f"  {u:<14} {p}")
    else:
        print("\nno changes; existing passwords left in place")
    if kept:
        print(f"kept (use --force to rotate): {', '.join(u for u, _ in kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
