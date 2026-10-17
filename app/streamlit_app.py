"""CUAD POC: browse the corpus by clause, type, jurisdiction and counterparty.

Run with: make app

Navigation lives in the URL. Index pages all drill into one filtered register,
and every contract has a detail page with related documents. Role decides
which pages exist for you:

  lawyer   Contracts / Clauses / Types / Parties
  auditor  Reports
  admin    everything

`rev` in the query string is a counter bumped on real navigation: facet
widgets key off it so they re-initialise from the URL when you arrive from an
index page, but keep their state while you are using them.

Raw HTML is emitted with st.html, never st.markdown: contract text contains
blank lines, and those terminate Markdown's HTML block, which would dump the
rest of the snippet as literal tags.

Audit writes happen at three chokepoints only — auth.check_login and logout,
the search form, and page_document/reports. See app/audit.py.
"""
from __future__ import annotations

import html
import re

import streamlit as st

import admin
import audit
import auth
import db
import queries
import reports

st.set_page_config(page_title="CUAD Corpus", page_icon="§", layout="wide")

MAX_RENDER = 200_000
CONTEXT = 260
ANY = "Any"

CSS = """
<style>
.doc {
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  line-height: 1.55;
  max-height: 65vh;
  overflow-y: auto;
  border: 1px solid rgba(128,128,128,0.35);
  border-radius: 6px;
  padding: 0.9rem 1rem;
}
.doc .clause { background: rgba(255, 196, 0, 0.35); border-bottom: 1px solid rgba(255,196,0,0.9); }
.doc .term   { background: rgba(0, 200, 120, 0.35); font-weight: 600; }
.snippet { font-size: 0.84rem; line-height: 1.5; }
.snippet .clause { background: rgba(255, 196, 0, 0.35); }
.snippet .term   { background: rgba(0, 200, 120, 0.35); font-weight: 600; }
.chip {
  display: inline-block; padding: 2px 8px; margin: 2px 4px 2px 0;
  border-radius: 10px; background: rgba(128,128,128,0.16);
  font-size: 0.72rem; color: inherit;
}
.small { color: rgba(128,128,128,1); font-size: 0.75rem; }
</style>
"""


# --- URL state ---------------------------------------------------------------

def param(name: str, default: str | None = None) -> str | None:
    value = st.query_params.get(name)
    return value if value not in (None, "") else default


def param_list(name: str) -> list[str]:
    raw = st.query_params.get(name)
    return [part for part in raw.split(",") if part] if raw else []


def rev() -> str:
    return st.query_params.get("rev") or "0"


def _write(current: dict) -> None:
    st.query_params.clear()
    for key, value in current.items():
        if value not in (None, ""):
            st.query_params[key] = value


def _apply(current: dict, changes: dict) -> None:
    for key, value in changes.items():
        if value in (None, "", []):
            current.pop(key, None)
        else:
            current[key] = value


def nav(**changes) -> None:
    """Real navigation: apply changes and bump rev so facet widgets re-init."""
    current = dict(st.query_params)
    _apply(current, changes)
    current["rev"] = str(int(current.get("rev", "0")) + 1)
    _write(current)
    st.rerun()


def nav_soft(**changes) -> None:
    """Facet change from a widget: update the URL without resetting widgets."""
    current = dict(st.query_params)
    _apply(current, changes)
    _write(current)


# --- rendering helpers -------------------------------------------------------

def highlight(text: str, term: str | None) -> str:
    if not term:
        return html.escape(text)
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    out, last = [], 0
    for match in pattern.finditer(text):
        out.append(html.escape(text[last:match.start()]))
        out.append(f"<mark>{html.escape(match.group(0))}</mark>")
        last = match.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def annotate(text: str, spans: list[tuple[int, int]], term: str | None) -> str:
    marks: list[tuple[int, int, str]] = [
        (s, e, "clause") for s, e in spans if 0 <= s < e <= len(text)
    ]
    if term:
        marks += [
            (m.start(), m.end(), "term")
            for m in re.finditer(re.escape(term), text, re.IGNORECASE)
        ]
    marks.sort(key=lambda m: (m[0], m[1]))
    out, pos = [], 0
    for start, end, kind in marks:
        if start < pos:
            continue
        out.append(html.escape(text[pos:start]))
        out.append(f'<span class="{kind}">{html.escape(text[start:end])}</span>')
        pos = end
    out.append(html.escape(text[pos:]))
    return "".join(out)


