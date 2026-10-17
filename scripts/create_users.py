#!/usr/bin/env python3
"""Seed the demo logins: three lawyers, one administrator, one auditor.

Generates a random password per new user, stores only a salted PBKDF2-SHA256
hash in CUAD_DB.CORPUS.APP_USERS, and writes the plaintext once to
credentials.txt (gitignored, mode 600).

Idempotent: existing users are left completely alone unless --force rotates
them. In particular ROLE and STATUS are only set on insert, so a re-run never
clobbers a role change or a suspension made through the admin UI.

Usage:
    python scripts/create_users.py [--force] [--iterations N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from credentials import DEFAULT_ITERATIONS, ROLES, new_credential  # noqa: E402
from sf import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS = ROOT / "credentials.txt"

USERS = [
    ("lawyer-001", "Ada Whitfield", "lawyer"),
    ("lawyer-002", "Marcus Iyer", "lawyer"),
    ("lawyer-003", "Noor Castellanos", "lawyer"),
    ("admin", "Sasha Lindqvist", "admin"),
    ("auditor", "Tomas Beck", "auditor"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rotate passwords for existing users")
    ap.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    args = ap.parse_args()

    created: list[tuple[str, str, str, str]] = []
    kept: list[tuple[str, str, str]] = []

    with connect(warehouse="CUAD_WH", database="CUAD_DB", schema="CORPUS") as conn:
        cur = conn.cursor()
        cur.execute("SELECT USERNAME FROM APP_USERS")
        existing = {row[0] for row in cur.fetchall()}

        for username, display_name, role in USERS:
            if username in existing and not args.force:
                kept.append((username, display_name, role))
                continue

            credential = new_credential(iterations=args.iterations)

            # ROLE and STATUS are set on insert only: re-running must not undo
            # a role change or a suspension made in the admin UI.
            cur.execute(
                """
                MERGE INTO APP_USERS t
                USING (SELECT %s AS USERNAME, %s AS DISPLAY_NAME, %s AS APP_ROLE,
                              %s AS SALT, %s AS PWD_HASH, %s AS ITERATIONS) s
                ON t.USERNAME = s.USERNAME
                WHEN MATCHED THEN UPDATE SET
                  t.DISPLAY_NAME = s.DISPLAY_NAME,
                  t.SALT         = s.SALT,
                  t.PWD_HASH     = s.PWD_HASH,
                  t.ITERATIONS   = s.ITERATIONS
                WHEN NOT MATCHED THEN INSERT
                  (USERNAME, DISPLAY_NAME, APP_ROLE, STATUS, SALT, PWD_HASH, ITERATIONS)
                  VALUES (s.USERNAME, s.DISPLAY_NAME, s.APP_ROLE, 'active',
                          s.SALT, s.PWD_HASH, s.ITERATIONS)
                """,
                (
                    username,
                    display_name,
                    role,
                    credential["salt"],
                    credential["digest"],
                    credential["iterations"],
                ),
            )
            created.append((username, display_name, role, credential["password"]))

        cur.execute(
            "SELECT USERNAME, DISPLAY_NAME, APP_ROLE, STATUS, CREATED_AT "
            "FROM APP_USERS ORDER BY APP_ROLE, USERNAME"
        )
        rows = cur.fetchall()

    if created:
        lines = [
            "CUAD POC demo logins",
            f"generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            "",
            "Do not commit this file. Rotate with: FORCE=1 make users",
            "",
            f"{'username':<14} {'role':<9} {'password':<20} name",
            "-" * 68,
        ]
        lines += [f"{u:<14} {r:<9} {p:<20} {n}" for u, n, r, p in created]
        if kept:
            lines += ["", "unchanged this run (password from an earlier file):"]
            lines += [f"  {u:<14} {r:<9} {n}" for u, n, r in kept]
        CREDENTIALS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        CREDENTIALS.chmod(0o600)

    print(f"APP_USERS now holds {len(rows)} login(s):")
    print(f"  {'username':<14} {'role':<9} {'status':<10} {'created':<20} name")
    for username, display_name, role, status, created_at in rows:
        print(f"  {username:<14} {role:<9} {status:<10} {str(created_at):<20} {display_name}")

    if created:
        print(f"\n{len(created)} password(s) written to {CREDENTIALS.relative_to(ROOT)} (mode 600)")
        for username, _name, role, password in created:
            print(f"  {username:<14} {role:<9} {password}")
    else:
        print("\nno new users; existing passwords left in place")
    if kept:
        print(f"kept (use --force to rotate): {', '.join(u for u, _, _ in kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
