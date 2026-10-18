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

import html

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


_USERS_CSS = """
<style>
table.users { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
table.users th, table.users td {
  text-align: left; padding: 6px 10px;
  border-bottom: 1px solid rgba(128,128,128,0.25);
}
table.users th { font-weight: 600; color: rgba(128,128,128,1); }
table.users td { vertical-align: top; }
</style>
"""


def _users_table(rows: list[tuple]) -> None:
    """The user list as a plain HTML table.

    It was an `st.dataframe` canvas grid. Canvas grids have a minimum width
    that cannot shrink, so the Last login column fell off the right edge in a
    narrow window; the cell text was also unselectable and absent from the
    accessibility tree until focused. Six rows need none of that: a real table
    wraps and stays readable at any width. See docs/fixes.md.
    """
    columns = ("Username", "Name", "Role", "Status", "Created (UTC)", "Last login (UTC)")
    head = "".join(f"<th>{html.escape(name)}</th>" for name in columns)
    body = []
    for row in rows:
        cells = [
            row[0], row[1], row[2], row[3],
            str(row[4])[:19],
            str(row[5])[:19] if row[5] else "—",
        ]
        body.append(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells) + "</tr>"
        )
    st.html(_USERS_CSS)
    st.html(
        f"<table class='users'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
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
    require_role("admin", page="admin")
    me = current_user()["username"]

    st.subheader("Users")
    _flash_new_password()

    rows = _users()
    _users_table(rows)
    st.caption(
        "Times are UTC. Suspended accounts keep their row and their audit history; "
        "only login is blocked."
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

    # One row of actions per account, rather than "pick one from a dropdown,
    # then click one button". The picker was the problem: any action reruns the
    # script, and the selectbox could come back on a different account, so the
    # next click landed on the wrong user. Per-row buttons cannot drift, and
    # they remove the re-selection cost the reviewers complained about.
    for username, name, role, status, _created, _last_login in manageable:
        row = st.columns([4, 1, 1.4], vertical_alignment="center")
        row[0].html(
            f"<b>{html.escape(username)}</b> &nbsp; "
            f'<span class="small">{html.escape(name)} · {html.escape(role)} · '
            f"{html.escape(status)}</span>"
        )
        if status == "active":
            if row[1].button("Suspend", key=f"admin-suspend-{username}", width="stretch"):
                _set_status(username, True)
        else:
            if row[1].button("Reactivate", key=f"admin-reactivate-{username}",
                             type="primary", width="stretch"):
                _set_status(username, False)
        if row[2].button("Reset password", key=f"admin-reset-{username}", width="stretch"):
            _reset_password(username)

    st.caption("You cannot suspend your own account.")