def chips(labels: list[str]) -> None:
    if labels:
        st.html(
            "".join(f'<span class="chip">{html.escape(str(label))}</span>' for label in labels)
        )


def small_line(label: str, value: str) -> str:
    return f'<span class="small">{html.escape(label)}</span><br>{value}'


# --- login -------------------------------------------------------------------

def login_screen() -> None:
    st.html(CSS)
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown("## CUAD Contract Review")
        st.caption("510 commercial contracts · 41 clause categories · demo corpus")
        with st.form("login"):
            username = st.text_input("Username", placeholder="lawyer-001")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            backend_error = None
            try:
                user = auth.check_login(username.strip().lower(), password)
            except auth.AuthBackendError as exc:
                user = None
                backend_error = str(exc)

            if user:
                st.session_state.user = user
                st.rerun()

            if backend_error:
                st.error(f"Could not read the login store: {backend_error}")
            else:
                st.error("Invalid username or password.")
                if auth.user_count() == 0:
                    st.warning(
                        "APP_USERS is empty: no logins have been seeded for this "
                        "database. Run `make users`, then use the passwords in "
                        "credentials.txt."
                    )
        st.html(
            '<p class="small">Demo logins are in <code>credentials.txt</code>, '
            "written by <code>make users</code>.</p>"
        )


# --- navigation --------------------------------------------------------------

NAV = [
    ("contracts", "Contracts", ("lawyer", "admin")),
    ("clauses", "Clauses", ("lawyer", "admin")),
    ("types", "Types", ("lawyer", "admin")),
    ("parties", "Parties", ("lawyer", "admin")),
    ("reports", "Reports", ("auditor", "admin")),
    ("admin", "Admin", ("admin",)),
]

DEFAULT_PAGE = {"lawyer": "contracts", "auditor": "reports", "admin": "contracts"}


def allowed_pages(role: str) -> set[str]:
    return {key for key, _label, roles in NAV if role in roles}


def sidebar(page: str, term: str | None, role: str) -> None:
    user = st.session_state.user
    with st.sidebar:
        st.markdown(f"**{user['display_name']}**")
        st.caption(f"`{user['username']}`")
        chips([role])
        if st.button("Sign out", width="stretch"):
            audit.log("LOGOUT")
            st.session_state.clear()
            st.query_params.clear()
            st.rerun()

        # Only the corpus pages need a search box.
        if "contracts" in allowed_pages(role):
            st.divider()
            with st.form("search", clear_on_submit=False):
                typed = st.text_input(
                    "Search", value=term or "", placeholder="title, counterparty, clause"
                )
                if st.form_submit_button("Search", width="stretch"):
                    query = typed.strip()
                    if query:
                        audit.log("SEARCH", detail=query)
                    nav(nav="contracts", q=query or None, doc=None)

        st.divider()
        st.html('<span class="small">BROWSE</span>')
        for key, label, roles in NAV:
            if role not in roles:
                continue
            if st.button(
                label,
                key=f"nav-{key}",
                width="stretch",
                type="primary" if key == page else "secondary",
            ):
                nav(nav=key, doc=None)


