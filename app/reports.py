"""Access reports for the auditor and admin role.

Aggregation lives here rather than in Snowflake views because every report is
date filtered and the cutoff is a parameter. See sql/07_audit.sql for the
table, and query ACCESS_LOG directly for ad-hoc analysis.

Every list carries its true total in a trailing `COUNT(*) OVER ()` column and
is capped by a *visible* limit chosen in the UI. It used to be capped silently
at 100/200 rows, which reads as "this is everything" until the log is big
enough that it isn't. See docs/fixes.md.
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import streamlit as st

import audit
import db
from auth import require_role

REPORTS = ("Logins", "Searches", "Documents", "Activity")
RANGES = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None}
LIMITS = {"100 rows": 100, "250 rows": 250, "1000 rows": 1000, "All": 100_000}

_TOTAL = "COUNT(*) OVER () AS TOTAL"

LOGINS = f"""
    SELECT ACTOR,
           COUNT(*)                                        AS EVENTS,
           COUNT_IF(EVENT_TYPE = 'LOGIN_SUCCESS')          AS SUCCESSES,
           COUNT_IF(EVENT_TYPE = 'LOGIN_FAILURE')          AS FAILURES,
           MAX(IFF(EVENT_TYPE = 'LOGIN_SUCCESS', EVENT_TS, NULL)) AS LAST_SUCCESS,
           {_TOTAL}
    FROM ACCESS_LOG
    WHERE EVENT_TYPE IN ('LOGIN_SUCCESS', 'LOGIN_FAILURE') AND EVENT_TS >= %s
    GROUP BY ACTOR
    ORDER BY FAILURES DESC, ACTOR
    LIMIT %s
"""

FAILURES = f"""
    SELECT EVENT_TS, ACTOR, COALESCE(ACTOR_ROLE, '—'), DETAIL, {_TOTAL}
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'LOGIN_FAILURE' AND EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT %s
"""

SEARCHES = f"""
    SELECT DETAIL,
           COUNT(*)                    AS SEARCHES,
           COUNT(DISTINCT ACTOR)       AS USERS,
           MAX(EVENT_TS)               AS LAST_SEARCH,
           {_TOTAL}
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'SEARCH' AND DETAIL IS NOT NULL AND EVENT_TS >= %s
    GROUP BY DETAIL
    ORDER BY SEARCHES DESC, DETAIL
    LIMIT %s
"""

RECENT_SEARCHES = f"""
    SELECT EVENT_TS, ACTOR, DETAIL, {_TOTAL}
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'SEARCH' AND EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT %s
"""

DOCUMENTS = f"""
    SELECT l.DOC_ID, c.TITLE,
           COUNT(*)                    AS VIEWS,
           COUNT(DISTINCT l.ACTOR)     AS VIEWERS,
           MAX(l.EVENT_TS)             AS LAST_VIEW,
           {_TOTAL}
    FROM ACCESS_LOG l
    LEFT JOIN CONTRACTS c ON c.DOC_ID = l.DOC_ID
    WHERE l.EVENT_TYPE = 'DOCUMENT_VIEW' AND l.EVENT_TS >= %s
    GROUP BY l.DOC_ID, c.TITLE
    ORDER BY VIEWS DESC, l.DOC_ID
    LIMIT %s
"""

RECENT_VIEWS = f"""
    SELECT l.EVENT_TS, l.ACTOR, l.DOC_ID, c.TITLE, {_TOTAL}
    FROM ACCESS_LOG l
    LEFT JOIN CONTRACTS c ON c.DOC_ID = l.DOC_ID
    WHERE l.EVENT_TYPE = 'DOCUMENT_VIEW' AND l.EVENT_TS >= %s
    ORDER BY l.EVENT_TS DESC
    LIMIT %s
"""

ACTIVITY = f"""
    SELECT EVENT_TS, EVENT_TYPE, ACTOR, ACTOR_ROLE, DOC_ID, DETAIL, {_TOTAL}
    FROM ACCESS_LOG
    WHERE EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT %s
