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
]


def main() -> int:
    if not MANIFEST.exists():
        print(f"error: {MANIFEST} missing. Run `make build`.", file=sys.stderr)
        return 1

    expected = json.loads(MANIFEST.read_text())["counts"]

    failures: list[str] = []
    rows: list[tuple[str, str, str, str]] = []

    with connect(warehouse="CUAD_WH", database=None, schema=None) as conn:
        cur = conn.cursor()
        cur.execute("USE DATABASE CUAD_DB")
        cur.execute("USE SCHEMA CORPUS")
        cur.execute("USE WAREHOUSE CUAD_WH")

        for name in TABLES:
            cur.execute(TABLES_SQL[name])
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

    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