def facet_controls(selected_clauses, doc_type, jurisdiction, decade, party) -> None:
    stamp = rev()
    with st.sidebar:
        st.divider()
        st.html('<span class="small">FILTER</span>')

        key = f"f-clause-{stamp}"
        st.multiselect(
            "Clause categories (all must be present)",
            options=[row[0] for row in queries.category_index()],
            default=selected_clauses,
            key=key,
            on_change=lambda k=key: nav_soft(clause=",".join(st.session_state[k]) or None),
        )

        types = [ANY] + [row[0] for row in queries.facet_types()]
        key = f"f-type-{stamp}"
        st.selectbox(
            "Agreement type",
            types,
            index=types.index(doc_type) if doc_type in types else 0,
            key=key,
            on_change=lambda k=key: nav_soft(
                type=None if st.session_state[k] == ANY else st.session_state[k]
            ),
        )

        jurisdictions = [ANY] + [row[0] for row in queries.facet_jurisdictions()]
        key = f"f-jur-{stamp}"
        st.selectbox(
            "Jurisdiction",
            jurisdictions,
            index=jurisdictions.index(jurisdiction) if jurisdiction in jurisdictions else 0,
            key=key,
            on_change=lambda k=key: nav_soft(
                jur=None if st.session_state[k] == ANY else st.session_state[k]
            ),
        )

        decades = [ANY] + [row[0] for row in queries.facet_decades()]
        key = f"f-decade-{stamp}"
        st.selectbox(
            "Agreement decade",
            decades,
            index=decades.index(decade) if decade in decades else 0,
            key=key,
            on_change=lambda k=key: nav_soft(
                decade=None if st.session_state[k] == ANY else st.session_state[k]
            ),
        )

        key = f"f-party-{stamp}"
        st.text_input(
            "Counterparty contains",
            value=party or "",
            key=key,
            on_change=lambda k=key: nav_soft(party=st.session_state[k].strip() or None),
        )

        if any([selected_clauses, doc_type, jurisdiction, decade, party]):
            if st.button("Clear filters", width="stretch"):
                nav(clause=None, type=None, jur=None, decade=None, party=None)


# --- corpus pages ------------------------------------------------------------

def page_contracts() -> None:
    term = param("q")
    selected_clauses = param_list("clause")
    doc_type, jurisdiction, decade, party = (
        param("type"), param("jur"), param("decade"), param("party")
    )
    facet_controls(selected_clauses, doc_type, jurisdiction, decade, party)

    rows = queries.browse(
        clauses=selected_clauses,
        doc_type=doc_type,
        jurisdiction=jurisdiction,
        decade=decade,
        party=party,
        term=term,
    )

    st.subheader(f"{len(rows)} contracts")
    active = [f"clause: {c}" for c in selected_clauses]
    active += [f"type: {doc_type}"] if doc_type else []
    active += [f"jurisdiction: {jurisdiction}"] if jurisdiction else []
    active += [f"decade: {decade}"] if decade else []
    active += [f"counterparty: {party}"] if party else []
    active += [f"search: {term}"] if term else []
    chips(active)

    if rows:
        table = [
            {
                "Title": row[1],
                "Type": row[2],
                "Year": str(row[3]) if row[3] is not None else "—",
                "Jurisdiction": row[4],
                "Counterparties": (row[5] or "")[:90],
                "Clauses": f"{row[6]}/41",
            }
            for row in rows
        ]
        ids = [row[0] for row in rows]

        event = st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            height=520,
            on_select="rerun",
            selection_mode="single-row",
            key="tbl-contracts",
            column_config={
                "Title": st.column_config.TextColumn(width=280),
                "Type": st.column_config.TextColumn(width=170),
                "Year": st.column_config.TextColumn(width=60),
                "Jurisdiction": st.column_config.TextColumn(width=120),
                "Counterparties": st.column_config.TextColumn(width=170),
                "Clauses": st.column_config.TextColumn(width=70),
            },
        )
        if event.selection.rows:
            nav(doc=ids[event.selection.rows[0]], nav="document")
    else:
        st.info("No contract titles or counterparties match those filters.")

    # Clause-text matches are shown even when no title matched: a term like
    # "indemnification" appears in clause bodies and in no title at all.
    if term:
        st.divider()
        st.markdown(f"#### Clause text matches for “{term}”")
        hits = queries.clause_matches(term, selected_clauses or None)
        if not hits:
            st.caption("No clause answers contain that term.")
        for index, (doc_id, title, category, answer) in enumerate(hits):
            with st.container(border=True):
                cols = st.columns([5, 1])
                cols[0].markdown(f"**{title}**")
                cols[0].html(f'<span class="small">{html.escape(category)}</span>')
                # index, not doc_id+category: one contract can have several
                # spans for the same category, which would collide.
                if cols[1].button("Open", key=f"hit-{index}", width="stretch"):
                    nav(doc=doc_id, nav="document")
                st.html(f'<div class="snippet">{highlight(answer, term)}</div>')


