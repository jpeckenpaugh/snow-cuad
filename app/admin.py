"""Admin page: create users, suspend and reactivate, reset passwords.

Suspension is a status change, never a delete: ACCESS_LOG rows reference
usernames and have to keep resolving.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import streamlit as st

import audit
import db
from auth import current_user, require_role
from credentials import ROLES, USERNAME_HELP, USERNAME_RE, new_credential


def _users() -> list[tuple]:
    return db.q(
        """
        SELECT u.USERNAME, u.DISPLAY_NAME, u.APP_ROLE, u.STATUS, u.CREATED_AT,
               (SELECT MAX(l.EVENT_TS) FROM ACCESS_LOG l
                 WHERE l.ACTOR = u.USERNAME AND l.EVENT_TYPE = 'LOGIN_SUCCESS') AS LAST_LOGIN
        FROM APP_USERS u
        ORDER BY u.APP_ROLE, u.USERNAME
        """
    )


def _flash_new_password() -> None:
    """Show a generated password exactly once.

    It is never written anywhere: an admin UI that persists plaintext
    passwords is worse than one that shows them once.
    """
    pending = st.session_state.pop("new_password", None)
    if pending:
        st.success(f"Password for **{pending['username']}** — shown once, not stored.")
        st.code(pending["password"], language=None)


def _create_user(username: str, display_name: str, role: str) -> None:
    username = username.strip().lower()
    display_name = display_name.strip()

    if not re.fullmatch(USERNAME_RE, username):
        st.error(f"Invalid username. {USERNAME_HELP}.")
        return
    if not display_name:
        st.error("Display name is required.")
        return
    if db.q("SELECT 1 FROM APP_USERS WHERE USERNAME = %s", (username,)):
        st.error(f"`{username}` already exists.")
        return

    credential = new_credential()
    db.execute(
        "INSERT INTO APP_USERS "
        "(USERNAME, DISPLAY_NAME, APP_ROLE, STATUS, SALT, PWD_HASH, ITERATIONS) "
        "VALUES (%s, %s, %s, 'active', %s, %s, %s)",
        (username, display_name, role, credential["salt"], credential["digest"],
         credential["iterations"]),
    )
    audit.log("USER_CREATED", detail=f"{username} role={role}")
    st.session_state.new_password = {"username": username, "password": credential["password"]}
    st.rerun()


def _set_status(target: str, suspend: bool) -> None:
    if suspend:
        db.execute(
            "UPDATE APP_USERS SET STATUS = 'suspended', SUSPENDED_AT = CURRENT_TIMESTAMP(), "
            "SUSPENDED_BY = %s WHERE USERNAME = %s",
            (current_user()["username"], target),
        )
        audit.log("USER_SUSPENDED", detail=target)
    else:
        db.execute(
            "UPDATE APP_USERS SET STATUS = 'active', SUSPENDED_AT = NULL, SUSPENDED_BY = NULL "
            "WHERE USERNAME = %s",
            (target,),
        )
        audit.log("USER_REACTIVATED", detail=target)
    st.rerun()


def _reset_password(target: str) -> None:
    credential = new_credential()
    db.execute(
        "UPDATE APP_USERS SET SALT = %s, PWD_HASH = %s, ITERATIONS = %s WHERE USERNAME = %s",
        (credential["salt"], credential["digest"], credential["iterations"], target),
    )
    audit.log("PASSWORD_RESET", detail=target)
    st.session_state.new_password = {"username": target, "password": credential["password"]}
    st.rerun()


def page_admin() -> None:
    require_role("admin")
    me = current_user()["username"]

    st.subheader("Users")
    _flash_new_password()

    rows = _users()
    table = [
        {
            "Username": row[0],
            "Name": row[1],
            "Role": row[2],
            "Status": row[3],
            "Created (UTC)": str(row[4])[:19],
            "Last login (UTC)": str(row[5])[:19] if row[5] else "—",
        }
        for row in rows
    ]
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=250,
        column_config={
            "Username": st.column_config.TextColumn(width=110),
            "Name": st.column_config.TextColumn(width=150),
            "Role": st.column_config.TextColumn(width=80),
            "Status": st.column_config.TextColumn(width=90),
            "Created (UTC)": st.column_config.TextColumn(width=150),
            "Last login (UTC)": st.column_config.TextColumn(width=150),
        },
    )
    st.caption(
        "Suspended accounts keep their row and their audit history; only login is blocked."
    )

    st.markdown("#### Create user")
    with st.form("admin-create", clear_on_submit=True):
        col_user, col_name, col_role = st.columns([2, 2, 1])
        username = col_user.text_input("Username", placeholder="lawyer-004")
        display_name = col_name.text_input("Display name", placeholder="Jamie Okafor")
        role = col_role.selectbox("Role", ROLES)
        if st.form_submit_button("Create", type="primary"):
            _create_user(username, display_name, role)

    st.markdown("#### Manage")
    manageable = [row for row in rows if row[0] != me]
    if not manageable:
        st.caption("No other accounts to manage.")
        return

    labels = [f"{row[0]} · {row[1]} · {row[2]} · {row[3]}" for row in manageable]
    pick = st.selectbox("Account", range(len(labels)), format_func=lambda i: labels[i])
    target = manageable[pick]

    col_status, col_password = st.columns(2)
    if target[3] == "active":
        if col_status.button(f"Suspend {target[0]}", width="stretch"):
            _set_status(target[0], True)
    else:
        if col_status.button(f"Reactivate {target[0]}", type="primary", width="stretch"):
            _set_status(target[0], False)

    if col_password.button(f"Reset password for {target[0]}", width="stretch"):
        _reset_password(target[0])

    st.caption("You cannot suspend your own account.")
