"""Access reports for the auditor and admin roles.

Aggregation lives here rather than in Snowflake views because every report is
date filtered and the cutoff is a parameter. See sql/07_audit.sql for the
table, and query ACCESS_LOG directly for ad-hoc analysis.
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

LOGINS = """
    SELECT ACTOR,
           COUNT(*)                                        AS EVENTS,
           COUNT_IF(EVENT_TYPE = 'LOGIN_SUCCESS')          AS SUCCESSES,
           COUNT_IF(EVENT_TYPE = 'LOGIN_FAILURE')          AS FAILURES,
           MAX(IFF(EVENT_TYPE = 'LOGIN_SUCCESS', EVENT_TS, NULL)) AS LAST_SUCCESS
    FROM ACCESS_LOG
    WHERE EVENT_TYPE IN ('LOGIN_SUCCESS', 'LOGIN_FAILURE') AND EVENT_TS >= %s
    GROUP BY ACTOR
    ORDER BY FAILURES DESC, ACTOR
"""

FAILURES = """
    SELECT EVENT_TS, ACTOR, COALESCE(ACTOR_ROLE, '—'), DETAIL
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'LOGIN_FAILURE' AND EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT 100
"""

SEARCHES = """
    SELECT DETAIL,
           COUNT(*)                    AS SEARCHES,
           COUNT(DISTINCT ACTOR)       AS USERS,
           MAX(EVENT_TS)               AS LAST_SEARCH
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'SEARCH' AND DETAIL IS NOT NULL AND EVENT_TS >= %s
    GROUP BY DETAIL
    ORDER BY SEARCHES DESC, DETAIL
    LIMIT 100
"""

RECENT_SEARCHES = """
    SELECT EVENT_TS, ACTOR, DETAIL
    FROM ACCESS_LOG
    WHERE EVENT_TYPE = 'SEARCH' AND EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT 100
"""

DOCUMENTS = """
    SELECT l.DOC_ID, c.TITLE,
           COUNT(*)                    AS VIEWS,
           COUNT(DISTINCT l.ACTOR)     AS VIEWERS,
           MAX(l.EVENT_TS)             AS LAST_VIEW
    FROM ACCESS_LOG l
    LEFT JOIN CONTRACTS c ON c.DOC_ID = l.DOC_ID
    WHERE l.EVENT_TYPE = 'DOCUMENT_VIEW' AND l.EVENT_TS >= %s
    GROUP BY l.DOC_ID, c.TITLE
    ORDER BY VIEWS DESC, l.DOC_ID
    LIMIT 100
"""

RECENT_VIEWS = """
    SELECT l.EVENT_TS, l.ACTOR, l.DOC_ID, c.TITLE
    FROM ACCESS_LOG l
    LEFT JOIN CONTRACTS c ON c.DOC_ID = l.DOC_ID
    WHERE l.EVENT_TYPE = 'DOCUMENT_VIEW' AND l.EVENT_TS >= %s
    ORDER BY l.EVENT_TS DESC
    LIMIT 100
"""

ACTIVITY = """
    SELECT EVENT_TS, EVENT_TYPE, ACTOR, ACTOR_ROLE, DOC_ID, DETAIL
    FROM ACCESS_LOG
    WHERE EVENT_TS >= %s
    ORDER BY EVENT_TS DESC
    LIMIT 200
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


def _render(label: str, key: str, columns: list[str], rows: list[tuple], height: int = 320) -> None:
    if not rows:
        st.caption("No events in this range.")
        return
    st.dataframe(
        [dict(zip(columns, row)) for row in rows],
        width="stretch",
        hide_index=True,
        height=height,
    )
    st.download_button(
        "Download CSV",
        data=_to_csv(columns, rows),
        file_name=f"{label.lower()}.csv",
        mime="text/csv",
        key=f"{key}-csv",
    )


def _report_logins(cutoff: str) -> None:
    rows = [
        (row[0], row[1], row[2], row[3], _stamp(row[4]))
        for row in db.q(LOGINS, (cutoff,))
    ]
    st.markdown("**Attempts and outcomes per username**")
    _render("logins", "logins", ["Username", "Events", "Successes", "Failures", "Last success"], rows)

    failures = [
        (_stamp(row[0]), row[1] or "—", row[2], row[3] or "—")
        for row in db.q(FAILURES, (cutoff,))
    ]
    st.markdown("**Recent failed attempts**")
    st.caption(
        "The attempted username is stored verbatim (truncated); passwords never are."
    )
    _render("failed-logins", "failures",
            ["When (UTC)", "Attempted username", "Role", "Reason"], failures)


def _report_searches(cutoff: str) -> None:
    rows = [
        (row[0], row[1], row[2], _stamp(row[3]))
        for row in db.q(SEARCHES, (cutoff,))
    ]
    st.markdown("**Most frequent search terms**")
    _render("searches", "searches", ["Term", "Searches", "Users", "Last search"], rows)

    recent = [
        (_stamp(row[0]), row[1] or "—", row[2] or "—")
        for row in db.q(RECENT_SEARCHES, (cutoff,))
    ]
    st.markdown("**Recent searches**")
    _render("recent-searches", "recent-searches", ["When (UTC)", "Username", "Term"], recent)


def _report_documents(cutoff: str) -> None:
    rows = [
        (row[1] or row[0], row[0], row[2], row[3], _stamp(row[4]))
        for row in db.q(DOCUMENTS, (cutoff,))
    ]
    st.markdown("**Most accessed contracts**")
    _render("documents", "documents",
            ["Title", "doc_id", "Views", "Viewers", "Last view"], rows)

    recent = [
        (_stamp(row[0]), row[1] or "—", row[3] or row[2])
        for row in db.q(RECENT_VIEWS, (cutoff,))
    ]
    st.markdown("**Recent document views**")
    _render("recent-views", "recent-views", ["When (UTC)", "Username", "Contract"], recent)


def _report_activity(cutoff: str) -> None:
    st.markdown("**Every recorded event**")
    rows = [
        (_stamp(row[0]), row[1], row[2] or "—", row[3] or "—", row[4] or "—", row[5] or "—")
        for row in db.q(ACTIVITY, (cutoff,))
    ]
    _render("activity", "activity",
            ["When (UTC)", "Event", "Actor", "Role", "doc_id", "Detail"], rows, height=420)


RENDERERS = {
    "Logins": _report_logins,
    "Searches": _report_searches,
    "Documents": _report_documents,
    "Activity": _report_activity,
}


def page_reports() -> None:
    require_role("admin", "auditor")
    st.subheader("Access reports")

    col_report, col_range = st.columns([2, 1])
    report = col_report.radio("Report", REPORTS, horizontal=True, key="rep-choice")
    window = col_range.selectbox("Range", list(RANGES), key="rep-range")

    cutoff = _cutoff(RANGES[window])
    st.caption(f"Showing events since {cutoff if RANGES[window] else 'the beginning'} (UTC).")

    # Log once per report+range, not on every rerun, and only when a report is
    # actually generated. Auditing report generation is the point.
    stamp = f"{report}|{window}"
    if st.session_state.get("last_report") != stamp:
        st.session_state.last_report = stamp
        audit.log("REPORT_RUN", detail=stamp)

    RENDERERS[report](cutoff)
