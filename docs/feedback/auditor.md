# Feedback — Auditor (Tomas Beck, auditor)

## What I did
- Read `README.md`, `sql/07_audit.sql` and the trust-boundary sections of `docs/security.md` before touching the app.
- Signed in to http://localhost:8501 as `auditor` (confirmed the sidebar shows **Tomas Beck** / *auditor* / **Sign out**). The auditor sidebar exposes only **Reports** — no search box, no Contracts/Clauses/Types/Parties — so I could **not** generate SEARCH or DOCUMENT_VIEW activity as myself; that part of the brief was impossible for this role and I say so rather than invent it.
- Opened the Reports page and ran all four reports: Logins, Searches, Documents, Activity. Switched Range to **All time** (the "Showing events since the beginning (UTC)" caption confirmed it took).
- Downloaded report CSVs through the **Download CSV** buttons. The buttons are real Streamlit downloads served from `/media/<hash>.csv`; I captured the URLs and fetched them with `curl -s http://localhost:8501/media/<hash>.csv`, then read the contents.
- Direct-URL authorization test: set `?nav=document&doc=alliancebancorpincofpennsylvania-10-18-2006-ex-1-2-agency-agreement` and forced a rerun. Result: **"Not authorised for this page."** — and, importantly, **no audit row was written for the denied attempt**.
- Exercised the failure path: signed out, then attempted `auditor` with a deliberately wrong password → UI showed **"Invalid username or password."**, and a `LOGIN_FAILURE` row (`auditor / auditor / bad password`, 2026-10-18 08:43:55) appeared in the report and its CSV. Then signed back in.
- Command line (all read-only, run from `/Users/jarad/git/snow-cuad`):
  - `make query Q="SELECT EVENT_TYPE, COUNT(*) ... GROUP BY EVENT_TYPE"` — event-type census.
  - `make query Q="SELECT SESSION_ID, EVENT_TYPE, ACTOR, EVENT_TS ... ORDER BY SESSION_ID, EVENT_TS"` — session correlation.
  - `make query Q="SHOW GRANTS ON TABLE CUAD_DB.CORPUS.ACCESS_LOG"` — confirmed `STREAMLITWEB_ROLE` has only `SELECT` + `INSERT`, `ACCOUNTADMIN` owns the table.
  - `make query Q="SELECT COLUMN_NAME, DATA_TYPE FROM ...INFORMATION_SCHEMA.COLUMNS WHERE ... TABLE_NAME='ACCESS_LOG'"` — column list.
  - `make query Q="SELECT TABLE_NAME, TABLE_TYPE FROM CUAD_DB.INFORMATION_SCHEMA.TABLES ..."` — to look for any entitlement table (**there is none**).
  - `make query Q="SHOW TABLES LIKE 'ACCESS_LOG' IN SCHEMA CUAD_DB.CORPUS"` — `retention_time = 1`.
  - `make query Q="SELECT COUNT(*) ... LAG(EVENT_TS) OVER (ORDER BY EVENT_ID) ... WHERE EVENT_TS < PREV_TS"` — **10 timestamp inversions** when ordering by `EVENT_ID`.

## Liked
1. **Session correlation is captured properly.** `SESSION_ID` cleanly groups a session: e.g. auditor session `4a397fe3-…` = `LOGIN_SUCCESS` (23:31:03.958) followed by four `REPORT_RUN`s; lawyer-001's `4ad809dc-…` = login → search → document view → logout, in order. The right join key exists — it is simply never shown.
2. **The Logins report has the right shape.** "Attempts and outcomes per username" gives Events / Successes / Failures / Last success per username, and "Recent failed attempts" lists When / Attempted username / Role / Reason. I saw both real reasons firsthand: `test-user-01 / account suspended` and my own `auditor / bad password`. The caption even states attempted usernames are stored verbatim and passwords never are.
3. **The four categories map to real reviewer questions** and the Activity report is genuinely complete: my exported all-time CSV contained `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`, `SESSION_REVOKED`, `SEARCH`, `DOCUMENT_VIEW`, `REPORT_RUN`, `USER_CREATED`, `USER_SUSPENDED`, `PASSWORD_RESET` — so admin actions are in the same stream as user actions.
4. **CSV exports are faithful and the Documents report resolves ids.** `recent-views.csv` gives `When (UTC),Username,Contract` with the human title, not just a `doc_id`, which is what makes the file usable outside the app.
5. **The privilege story is real, not aspirational.** `SHOW GRANTS` shows `STREAMLITWEB_ROLE` has `SELECT` + `INSERT` only on `ACCESS_LOG` (no `UPDATE`/`DELETE`), and when I forced a document URL the `require_role("lawyer","admin")` backstop stopped me. The log is append-only *by privilege*, which I could verify.