def page_clauses() -> None:
    index = queries.category_index()
    st.subheader("Clause categories")
    st.caption(
        "How many of the 510 contracts contain each clause. Select a row to filter the register."
    )
    table = [
        {"Clause": row[0], "Contracts": row[1], "Spans": row[2], "Group": row[3],
         "Description": row[4]}
        for row in index
    ]
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=620,
        on_select="rerun",
        selection_mode="single-row",
        key="tbl-clauses",
        column_config={
            "Clause": st.column_config.TextColumn(width=250),
            "Contracts": st.column_config.NumberColumn(width=90),
            "Spans": st.column_config.NumberColumn(width=80),
            "Group": st.column_config.TextColumn(width=70),
            "Description": st.column_config.TextColumn(width=420),
        },
    )
    if event.selection.rows:
        nav(nav="contracts", clause=index[event.selection.rows[0]][0])


def page_types() -> None:
    index = queries.type_index()
    typed = sum(row[1] for row in index)
    st.subheader("Agreement types")
    st.caption(
        f"{len(index)} distinct types across {typed} contracts. Types come from the "
        "annotated contract name, so the tail is long; 'Unclassified' means no type "
        "could be parsed. Select a row to filter the register."
    )
    table = [{"Agreement type": row[0], "Contracts": row[1]} for row in index]
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=620,
        on_select="rerun",
        selection_mode="single-row",
        key="tbl-types",
        column_config={
            "Agreement type": st.column_config.TextColumn(width=340),
            "Contracts": st.column_config.NumberColumn(width=100),
        },
    )
    if event.selection.rows:
        nav(nav="contracts", type=index[event.selection.rows[0]][0])


def page_parties() -> None:
    index = queries.party_index(min_docs=2)
    singletons = queries.party_singletons()
    st.subheader("Counterparties")
    st.caption(
        f"Only the {len(index)} names appearing in more than one contract are listed. "
        f"The other {singletons} occur once: CUAD's party field is free text that mixes "
        "entity names with role labels ('Licensor', 'Party A'). Use the counterparty "
        "filter on Contracts to search all of them. Select a row to filter the register."
    )
    table = [{"Counterparty": row[0], "Contracts": row[1]} for row in index]
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=620,
        on_select="rerun",
        selection_mode="single-row",
        key="tbl-parties",
        column_config={
            "Counterparty": st.column_config.TextColumn(width=340),
            "Contracts": st.column_config.NumberColumn(width=100),
        },
    )
    if event.selection.rows:
        nav(nav="contracts", party=index[event.selection.rows[0]][0])


