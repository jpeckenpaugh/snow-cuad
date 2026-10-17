#!/usr/bin/env python3
"""Prove the service identity is least-privilege, rather than claiming it.

Connects as STREAMLITWEB (layers 2 of 3) using .env.service and asserts:
  * what the app needs, works
  * what the app must never do, is denied

A denial that succeeds is a failure. Exit code is non-zero if any check
fails, so `make verify-privileges` is usable as a gate.

Usage:
    python scripts/verify_privileges.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from sf import connect  # noqa: E402

SERVICE_ENV = ".env.service"
USER = "STREAMLITWEB"
ROLE = "STREAMLITWEB_ROLE"

# (label, statement) that must succeed
ALLOWED = [
    ("read CONTRACTS", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CONTRACTS"),
    ("read CONTRACT_TEXT", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CONTRACT_TEXT"),
    ("read CLAUSES", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CLAUSES"),
    ("read CLAUSE_CATEGORIES", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CLAUSE_CATEGORIES"),
    ("read CONTRACT_DIM", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CONTRACT_DIM"),
    ("read CONTRACT_PARTY", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.CONTRACT_PARTY"),
    ("read APP_USERS", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.APP_USERS"),
    ("read ACCESS_LOG", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.ACCESS_LOG"),
    ("read V_CONTRACT_BROWSE", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_CONTRACT_BROWSE"),
    ("read V_CONTRACT_CATEGORY_STATUS", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_CONTRACT_CATEGORY_STATUS"),
    ("read V_CATEGORY_INDEX", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_CATEGORY_INDEX"),
    ("read V_FACET_TYPE", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_FACET_TYPE"),
    ("read V_FACET_JURISDICTION", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_FACET_JURISDICTION"),
    ("read V_FACET_PARTY", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_FACET_PARTY"),
    ("read V_RELATED_DOC", "SELECT COUNT(*) FROM CUAD_DB.CORPUS.V_RELATED_DOC"),
    ("update an app user", "UPDATE CUAD_DB.CORPUS.APP_USERS SET STATUS = 'active' WHERE USERNAME = 'nobody'"),
]

# (label, statement) that must be denied
DENIED = [
    ("drop a corpus table", "DROP TABLE CUAD_DB.CORPUS.CONTRACTS"),
    ("truncate a corpus table", "TRUNCATE TABLE CUAD_DB.CORPUS.CLAUSES"),
    ("insert a fake contract", "INSERT INTO CUAD_DB.CORPUS.CONTRACTS (DOC_ID) VALUES ('x')"),
    ("update a clause", "UPDATE CUAD_DB.CORPUS.CLAUSES SET CATEGORY = 'x'"),
    ("delete an app user", "DELETE FROM CUAD_DB.CORPUS.APP_USERS"),
    ("rewrite an audit row", "UPDATE CUAD_DB.CORPUS.ACCESS_LOG SET DETAIL = 'tampered'"),
    ("delete an audit row", "DELETE FROM CUAD_DB.CORPUS.ACCESS_LOG"),
    ("create a table", "CREATE TABLE CUAD_DB.CORPUS.PRIV_PROBE (X NUMBER)"),
    ("read account usage", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.USERS"),
    ("create a role", "CREATE ROLE PRIV_PROBE"),
]


def main() -> int:
    if not (ROOT / SERVICE_ENV).exists():
        print(f"error: {SERVICE_ENV} missing. Run `make service-user` first.", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str]] = []
    failures: list[str] = []

    with connect(env_file=SERVICE_ENV, database="CUAD_DB", schema="CORPUS") as conn:
        cur = conn.cursor()

        cur.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
        current_user, current_role = cur.fetchone()
        identity_ok = current_user == USER and current_role == ROLE
        rows.append((
            f"identity is {USER} as {ROLE}",
            f"{USER} / {ROLE}",
            f"{current_user} / {current_role}",
            "PASS" if identity_ok else "FAIL",
        ))
        if not identity_ok:
            failures.append(f"identity: expected {USER}/{ROLE}, got {current_user}/{current_role}")

        for label, statement in ALLOWED:
            try:
                cur.execute(statement)
                rows.append((label, "allowed", "allowed", "PASS"))
            except Exception as exc:  # noqa: BLE001
                rows.append((label, "allowed", "DENIED", "FAIL"))
                failures.append(f"{label}: was denied ({str(exc)[:80]})")

        for label, statement in DENIED:
            try:
                cur.execute(statement)
                rows.append((label, "denied", "ALLOWED", "FAIL"))
                failures.append(f"{label}: SUCCEEDED, should have been denied")
            except Exception:  # noqa: BLE001
                rows.append((label, "denied", "denied", "PASS"))

    # The one write the app performs, proved without polluting the audit log:
    # insert inside a transaction and roll it back.
    try:
        with connect(env_file=SERVICE_ENV, database="CUAD_DB", schema="CORPUS",
                     autocommit=False) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO ACCESS_LOG (EVENT_TYPE, ACTOR, DETAIL) "
                "VALUES ('PRIVILEGE_CHECK', %s, 'rolled back')",
                (USER,),
            )
            conn.rollback()
        rows.append(("insert into ACCESS_LOG", "allowed", "allowed (rolled back)", "PASS"))
    except Exception as exc:  # noqa: BLE001
        rows.append(("insert into ACCESS_LOG", "allowed", "DENIED", "FAIL"))
        failures.append(f"insert into ACCESS_LOG: was denied ({str(exc)[:80]})")

    width = max(len(row[0]) for row in rows) + 2
    print(f"{'check':<{width}} {'expect':>9} {'actual':>22}  result")
    print("-" * (width + 44))
    for label, expect, actual, result in rows:
        print(f"{label:<{width}} {expect:>9} {actual:>22}  {result}")

    if failures:
        print("\nFAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\nservice identity is least-privilege")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
