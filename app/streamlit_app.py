"""CUAD POC: lawyer-facing contract search over CUAD_DB.CORPUS.

Run with: make app
"""
from __future__ import annotations

import hashlib
import hmac
import html
import re

import streamlit as st

import db

st.set_page_config(page_title="CUAD Contract Review", page_icon="§", layout="wide")

MAX_RENDER = 200_000   # chars of contract text rendered inline
CONTEXT = 260          # chars of context around a clause span
MAX_CLAUSE_HITS = 100
MAX_DOC_HITS = 40

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
.snippet { font-size: 0.82rem; line-height: 1.5; }
.snippet .clause { background: rgba(255, 196, 0, 0.35); }
.snippet .term   { background: rgba(0, 200, 120, 0.35); font-weight: 600; }
.small { color: rgba(128,128,128,1); font-size: 0.75rem; }
</style>
"""


# --- helpers -----------------------------------------------------------------

def highlight(text: str, term: str) -> str:
    """Escape text and wrap case-insensitive occurrences of term in <mark>."""
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


def annotate(text: str, spans: list[tuple[int, int]], term: str) -> str:
    """Render text with clause spans and search hits marked.

    Overlapping marks are dropped rather than nested: the first span wins.
    """
    marks: list[tuple[int, int, str]] = [(s, e, "clause") for s, e in spans if 0 <= s < e <= len(text)]
    if term:
        marks += [(m.start(), m.end(), "term") for m in re.finditer(re.escape(term), text, re.IGNORECASE)]
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


def check_login(username: str, password: str) -> dict | None:
    try:
        rows = db.q(
            "SELECT DISPLAY_NAME, SALT, PWD_HASH, ITERATIONS FROM APP_USERS WHERE USERNAME = %s",
            (username,),
        )
    except RuntimeError:
        return None
    if not rows:
        return None
    display_name, salt_hex, digest_hex, iterations = rows[0]
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
    ).hex()
    if hmac.compare_digest(computed, digest_hex):
        return {"username": username, "display_name": display_name}
    return None


# --- screens -----------------------------------------------------------------

def login_screen() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    left, mid, right = st.columns([1, 1.1, 1])
    with mid:
        st.markdown("## CUAD Contract Review")
        st.caption("510 commercial contracts · 41 clause categories · demo corpus")
        with st.form("login"):
            username = st.text_input("Username", placeholder="lawyer-001")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            user = check_login(username.strip(), password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid username or password.")
        st.markdown(
            '<p class="small">Demo logins are in <code>credentials.txt</code>, '
            "written by <code>make users</code>.</p>",
            unsafe_allow_html=True,
        )


def sidebar() -> tuple[str, list[str]]:
    user = st.session_state.user
    with st.sidebar:
        st.markdown(f"**{user['display_name']}**")
        st.caption(f"`{user['username']}`")
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.rerun()
        st.divider()
        term = st.text_input(
            "Search clause text",
            key="term",
            placeholder="e.g. governing law, indemnif",
            help="Case-insensitive substring match over clause answers.",
        ).strip()
        selected = st.multiselect("Clause categories", options=db.categories())
        st.caption("Leave the box empty to browse the document register.")
        st.divider()
        st.caption(f"{len(db.categories())} categories · XS warehouse")
    return term, selected


def render_register(term: str) -> None:
    st.subheader("Document register")
    st.caption("Pick a contract, or search for a term in the sidebar.")
    rows = db.q(
        """
        SELECT DOC_ID, TITLE, PARTIES, AGREEMENT_DATE, GOVERNING_LAW, CHAR_LEN
        FROM V_CONTRACT_METADATA
        ORDER BY TITLE
        LIMIT 200
        """
    )
    for doc_id, title, parties, date, law, char_len in rows:
        with st.container(border=True):
            cols = st.columns([4, 2, 1])
            cols[0].markdown(f"**{highlight(title, term)}**", unsafe_allow_html=True)
            cols[0].markdown(
                f'<span class="small">{highlight((parties or "parties not stated")[:120], term)}</span>',
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f'<span class="small">{date or "no date"} · {law or "law not stated"}</span>',
                unsafe_allow_html=True,
            )
            if cols[2].button("Open", key=f"open-reg-{doc_id}", use_container_width=True):
                st.session_state.doc_id = doc_id
                st.rerun()
    st.caption("Showing the first 200 of 510 contracts.")


def render_results(term: str, selected: list[str]) -> None:
    like = f"%{term}%"

    where = "cl.ANSWER_TEXT ILIKE %s"
    params: list = [like]
    if selected:
        where += f" AND cl.CATEGORY IN ({','.join(['%s'] * len(selected))})"
        params += selected
    clause_hits = db.q(
        f"""
        SELECT cl.CLAUSE_ID, cl.DOC_ID, c.TITLE, cl.CATEGORY, cl.ANSWER_TEXT
        FROM CLAUSES cl
        JOIN CONTRACTS c ON c.DOC_ID = cl.DOC_ID
        WHERE {where}
        ORDER BY c.TITLE, cl.ANSWER_START
        LIMIT {MAX_CLAUSE_HITS}
        """,
        tuple(params),
    )

    doc_hits = db.q(
        f"""
        SELECT c.DOC_ID, c.TITLE, c.CHAR_LEN
        FROM CONTRACT_TEXT t
        JOIN CONTRACTS c ON c.DOC_ID = t.DOC_ID
        WHERE t.FULL_TEXT ILIKE %s
        ORDER BY c.TITLE
        LIMIT {MAX_DOC_HITS}
        """,
        (like,),
    )

    st.subheader(f"Results for “{term}”")
    left, right = st.columns(2)
    left.metric("Clause matches", len(clause_hits))
    right.metric("Contracts containing the term", len(doc_hits))

    if clause_hits:
        st.markdown("#### Clause matches")
        for clause_id, doc_id, title, category, answer in clause_hits:
            with st.container(border=True):
                head = st.columns([4, 2, 1])
                head[0].markdown(f"**{highlight(title, term)}**", unsafe_allow_html=True)
                head[1].markdown(f'<span class="small">{category}</span>', unsafe_allow_html=True)
                if head[2].button("Open", key=f"open-cl-{clause_id}", use_container_width=True):
                    st.session_state.doc_id = doc_id
                    st.rerun()
                st.markdown(
                    f'<div class="snippet">{highlight(answer, term)}</div>',
                    unsafe_allow_html=True,
                )
        if len(clause_hits) == MAX_CLAUSE_HITS:
            st.caption(f"Capped at {MAX_CLAUSE_HITS} clause matches.")
    else:
        st.info("No clause answers matched. The term may still appear in contract bodies.")

    if doc_hits:
        st.markdown("#### Contracts containing the term")
        for doc_id, title, char_len in doc_hits:
            cols = st.columns([5, 1, 1])
            cols[0].markdown(f"{highlight(title, term)}", unsafe_allow_html=True)
            cols[1].markdown(f'<span class="small">{char_len:,} chars</span>', unsafe_allow_html=True)
            if cols[2].button("Open", key=f"open-doc-{doc_id}", use_container_width=True):
                st.session_state.doc_id = doc_id
                st.rerun()


def render_document(doc_id: str, term: str) -> None:
    if st.button("← Back to results"):
        st.session_state.pop("doc_id", None)
        st.rerun()

    meta = db.q(
        """
        SELECT TITLE, PARTIES, AGREEMENT_DATE, EFFECTIVE_DATE, EXPIRATION_DATE,
               RENEWAL_TERM, NOTICE_PERIOD_TO_TERMINATE_RENEWAL, GOVERNING_LAW, CHAR_LEN
        FROM V_CONTRACT_METADATA WHERE DOC_ID = %s
        """,
        (doc_id,),
    )
    if not meta:
        st.error(f"No such contract: {doc_id}")
        return
    (title, parties, agreement_date, effective_date, expiration_date,
     renewal_term, notice_period, governing_law, char_len) = meta[0]

    st.subheader(title)
    st.markdown(
        f'<span class="small">{char_len:,} characters · doc_id <code>{doc_id}</code></span>',
        unsafe_allow_html=True,
    )

    fields = [
        ("Parties", parties),
        ("Agreement date", agreement_date),
        ("Effective date", effective_date),
        ("Expiration date", expiration_date),
        ("Renewal term", renewal_term),
        ("Notice period", notice_period),
        ("Governing law", governing_law),
    ]
    for row_start in range(0, len(fields), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, fields[row_start:row_start + 4]):
            col.markdown(
                f'<span class="small">{label}</span><br>{highlight(value or "not stated", term)}',
                unsafe_allow_html=True,
            )

    clauses = db.q(
        """
        SELECT CATEGORY, ANSWER_TEXT, ANSWER_START, ANSWER_END
        FROM CLAUSES WHERE DOC_ID = %s ORDER BY ANSWER_START, ANSWER_END
        """,
        (doc_id,),
    )
    status = db.q(
        """
        SELECT CATEGORY, GRP, FOUND, SPAN_COUNT
        FROM V_CONTRACT_CATEGORY_STATUS WHERE DOC_ID = %s
        ORDER BY GRP, CATEGORY
        """,
        (doc_id,),
    )
    text_rows = db.q("SELECT FULL_TEXT FROM CONTRACT_TEXT WHERE DOC_ID = %s", (doc_id,))
    full_text = text_rows[0][0] if text_rows else ""

    found = sum(1 for row in status if row[2])
    if status:
        st.progress(found / len(status), text=f"{found} of {len(status)} clause categories present in this contract")

    tab_clauses, tab_checklist, tab_text = st.tabs(["Matched clauses", "Category checklist", "Full text"])

    with tab_clauses:
        if not clauses:
            st.info("No clause answers recorded for this contract.")
        for category, answer, start, end in clauses:
            begin = max(0, start - CONTEXT)
            snippet = full_text[begin:end + CONTEXT]
            body = annotate(snippet, [(start - begin, end - begin)], term)
            st.markdown(f"**{category}**", unsafe_allow_html=True)
            st.markdown(f'<div class="snippet">…{body}…</div>', unsafe_allow_html=True)

    with tab_checklist:
        for category, grp, is_found, span_count in status:
            mark = "✔" if is_found else "·"
            detail = f"{span_count} span(s)" if is_found else "not present"
            st.markdown(f"{mark} &nbsp; **{category}** &nbsp; <span class='small'>{detail}</span>",
                        unsafe_allow_html=True)

    with tab_text:
        spans = [(s, e) for _, _, s, e in clauses]
        shown = full_text[:MAX_RENDER]
        st.markdown(CSS, unsafe_allow_html=True)
        st.markdown(f'<div class="doc">{annotate(shown, spans, term)}</div>', unsafe_allow_html=True)
        if len(full_text) > MAX_RENDER:
            st.warning(f"Showing the first {MAX_RENDER:,} of {len(full_text):,} characters.")
        st.download_button(
            "Download full text",
            data=full_text,
            file_name=f"{doc_id}.txt",
            mime="text/plain",
        )


# --- main --------------------------------------------------------------------

def main() -> None:
    if "user" not in st.session_state:
        login_screen()
        return

    term, selected = sidebar()

    if st.session_state.get("doc_id"):
        render_document(st.session_state.doc_id, term)
    elif term:
        render_results(term, selected)
    else:
        render_register(term)

    st.divider()
    st.caption(
        "Demo only. CUAD data (CC BY 4.0) from The Atticus Project; "
        "not legal advice. Clause spans are expert annotations, not model output."
    )


main()
