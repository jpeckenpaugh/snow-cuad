"""Every query the UI runs. Parameterised; no string-built user input."""
from __future__ import annotations

import db

ALL = "Any"
NOT_STATED = "Not stated"


def facet_types() -> list[tuple[str, int]]:
    return db.q("SELECT DOC_TYPE, DOC_COUNT FROM V_FACET_TYPE ORDER BY DOC_COUNT DESC, DOC_TYPE")


def facet_jurisdictions() -> list[tuple[str, int]]:
    return db.q(
        "SELECT JURISDICTION, DOC_COUNT FROM V_FACET_JURISDICTION "
        "ORDER BY DOC_COUNT DESC, JURISDICTION"
    )


def facet_decades() -> list[tuple[str, int]]:
    return db.q(
        """
        SELECT
          CASE
            WHEN AGREEMENT_YEAR IS NULL THEN 'Not stated'
            ELSE TO_CHAR(FLOOR(AGREEMENT_YEAR / 10) * 10) || 's'
          END AS DECADE,
          COUNT(*) AS DOC_COUNT
        FROM CONTRACT_DIM
        GROUP BY 1
        ORDER BY 1
        """
    )


def category_index() -> list[tuple]:
    return db.q(
        "SELECT CATEGORY, DOC_COUNT, SPAN_COUNT, GRP, DESCRIPTION FROM V_CATEGORY_INDEX "
        "ORDER BY DOC_COUNT DESC, CATEGORY"
    )


def type_index() -> list[tuple]:
    return db.q("SELECT DOC_TYPE, DOC_COUNT FROM V_FACET_TYPE ORDER BY DOC_COUNT DESC, DOC_TYPE")


def party_index(min_docs: int = 2) -> list[tuple]:
    return db.q(
        "SELECT PARTY_NAME, DOC_COUNT FROM V_FACET_PARTY WHERE DOC_COUNT >= %s "
        "ORDER BY DOC_COUNT DESC, PARTY_NAME",
        (min_docs,),
    )


def party_singletons() -> int:
    return db.q("SELECT COUNT(*) FROM V_FACET_PARTY WHERE DOC_COUNT < 2")[0][0]


def browse(
    *,
    clauses: list[str] | None = None,
    doc_type: str | None = None,
    jurisdiction: str | None = None,
    decade: str | None = None,
    party: str | None = None,
    term: str | None = None,
    limit: int = 600,
) -> list[tuple]:
    where = ["1=1"]
    params: list = []

    for category in clauses or []:
        where.append(
            "EXISTS (SELECT 1 FROM CLAUSES c WHERE c.DOC_ID = b.DOC_ID AND c.CATEGORY = %s)"
        )
        params.append(category)

    if doc_type:
        where.append("b.DOC_TYPE = %s")
        params.append(doc_type)

    if jurisdiction:
        where.append("b.JURISDICTION = %s")
        params.append(jurisdiction)

    if decade:
        if decade == NOT_STATED:
            where.append("b.AGREEMENT_YEAR IS NULL")
        else:
            where.append("b.AGREEMENT_YEAR >= %s AND b.AGREEMENT_YEAR < %s")
            start = int(decade.rstrip("s"))
            params += [start, start + 10]

    if party:
        where.append("EXISTS (SELECT 1 FROM CONTRACT_PARTY p WHERE p.DOC_ID = b.DOC_ID "
                     "AND p.PARTY_NAME ILIKE %s)")
        params.append(f"%{party}%")

    if term:
        where.append("(b.TITLE ILIKE %s OR b.PARTIES ILIKE %s)")
        params += [f"%{term}%", f"%{term}%"]

    sql = f"""
        SELECT b.DOC_ID, b.TITLE, b.DOC_TYPE, b.AGREEMENT_YEAR, b.JURISDICTION,
               b.PARTIES, b.CLAUSE_COUNT, b.CHAR_LEN
        FROM V_CONTRACT_BROWSE b
        WHERE {' AND '.join(where)}
        ORDER BY b.TITLE
        LIMIT {int(limit)}
    """
    return db.q(sql, tuple(params))


def document(doc_id: str) -> dict | None:
    rows = db.q(
        """
        SELECT DOC_ID, TITLE, CHAR_LEN, DOC_TYPE, AGREEMENT_YEAR, JURISDICTION,
               PARTIES, CLAUSE_COUNT
        FROM V_CONTRACT_BROWSE WHERE DOC_ID = %s
        """,
        (doc_id,),
    )
    if not rows:
        return None
    keys = ["doc_id", "title", "char_len", "doc_type", "agreement_year",
            "jurisdiction", "parties", "clause_count"]
    return dict(zip(keys, rows[0]))


def document_clauses(doc_id: str) -> list[tuple]:
    return db.q(
        "SELECT CATEGORY, ANSWER_TEXT, ANSWER_START, ANSWER_END, QUESTION "
        "FROM CLAUSES WHERE DOC_ID = %s ORDER BY ANSWER_START, ANSWER_END",
        (doc_id,),
    )


def document_category_status(doc_id: str) -> list[tuple]:
    return db.q(
        "SELECT CATEGORY, GRP, FOUND, SPAN_COUNT FROM V_CONTRACT_CATEGORY_STATUS "
        "WHERE DOC_ID = %s ORDER BY FOUND DESC, GRP, CATEGORY",
        (doc_id,),
    )


def document_text(doc_id: str) -> str:
    rows = db.q("SELECT FULL_TEXT FROM CONTRACT_TEXT WHERE DOC_ID = %s", (doc_id,))
    return rows[0][0] if rows else ""


def related(doc_id: str) -> list[tuple]:
    return db.q(
        "SELECT RELATED_DOC_ID, RELATED_TITLE, RELATED_TYPE, RELATED_YEAR, SCORE, REASONS "
        "FROM V_RELATED_DOC WHERE DOC_ID = %s ORDER BY RANK",
        (doc_id,),
    )


def clause_matches(term: str, categories: list[str] | None = None, limit: int = 60) -> list[tuple]:
    where = ["cl.ANSWER_TEXT ILIKE %s"]
    params: list = [f"%{term}%"]
    if categories:
        where.append("cl.CATEGORY IN (" + ",".join(["%s"] * len(categories)) + ")")
        params += categories
    return db.q(
        f"""
        SELECT cl.DOC_ID, c.TITLE, cl.CATEGORY, cl.ANSWER_TEXT
        FROM CLAUSES cl
        JOIN CONTRACTS c ON c.DOC_ID = cl.DOC_ID
        WHERE {' AND '.join(where)}
        ORDER BY c.TITLE, cl.ANSWER_START
        LIMIT {int(limit)}
        """,
        tuple(params),
    )
