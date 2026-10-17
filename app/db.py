"""Snowflake access for the Streamlit app.

One cached connection, opened with the credentials in .env, plus a small
query helper. Queries are parameterised; nothing is string-concatenated
from user input.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from sf import connect  # noqa: E402


@st.cache_resource(show_spinner=False)
def _connection():
    return connect(warehouse="CUAD_WH", database="CUAD_DB", schema="CORPUS")


def q(sql: str, params: tuple = ()) -> list[tuple]:
    """Run a query and return rows. Reconnects once if the session dropped."""
    last: Exception | None = None
    for attempt in (0, 1):
        try:
            cur = _connection().cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []
            finally:
                cur.close()
        except Exception as exc:  # noqa: BLE001 - retry once, then surface
            last = exc
            _connection.clear()
    raise RuntimeError(f"query failed: {last}") from last


def execute(sql: str, params: tuple = ()) -> int:
    """Run a DML statement and return the affected row count.

    The connector autocommits, so no explicit commit is needed.
    """
    last: Exception | None = None
    for attempt in (0, 1):
        try:
            cur = _connection().cursor()
            try:
                cur.execute(sql, params)
                return cur.rowcount
            finally:
                cur.close()
        except Exception as exc:  # noqa: BLE001 - retry once, then surface
            last = exc
            _connection.clear()
    raise RuntimeError(f"statement failed: {last}") from last


@st.cache_data(show_spinner=False)
def categories() -> list[str]:
    return [row[0] for row in q("SELECT CATEGORY FROM CLAUSE_CATEGORIES ORDER BY CATEGORY")]
