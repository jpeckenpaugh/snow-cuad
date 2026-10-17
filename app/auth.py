"""Authentication and authorisation.

Credentials are app-level: the PBKDF2 hash lives in APP_USERS and the app
connects to Snowflake as one service role. See sql/04_users.sql.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import streamlit as st

import audit
import db
from credentials import verify_password


def current_user() -> dict:
    return st.session_state.get("user") or {}


def check_login(username: str, password: str) -> dict | None:
    """Verify credentials, log the attempt, and return the session user.

    Password is checked before status so a suspended account with the wrong
    password is recorded as a bad password, not as a suspension probe.
    """
    try:
        rows = db.q(
            "SELECT DISPLAY_NAME, SALT, PWD_HASH, ITERATIONS, APP_ROLE, STATUS "
            "FROM APP_USERS WHERE USERNAME = %s",
            (username,),
        )
    except RuntimeError:
        return None

    if not rows:
        audit.log_login_failure(username, "no such user")
        return None

    display_name, salt_hex, digest_hex, iterations, role, status = rows[0]

    if not verify_password(password, salt_hex, digest_hex, iterations):
        audit.log_login_failure(username, "bad password", role=role)
        return None

    if status != "active":
        audit.log_login_failure(username, "account suspended", role=role)
        return None

    audit.log("LOGIN_SUCCESS", actor=username, role=role)
    return {"username": username, "display_name": display_name, "role": role}


def require_role(*allowed: str) -> None:
    """Backstop for direct URL access; the sidebar already hides other pages."""
    if current_user().get("role") not in allowed:
        st.error("Not authorised for this page.")
        st.stop()