"""


def _cutoff(days: int | None) -> str:
    if days is None:
        return "1900-01-01 00:00:00"
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _stamp(value) -> str:
    return str(value)[:19] if value is not None else "—"


def _to_csv(columns: list[str], rows: list[tuple]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def _fetch(sql: str, cutoff: str, limit: int) -> tuple[list[tuple], int]:
    """Run a report query and split off its trailing total.

    The total is a window count, so it is computed before LIMIT and is the true
    size of the result set.
    """
    data = db.q(sql, (cutoff, limit))
    if not data:
        return [], 0
    return [row[:-1] for row in data], int(data[0][-1])


def _render(
    label: str,
    key: str,
    columns: list[str],
    rows: list[tuple],
    total: int,
    height: int = 320,
) -> None:
    if not rows:
        st.caption("No events in this range.")
        return
    st.dataframe(
        [dict(zip(columns, row)) for row in rows],
        width="stretch",
        hide_index=True,
        height=height,
    )
    if total > len(rows):
        st.caption(f"Showing {len(rows)} of {total} — raise “Rows per list” to see more.")
    else:
        st.caption(f"All {total} row(s) shown.")
    st.download_button(
        "Download CSV",
        data=_to_csv(columns, rows),
        file_name=f"{label.lower()}.csv",
        mime="text/csv",
        key=f"{key}-csv",
    )


def _report_logins(cutoff: str, limit: int) -> None:
    data, total = _fetch(LOGINS, cutoff, limit)
    rows = [
        (row[0], row[1], row[2], row[3], _stamp(row[4]))
        for row in data
    ]
    st.markdown("**Attempts and outcomes per username**")
    _render("logins", "logins", ["Username", "Events", "Successes", "Failures", "Last success"],
            rows, total)

    failures, f_total = _fetch(FAILURES, cutoff, limit)
    failures = [
        (_stamp(row[0]), row[1] or "—", row[2], row[3] or "—")
        for row in failures
    ]
    st.markdown("**Recent failed attempts**")
    st.caption(
        "The attempted username is stored verbatim (truncated); passwords never are."
    )
    _render("failed-logins", "failures",
            ["When (UTC)", "Attempted username", "Role", "Reason"], failures, f_total)


def _report_searches(cutoff: str, limit: int) -> None:
    data, total = _fetch(SEARCHES, cutoff, limit)
    rows = [
        (row[0], row[1], row[2], _stamp(row[3]))
        for row in data
    ]
    st.markdown("**Most frequent search terms**")
    _render("searches", "searches", ["Term", "Searches", "Users", "Last search"], rows, total)

    recent, r_total = _fetch(RECENT_SEARCHES, cutoff, limit)
    recent = [
        (_stamp(row[0]), row[1] or "—", row[2] or "—")
        for row in recent
    ]
    st.markdown("**Recent searches**")
    _render("recent-searches", "recent-searches", ["When (UTC)", "Username", "Term"],
            recent, r_total)


def _report_documents(cutoff: str, limit: int) -> None:
    data, total = _fetch(DOCUMENTS, cutoff, limit)
    rows = [
        (row[1] or row[0], row[0], row[2], row[3], _stamp(row[4]))
        for row in data
    ]
    st.markdown("**Most accessed contracts**")
    _render("documents", "documents",
            ["Title", "doc_id", "Views", "Viewers", "Last view"], rows, total)

    recent, r_total = _fetch(RECENT_VIEWS, cutoff, limit)
    recent = [
        (_stamp(row[0]), row[1] or "—", row[3] or row[2])
        for row in recent
    ]
    st.markdown("**Recent document views**")
    _render("recent-views", "recent-views", ["When (UTC)", "Username", "Contract"],
            recent, r_total)


def _report_activity(cutoff: str, limit: int) -> None:
    data, total = _fetch(ACTIVITY, cutoff, limit)
    rows = [
        (_stamp(row[0]), row[1], row[2] or "—", row[3] or "—", row[4] or "—", row[5] or "—")
        for row in data
    ]
    st.markdown("**Every recorded event**")
    _render("activity", "activity",
            ["When (UTC)", "Event", "Actor", "Role", "doc_id", "Detail"], rows, total,
            height=420)


RENDERERS = {
    "Logins": _report_logins,
    "Searches": _report_searches,
    "Documents": _report_documents,
    "Activity": _report_activity,
}


def page_reports() -> None:
    require_role("admin", "auditor", page="reports")
    st.subheader("Access reports")

    col_report, col_range, col_rows = st.columns([2, 1, 1])
    report = col_report.radio("Report", REPORTS, horizontal=True, key="rep-choice")
    window = col_range.selectbox("Range", list(RANGES), key="rep-range")
    size = col_rows.selectbox("Rows per list", list(LIMITS), key="rep-limit")
    limit = LIMITS[size]

    cutoff = _cutoff(RANGES[window])
    st.caption(
        f"Showing events since {cutoff if RANGES[window] else 'the beginning'} (UTC). "
        "The CSV exports the rows shown."
    )

    # Log once per report+range, not on every rerun, and only when a report is
    # actually generated. Auditing report generation is the point.
    stamp = f"{report}|{window}"
    if st.session_state.get("last_report") != stamp:
        st.session_state.last_report = stamp
        audit.log("REPORT_RUN", detail=stamp)

    RENDERERS[report](cutoff, limit)