def page_document() -> None:
    auth.require_role("lawyer", "admin")
    doc_id = param("doc")
    if not doc_id:
        st.info("No document selected.")
        return
    term = param("q")
    meta = queries.document(doc_id)
    if not meta:
        st.error(f"No such contract: {doc_id}")
        return

    # Streamlit re-runs the script on every interaction, so without this guard
    # one open document would produce dozens of DOCUMENT_VIEW rows.
    if st.session_state.get("last_doc") != doc_id:
        st.session_state.last_doc = doc_id
        audit.log("DOCUMENT_VIEW", doc_id=doc_id)

    if st.button("← Back to contracts"):
        nav(nav="contracts", doc=None)

    st.subheader(meta["title"])
    st.html(
        f'<span class="small">{meta["char_len"]:,} characters · '
        f'doc_id <code>{html.escape(doc_id)}</code></span>'
    )

    derived = [
        ("Type", html.escape(str(meta["doc_type"]))),
        ("Agreement year", str(meta["agreement_year"] or "Not stated")),
        ("Jurisdiction", html.escape(str(meta["jurisdiction"]))),
        ("Clauses present", f'{meta["clause_count"]} of 41'),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, derived):
        col.html(small_line(label, value))
    st.html(small_line("Counterparties", html.escape(meta["parties"] or "none parsed")))

    clauses = queries.document_clauses(doc_id)
    status = queries.document_category_status(doc_id)
    full_text = queries.document_text(doc_id)

    found = sum(1 for row in status if row[2])
    if status:
        st.progress(found / len(status), text=f"{found} of {len(status)} clause categories present")

    tab_clauses, tab_checklist, tab_text = st.tabs(["Clauses", "Checklist", "Full text"])

    with tab_clauses:
        if not clauses:
            st.info("No clause answers recorded.")
        for category, _answer, start, end, _question in clauses:
            begin = max(0, start - CONTEXT)
            snippet = full_text[begin:end + CONTEXT]
            body = annotate(snippet, [(start - begin, end - begin)], term)
            st.markdown(f"**{category}**")
            st.html(f'<div class="snippet">…{body}…</div>')

    with tab_checklist:
        lines = []
        for category, _group, is_found, span_count in status:
            mark = "✔" if is_found else "·"
            detail = f"{span_count} span(s)" if is_found else "not present"
            lines.append(
                f'<div>{mark} &nbsp; <b>{html.escape(category)}</b> &nbsp; '
                f'<span class="small">{detail}</span></div>'
            )
        st.html("".join(lines))

    with tab_text:
        shown = full_text[:MAX_RENDER]
        st.html(
            f'<div class="doc">'
            f'{annotate(shown, [(s, e) for _, _, s, e, _ in clauses], term)}</div>'
        )
        if len(full_text) > MAX_RENDER:
            st.warning(f"Showing the first {MAX_RENDER:,} of {len(full_text):,} characters.")
        st.download_button("Download full text", data=full_text, file_name=f"{doc_id}.txt")

    st.divider()
    st.markdown("#### Related contracts")
    st.caption(
        "Ranked by shared counterparty, clause overlap, agreement type, jurisdiction and year."
    )
    rel = queries.related(doc_id)
    if not rel:
        st.caption("Nothing scored above the threshold for this contract.")
    for rel_id, title, rel_type, rel_year, score, reasons in rel:
        with st.container(border=True):
            cols = st.columns([4, 1, 1])
            cols[0].markdown(f"**{title}**")
            cols[0].html(
                f'<span class="small">{html.escape(str(rel_type))} · '
                f'{rel_year or "year not stated"}</span>'
            )
            cols[1].html(f'<span class="small">score {score}</span>')
            if cols[2].button("Open", key=f"rel-{rel_id}", width="stretch"):
                nav(doc=rel_id, nav="document")
            chips([part.strip() for part in reasons.split("|")])


# --- main --------------------------------------------------------------------

def _refresh_user() -> bool:
    """Re-read role and status so a suspension takes effect on the next rerun."""
    username = st.session_state.user["username"]
    rows = db.q(
        "SELECT DISPLAY_NAME, APP_ROLE, STATUS FROM APP_USERS WHERE USERNAME = %s",
        (username,),
    )
    if not rows or rows[0][2] != "active":
        return False
    st.session_state.user["display_name"] = rows[0][0]
    st.session_state.user["role"] = rows[0][1]
    return True


def main() -> None:
    if "user" not in st.session_state:
        login_screen()
        return

    if not _refresh_user():
        # Log once, then drop the session. The account may have been suspended.
        audit.log(
            "SESSION_REVOKED",
            actor=st.session_state.user["username"],
            detail="account not active",
        )
        st.session_state.clear()
        st.query_params.clear()
        st.warning("Your session has ended because the account is no longer active.")
        login_screen()
        return

    st.html(CSS)
    role = st.session_state.user["role"]
    allowed = allowed_pages(role)

    page = param("nav") or DEFAULT_PAGE.get(role, "contracts")
    if page != "document" and page not in allowed:
        page = DEFAULT_PAGE.get(role, "contracts")

    sidebar(page, param("q"), role)

    if page == "document":
        page_document()
    elif page == "reports":
        reports.page_reports()
    elif page == "admin":
        admin.page_admin()
    elif page == "clauses":
        page_clauses()
    elif page == "types":
        page_types()
    elif page == "parties":
        page_parties()
    else:
        page_contracts()

    st.divider()
    st.html(
        '<span class="small">Demo only. Type, year, jurisdiction and counterparty are '
        "parsed from CUAD's free-text clause answers; unparseable values are shown as "
        "Unclassified or Not stated. CUAD data (CC BY 4.0) from The Atticus Project. "
        "Not legal advice.</span>"
    )


main()