## Frustrated by
1. **No report can be filtered by user or by document.** Every list is flat. "Recent document views" is just rows of When/Username/Contract, capped, with no "show me lawyer-001" control; "Most accessed contracts" gives me `Viewers = 2` as a number, not the two names. Answering a concrete question meant leaving the app for a SQL console or the CSV.
2. **Silent truncation.** `reports.py` hard-codes `LIMIT 100` (searches, views, failures, documents) and `LIMIT 200` (activity). There is no total, no "showing 100 of N", no pagination and no warning. With 47 rows today it looks complete; at real volume the top of the report would silently become the whole report.
3. **A denied access leaves no trace.** My forced `?nav=document...` request showed "Not authorised for this page." and wrote **nothing** to `ACCESS_LOG`. There is no `ACCESS_DENIED`/authorization-failure event type at all, so probing the system for pages you cannot have is invisible to the reviewer.
4. **The data needed to answer "who could see contract Y?" is not modelled anywhere.** `INFORMATION_SCHEMA.TABLES` shows nothing resembling an entitlement/permission table — only `ACCESS_LOG`, `APP_USERS` and the corpus. The product can therefore only ever tell me who *did* look, never who *may*.
5. **`EVENT_ID` is not chronological, so the obvious ad-hoc query misleads.** My very first recommended query, `ORDER BY EVENT_ID DESC`, returned timestamps out of order; a dedicated check found **10 inversions**, e.g. `EVENT_ID 1311 @ 08:44:48` sorts below `EVENT_ID 1401 @ 08:37:18`. The ids also skip in blocks (`…1401`, then `1311`), so they are not a usable sequence either.

## The one thing I'd add first
Add actor and document filters (plus visible row counts and paging) to every report. The raw material is already there — `ACTOR`, `DOC_ID` and `SESSION_ID` are populated and the joins work — but today the reviewer can only scroll a capped list. Filtering by a username, opening a contract's view history, or opening a `SESSION_ID` timeline would turn four static dumps into the two questions an access review actually asks: "which contracts did user X open?" and "who looked at contract Y, and when?". Until that exists, the honest answer to a real reviewer is "export the CSV and pivot it yourself".

## Honest limits I noticed
- **The log is application-level, not tamper-proof.** The writer role holds `INSERT`, so anyone with the service credentials can append forged rows under any `ACTOR`/`ACTOR_ROLE`; `ACCOUNTADMIN` owns the table and can `UPDATE`/`DELETE`/`DROP` it outright. `demo/runner.py` even does `DELETE FROM ACCESS_LOG` to reset the log.
- **It is not tamper-*evident* either.** No row hash, no chaining, no signature, no external sink — nothing would let a third party detect an altered or removed row after the fact.
- **No document-level entitlement.** Roles gate *pages*, not contracts; every lawyer sees the whole corpus. So "who could see contract Y?" is unanswerable by design, and the log must be read as "who did", not "who may".
- **Search terms are stored verbatim in plaintext** in `DETAIL` (I read `governing law`, `agreement`, `indemnif` straight out of `searches.csv`), as are attempted usernames in failed logins.
- **Audit write failures are swallowed** to stderr (`app/audit.py`), so the app keeps running and the report just quietly misses events; nothing surfaces a gap.
- **No long-term retention or immutability:** `SHOW TABLES` reports `retention_time = 1` day, and no SQL or Makefile setting raises it.
- **`SESSION_ID` is captured but never exposed** in any report, table or CSV export.
- **No request metadata:** no IP address, user agent, or source columns, so "from where" is unanswerable.
- **Downloads are not logged:** neither the report CSVs nor the "Download full text" button produce an event; I only get `REPORT_RUN` with `Report|Range`.
- **`LOGIN_FAILURE` overloads `ACTOR`** with the attempted username, so `ACTOR` sometimes means "authenticated identity" and sometimes "string someone typed" — a reviewer has to know which.
- **Sessions that end by closing the tab never log `LOGOUT`**, so absence of a logout is not evidence of anything.
- **I could not review my own browsing** because the auditor role cannot reach the corpus pages at all; that separation is defensible, but it means the auditor's own corpus activity can never appear in the log.

## What would make this audit-worthy
- Per-actor and per-document filters, totals, and paging on every report; stop relying on a silent `LIMIT`.
- Log denials: authorization failures, backend auth errors, and downloads — all currently invisible.
- Tamper-evidence: hash-chain each row (`prev_hash`), sign with a key the app's writer does not hold, and/or stream to an append-only external sink (object-lock storage, a Snowflake event table, or a SIEM).
- Document-level entitlement (or contract-level grants), so "who could see Y" is answerable rather than inferred.
- Retention and immutability: explicit long retention, no `DELETE`/`UPDATE` path outside a break-glass role, and a documented, audited wipe procedure instead of `DELETE FROM ACCESS_LOG`.
- Surface `SESSION_ID` as a first-class session view (login → searches → views → logout).
- Capture source IP and user agent at the write chokepoints, and keep a monotonic sequence separate from `EVENT_ID`.
- Alerting for the patterns that matter: failure spikes / brute force, off-hours access, mass document pulls, first-seen sources.
