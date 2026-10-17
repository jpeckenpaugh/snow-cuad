#!/usr/bin/env python3
"""Assert that the CUAD load landed completely and consistently.

Compares live counts against build/manifest.json, then checks referential
integrity and the metadata view. Exit code is non-zero on any failure, so
`make verify` is usable as a gate.

Usage: python scripts/verify_load.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sf import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "build" / "manifest.json"

TABLES = ["contracts", "contract_text", "clauses", "categories"]
TABLES_SQL = {
    "contracts": "SELECT COUNT(*) FROM CONTRACTS",
    "contract_text": "SELECT COUNT(*) FROM CONTRACT_TEXT",
    "clauses": "SELECT COUNT(*) FROM CLAUSES",
    "categories": "SELECT COUNT(*) FROM CLAUSE_CATEGORIES",
}

DIM_TABLES = ["contract_dim", "contract_party", "related_doc", "category_stats"]
DIM_SQL = {
    "contract_dim": "SELECT COUNT(*) FROM CONTRACT_DIM",
    "contract_party": "SELECT COUNT(*) FROM CONTRACT_PARTY",
    "related_doc": "SELECT COUNT(*) FROM RELATED_DOC",
    "category_stats": "SELECT COUNT(*) FROM CATEGORY_STATS",
}

CHECKS = [
    (
        "orphan clauses (doc_id not in CONTRACTS)",
        "SELECT COUNT(*) FROM CLAUSES c LEFT JOIN CONTRACTS t ON t.DOC_ID = c.DOC_ID "
        "WHERE t.DOC_ID IS NULL",
        0,
    ),
    (
        "orphan text rows",
        "SELECT COUNT(*) FROM CONTRACT_TEXT x LEFT JOIN CONTRACTS t ON t.DOC_ID = x.DOC_ID "
        "WHERE t.DOC_ID IS NULL",
        0,
    ),
    (
        "spans extending past end of contract",
        "SELECT COUNT(*) FROM CLAUSES c JOIN CONTRACTS t ON t.DOC_ID = c.DOC_ID "
        "WHERE c.ANSWER_END > t.CHAR_LEN",
        0,
    ),
    (
        "metadata view rows != contracts",
        "SELECT (SELECT COUNT(*) FROM V_CONTRACT_METADATA) "
        "- (SELECT COUNT(*) FROM CONTRACTS)",
        0,
    ),
    (
        "contracts with no clauses at all",
        "SELECT COUNT(*) FROM CONTRACTS t "
        "WHERE NOT EXISTS (SELECT 1 FROM CLAUSES c WHERE c.DOC_ID = t.DOC_ID)",
        0,
    ),
    (
        "clause categories never matched",
        "SELECT (SELECT COUNT(*) FROM CLAUSE_CATEGORIES cc "
        "WHERE NOT EXISTS (SELECT 1 FROM CLAUSES c WHERE c.CATEGORY = cc.CATEGORY))",
        0,
    ),
    # --- derived dimensions ---------------------------------------------------
    (
        "dimension rows not in CONTRACTS",
        "SELECT COUNT(*) FROM CONTRACT_DIM d LEFT JOIN CONTRACTS c ON c.DOC_ID = d.DOC_ID "
        "WHERE c.DOC_ID IS NULL",
        0,
    ),
    (
        "party rows not in CONTRACTS",
        "SELECT COUNT(*) FROM CONTRACT_PARTY p LEFT JOIN CONTRACTS c ON c.DOC_ID = p.DOC_ID "
        "WHERE c.DOC_ID IS NULL",
        0,
    ),
    (
        "related docs not in CONTRACTS",
        "SELECT COUNT(*) FROM RELATED_DOC r LEFT JOIN CONTRACTS c "
        "ON c.DOC_ID = r.RELATED_DOC_ID WHERE c.DOC_ID IS NULL",
        0,
    ),
    (
        "self-referencing related docs",
        "SELECT COUNT(*) FROM RELATED_DOC WHERE DOC_ID = RELATED_DOC_ID",
        0,
    ),
    (
        "category stats not covering all 41 categories",
        "SELECT (SELECT COUNT(*) FROM CLAUSE_CATEGORIES) - (SELECT COUNT(*) FROM CATEGORY_STATS)",
        0,
    ),
    (
        "category stats doc_count disagreeing with CLAUSES",
        "SELECT COUNT(*) FROM CATEGORY_STATS s WHERE s.DOC_COUNT <> "
        "(SELECT COUNT(DISTINCT c.DOC_ID) FROM CLAUSES c WHERE c.CATEGORY = s.CATEGORY)",
        0,
    ),
    (
        "browse view rows != contracts",
        "SELECT (SELECT COUNT(*) FROM V_CONTRACT_BROWSE) - (SELECT COUNT(*) FROM CONTRACTS)",
        0,
    ),
    (
        "facet year counts not summing to contracts",
        "SELECT (SELECT COUNT(*) FROM CONTRACTS) - (SELECT COALESCE(SUM(DOC_COUNT),0) FROM V_FACET_YEAR)",
        0,
    ),
    (
        "facet jurisdiction counts not summing to contracts",
        "SELECT (SELECT COUNT(*) FROM CONTRACTS) - "
        "(SELECT COALESCE(SUM(DOC_COUNT),0) FROM V_FACET_JURISDICTION)",
        0,
    ),
    (
        "more than 20 contracts with no related documents",
        "SELECT IFF((SELECT COUNT(*) FROM CONTRACTS c WHERE NOT EXISTS "
        "(SELECT 1 FROM RELATED_DOC r WHERE r.DOC_ID = c.DOC_ID)) <= 20, 0, 1)",
        0,
    ),
    # --- users, roles and audit ----------------------------------------------
    (
        "user roles outside the allowed set",
        "SELECT COUNT(*) FROM APP_USERS WHERE APP_ROLE NOT IN ('lawyer', 'auditor', 'admin')",
        0,
    ),
    (
        "user statuses outside the allowed set",
        "SELECT COUNT(*) FROM APP_USERS WHERE STATUS NOT IN ('active', 'suspended')",
        0,
    ),
    (
        "active admins != 1 (skipped while no users are seeded)",
        "SELECT IFF((SELECT COUNT(*) FROM APP_USERS) = 0, 0, "
        "IFF((SELECT COUNT(*) FROM APP_USERS WHERE APP_ROLE = 'admin' AND STATUS = 'active') = 1, 0, 1))",
        0,
    ),
    (
        "audit event types outside the known set",
        "SELECT COUNT(*) FROM ACCESS_LOG WHERE EVENT_TYPE NOT IN ("
        "'LOGIN_SUCCESS','LOGIN_FAILURE','LOGOUT','SESSION_REVOKED','SEARCH',"
        "'DOCUMENT_VIEW','REPORT_RUN','USER_CREATED','USER_SUSPENDED',"
        "'USER_REACTIVATED','PASSWORD_RESET')",
        0,
    ),
    (
        "suspended users without a suspension timestamp",
        "SELECT COUNT(*) FROM APP_USERS WHERE STATUS = 'suspended' AND SUSPENDED_AT IS NULL",
        0,
    ),
]


def main() -> int:
    dim_manifest = ROOT / "build" / "dimensions.json"
    for path in (MANIFEST, dim_manifest):
        if not path.exists():
            print(f"error: {path.relative_to(ROOT)} missing. Run `make build`.", file=sys.stderr)
            return 1

    expected = json.loads(MANIFEST.read_text())["counts"]
    dims = json.loads(dim_manifest.read_text())
    expected.update(dims["counts"])
    rates = dims["rates"]

    failures: list[str] = []
    rows: list[tuple[str, str, str, str]] = []

    with connect(warehouse="CUAD_WH", database=None, schema=None) as conn:
        cur = conn.cursor()
        cur.execute("USE DATABASE CUAD_DB")
        cur.execute("USE SCHEMA CORPUS")
        cur.execute("USE WAREHOUSE CUAD_WH")

        for name in TABLES + DIM_TABLES:
            cur.execute((TABLES_SQL | DIM_SQL)[name])
            actual = cur.fetchone()[0]
            want = expected[name]
            ok = actual == want
            if not ok:
                failures.append(f"{name}: expected {want}, got {actual}")
            rows.append((f"count {name}", str(want), str(actual), "PASS" if ok else "FAIL"))

        for label, sql, want in CHECKS:
            cur.execute(sql)
            actual = cur.fetchone()[0]
            ok = actual == want
            if not ok:
                failures.append(f"{label}: expected {want}, got {actual}")
            rows.append((label, str(want), str(actual), "PASS" if ok else "FAIL"))

        cur.execute(
            "SELECT COUNT(DISTINCT DOC_ID) FROM CLAUSES"
        )
        docs_with_clauses = cur.fetchone()[0]
        rows.append(("distinct contracts with clauses", "510", str(docs_with_clauses),
                     "PASS" if docs_with_clauses == 510 else "FAIL"))
        if docs_with_clauses != 510:
            failures.append(f"distinct contracts with clauses: expected 510, got {docs_with_clauses}")

        cur.execute("SELECT COUNT(*) FROM APP_USERS")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ACCESS_LOG")
        audit_count = cur.fetchone()[0]

    width_a = max(len(r[0]) for r in rows) + 2
    print(f"{'check':<{width_a}} {'want':>8} {'got':>8}  result")
    print("-" * (width_a + 28))
    for label, want, got, result in rows:
        print(f"{label:<{width_a}} {want:>8} {got:>8}  {result}")

    if failures:
        print("\nFAILED", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    total = rates["documents"]
    print(f"\nusers seeded: {user_count} · audit events recorded: {audit_count}")
    print("parse rates (build-time, informational)")
    for label, key in (
        ("type classified", "type_classified"),
        ("year parsed", "year_parsed"),
        ("jurisdiction parsed", "jurisdiction_parsed"),
    ):
        print(f"  {label:<22} {rates[key]:>4}/{total} ({rates[key] * 100 // total}%)")

    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
