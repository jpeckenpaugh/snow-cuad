"""Access audit logging.

Every event goes to CUAD_DB.CORPUS.ACCESS_LOG through one function, called
from exactly three chokepoints:

  * check_login() / logout        -> LOGIN_*, LOGOUT, SESSION_REVOKED
  * nav() / the search form       -> SEARCH
  * page_document() / reports     -> DOCUMENT_VIEW, REPORT_RUN
  * app/admin.py                  -> USER_CREATED, USER_SUSPENDED, ...

Logging must never take the app down, so failures are reported to stderr and
swallowed. The alternative is an audit table that can break a login.
"""
from __future__ import annotations

import sys
import uuid

import streamlit as st

import db

MAX_DETAIL = 1000
MAX_USERNAME = 64

EVENT_TYPES = (
    "LOGIN_SUCCESS",
    "LOGIN_FAILURE",
    "LOGOUT",
    "SESSION_REVOKED",
    "SEARCH",
    "DOCUMENT_VIEW",
    "REPORT_RUN",
    "USER_CREATED",
    "USER_SUSPENDED",
    "USER_REACTIVATED",
    "PASSWORD_RESET",
)


def session_id() -> str:
    """Stable per browser session, so events can be grouped."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def log(
    event_type: str,
    *,
    actor: str | None = None,
    role: str | None = None,
    doc_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Append one event. Unknown event types are still recorded."""
    user = st.session_state.get("user") or {}
    if actor is None:
        actor = user.get("username")
    if role is None:
        role = user.get("role")
    if detail is not None:
        detail = detail[:MAX_DETAIL]

    try:
        db.execute(
            "INSERT INTO ACCESS_LOG (EVENT_TYPE, ACTOR, ACTOR_ROLE, SESSION_ID, DOC_ID, DETAIL) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (event_type, actor, role, session_id(), doc_id, detail),
        )
    except Exception as exc:  # noqa: BLE001 - never break the app for audit
        print(f"audit write failed ({event_type}): {exc}", file=sys.stderr)


def log_login_failure(attempted_username: str, reason: str, role: str | None = None) -> None:
    """Record a failed attempt.

    The attempted username is stored verbatim but truncated: it is useful
    forensics (typos, brute-force patterns, someone else's login), and the
    password is never recorded.
    """
    log(
        "LOGIN_FAILURE",
        actor=(attempted_username or "")[:MAX_USERNAME],
        role=role,
        detail=reason,
    )
