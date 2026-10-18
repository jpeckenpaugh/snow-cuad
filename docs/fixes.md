# Fixes

Nine issues were raised by the three role-played testers (their full reports are
in [`docs/feedback/`](feedback/)) and then re-tested by hand in a live browser
before anything was changed. This page records what each one was, what changed,
and how the change was verified.

Every fix below was re-verified against the running app after the change.
`make verify-ui` runs those checks — 15 assertions across the nine issues —
against a running app and exits non-zero if any fail; the file is
`tests/verify_ui.py`.

| # | Issue | Status |
|---|---|---|
| 1 | Clause search silently capped at 60 results | fixed |
| 2 | Register rows could not be opened by clicking | fixed |
| 3 | "0 contracts" shown above real clause matches | fixed |
| 4 | Admin account picker reset after every action | fixed (reworked after re-testing) |
| 5 | Reports truncated silently at 100/200 rows | fixed |
| 6 | Denied page requests left no audit trail | fixed |
| 7 | User list lost its Last login column when narrow | fixed (reworked after re-testing) |
| 8 | "1 contracts" | fixed |
| 9 | Reload logged you out; deep links did not resume | mitigated + documented |

---

## 1. Clause search capped at 60, silently

**Symptom.** `indemnif` rendered exactly 60 match cards with no total and no
paging. Snowflake holds 193 spans for `indemnif` and 5,565 for `agreement`, so
the list looked like a complete answer while being an arbitrary slice.

**Why it mattered.** A lawyer reviewing a clause type cannot tell corpus size
from page size. This was the lawyer tester's top request.

**Change.** `app/queries.py` gains `clause_matches(..., limit, offset)` and
`clause_match_count(...)`. `app/streamlit_app.py` renders
"Showing 1–60 of 193 matching clause spans." and Previous/Next controls, keyed
off a `cpage` query parameter so a page of results is still linkable. A new
search resets to page 1.

**Verified.** `indemnif` → "Showing 1–60 of 193", Next → "Showing 61–120 of
193".

## 2. Register rows could not be opened by clicking

**Symptom.** Clicking a row in the Contracts register (or the Clauses / Types /
Parties indexes) did nothing. It was reported as "cannot open a contract from
the register at all".

**Diagnosis.** Trusted single and double clicks on the row body did nothing,
while a click on the row's small leading selection cell *did* navigate. That is
how Streamlit's row selection behaves: only the selection cell fires it. So the
feature was technically present and practically undiscoverable — and the one
affordance that worked navigated immediately, with no confirmation.

**Change.** A `row_picker()` helper pairs the table with an explicit action
button. Selection now enables a labelled button ("Open" on the register,
"Filter register" on the index pages) that performs the navigation. Nothing
happens on a stray click, and the hint text says what to do.

**Verified.** Selecting a row enables the Open button; clicking it lands on
`?nav=document&doc=2themart…`.

## 3. "0 contracts" shown above the clause matches

**Symptom.** Searching `indemnif` displayed "0 contracts" and "No contract
titles or counterparties match those filters." immediately above 60 clause
matches. The tester twice assumed the search had failed.

**Why it happened.** A term like "indemnification" appears in clause bodies and
in no title, so the register is legitimately empty — but the page presented
that as the whole result.

**Change.** The clause-match count is computed before the header is written. If
titles do not match but clause text does, the page now says so:
"No contract title or counterparty matches "indemnif". 193 clause-text matches
are shown below." The bare "0 contracts" heading is gone.

**Verified.** See the text above, reproduced in the live run.

## 4. Admin account picker reset after every action

**Symptom.** Choosing an account, then suspending or reactivating it, snapped
the Account dropdown back to the first row (`auditor · Tomas Beck`), so every
action cost a re-selection and invited acting on the wrong account.

**Cause.** `st.selectbox("Account", range(len(labels)))` with no stable key and
positional options.

**Change (first attempt).** Key the widget and use usernames as options
instead of positional indexes. This held for one action, but re-testing caught
it resetting again on a *second* action — the selectbox is rebased by the
`st.rerun()` that follows a status change, and the next click could land on the
wrong account. A picker that can silently retarget an action is worse than the
re-selection it costs.

**Change (what shipped).** The Manage block is now one row of actions per
account — `Suspend` / `Reactivate` and `Reset password` buttons scoped to that
username. There is no shared widget to drift, so acting on the wrong account is
structurally impossible, and the re-selection cost disappears. This also
answers the administrator's "one-at-a-time dropdown" complaint directly.

**Verified.** `Reactivate` on `test-user-01` takes the row from `suspended` to
`active`; the reverse `Suspend` takes it back to `suspended`, with the row
reflectng it both times.

## 5. Reports truncated silently

**Symptom.** `app/reports.py` hard-coded `LIMIT 100` (and 200 for Activity).
At today's volume nothing was hidden, but the first row of a busy day would
silently become the whole report.

**Change.** Every list carries a `COUNT(*) OVER ()` total, and the page has a
visible "Rows per list" control (100 / 250 / 1000 / All). Each table is
labelled either "All N row(s) shown." or "Showing X of N — raise "Rows per
list" to see more." The CSV exports the rows shown, and the caption says so.

**Verified.** Logins reports "All 5 row(s) shown." with "Rows per list" set to
100.

## 6. Denied page requests left no audit trail

**Symptom.** An auditor forcing `?nav=document&doc=…` got "Not authorised for
this page." and the log gained nothing. Probing for pages you cannot have is
exactly what a reviewer wants to see, and there was no `ACCESS_DENIED` event
type at all.

**Change.** `app/auth.py::require_role` now logs `ACCESS_DENIED` with the page
it refused, and the dispatcher in `app/streamlit_app.py` logs an explicit
`?nav=` request for a page the role does not have. `ACCESS_DENIED` is added to
`EVENT_TYPES` in `app/audit.py` and to the known-types comment in
`sql/07_audit.sql`. No DDL change was needed: `EVENT_TYPE` is a plain string.

**Verified.** Two rows in `ACCESS_LOG`:

```
ACCESS_DENIED | auditor | auditor | page=document | 782d0171-… | 2026-10-18 09:47:27
```

## 7. User list lost its Last login column when narrow

**Symptom.** The Users table is a canvas grid with six fixed column widths
totalling 730px. Measured against the container: 938px wide at a 1400px
viewport (fine), but 538px at 1000px, where the Last login column scrolled off
the right edge. Cell text was also unselectable.

**Change.** First attempt was to drop the fixed widths; that halved the
overflow but did not remove it, because a canvas grid has a minimum width that
cannot shrink. So the list is now a plain HTML table (`_users_table` in
`app/admin.py`) with the same columns. Six rows need no grid: the table wraps,
its text is selectable, and it is exposed to assistive technology.

**Verified.** At a 1000px viewport: `table.users` is 540px wide with 540px of
scroll (no overflow) and all six headers present, including
"Last login (UTC)".

## 8. "1 contracts"

**Symptom.** A single-row register read "1 contracts".

**Change.** A `plural()` helper; the header is "1 contract" or "2 contracts".

**Verified.** Searching `2Themart` gives "1 contract".

## 9. Reload logged you out; deep links did not resume

**Symptom.** A full page reload dropped to the sign-in screen, so a URL that
looked linkable was not: it lost the session *and* the destination.

**What is fixable, and what is not.** Session state living in the browser
session is inherent to the POC's auth model — there is no cookie or token
store, and adding one (or putting a session token in the URL) is a design
decision with security consequences, not a bug fix. What *was* a bug is that
the destination was silently discarded: a deep link should survive the sign-in
it forces.

**Change.** Navigation already lives in the query string, so the params were
still there; the login screen now says what it is about to do ("Sign in to
continue to the contracts page…") and the destination is honoured after
sign-in. The limitation is stated on the login screen rather than left to be
discovered.

**Verified.** Opening `?nav=contracts&q=indemnif` logged out shows the hint;
signing in in place lands on that filtered register
(`?nav=contracts&q=indemnif`, with clause matches rendered).

---

## Deliberately not changed

**A suspended login still reads "Invalid username or password."** It looks the
same as a wrong password, and that is correct: account status should not be
disclosed to an unauthenticated caller. The operator's need — knowing *why* a
login was refused — is served by the Logins report, which shows the reason. The
tester's report framed this as a bug; it is not one.

**Search terms are still stored verbatim.** Deliberate and disclosed in the UI.
Whether to mask them is a policy question for the data owner.

**`EVENT_ID` still is not chronological.** That is Snowflake `AUTOINCREMENT`
under concurrent writers, not something the app controls. The actionable part
is documentation, so `sql/07_audit.sql` now says to order by `EVENT_TS`.

## Residual limitations (unchanged)

- No document-level access control: roles gate pages, not contracts.
- The audit log is application-level: append-only by privilege, but not
  tamper-evident.
- No per-user detail/edit/delete in the admin console; no bulk actions.
- Counterparty data remains noisy; `Unclassified` / `Not stated` remain visible
  facets rather than being hidden.
