# Testing and debug summary

What the three role-played reviewers said, what I determined about each
comment, what was changed, and what was left alone and why.

The reviewers' own write-ups are in [`docs/feedback/`](feedback/). The code
changes are described fix-by-fix in [`fixes.md`](fixes.md); this page is the
narrative that connects the two: **comment → determination → disposition.**

| | |
|---|---|
| Reviewers | 3 (lawyer, administrator, auditor), one per role |
| Comments raised | 15 frustrations + 3 "one thing I'd add first" + 25 honest limits |
| Confirmed defects | 9 fixed, 1 documentation error corrected |
| Judged not a defect | 4 (with reasons below) |
| Not reproducible as stated | 1 |
| Deferred to follow-up | 6 |
| Re-testing after the fixes | 15 assertions passing (`make verify-ui`) |

---

## 1. How the test was run

**Reviewers.** Three sub-agents were briefed as the three roles and told to
actually use the running app, then write a report in a fixed shape (what I did
/ 5 liked / 5 frustrated by / one thing to add first / honest limits). Each was
given only its own credentials. They were told to ground every claim in
something they observed and to say so plainly rather than invent results — and
one did exactly that (the auditor reported that part of its brief was
impossible for its role, rather than fabricating search activity).

| Reviewer | Role | Login | Report |
|---|---|---|---|
| Ada Whitfield | lawyer | `lawyer-001` | [`feedback/lawyer.md`](feedback/lawyer.md) |
| Sasha Lindqvist | administrator | `admin` | [`feedback/admin.md`](feedback/admin.md) |
| Tomas Beck | auditor | `auditor` | [`feedback/auditor.md`](feedback/auditor.md) |

**Then every claim was re-tested by hand before anything changed.** Reviewer
accounts are evidence, not verdicts, and several comments turned out to be
one of: correct behaviour, a documentation error, or a misreading of a
difficult widget. Each was reproduced in a real browser before it was called a
bug.

**Method.** Browser automation against the live app plus SQL against the live
tables. Two tools, for a reason:

- Most interactions were driven with a local headless Chromium (Playwright),
  because the assistant's own browser tool could not always reach the canvas
  widgets both reviewers struggled with — which is itself part of finding #7.
- Claims about the audit trail and the corpus were checked with SQL, since
  "the report says X" and "the table says X" are different claims.

**Caveats.** The assistant browser was flaky for all three reviewers (one fell
back to Playwright, one could not screenshot, one fetched report CSVs with
`curl`). Values they read from canvas grids are lower-confidence; everything
quoted below was re-derived independently. Reviewer reports are unedited except
for redacting two one-time passwords for the throwaway `test-user-01`.

---

## 2. Cross-cutting findings

Three problems were reported independently by two different roles. Those are
the strongest signals in the set, because the reviewers never compared notes.

| Theme | Raised by | Determination |
|---|---|---|
| **Capped lists with no total** — clause search stopped at 60; reports stopped at `LIMIT 100/200` | lawyer + auditor | Confirmed. Both fixed with real totals and paging |
| **Canvas grids as the weak surface** — register rows would not open; user list lost a column and its text was unselectable | lawyer + admin | Confirmed. Register reworked; user list no longer a grid |
| **Search terms stored verbatim** | admin + auditor | Deliberate and disclosed. Not changed; flagged as a policy call |
| **Audit log is application-level, not tamper-proof** | admin + auditor | Correctly described by both. Documented as a residual limit |

---

## 3. Comment → determination → disposition

### Lawyer (Ada Whitfield)

| Reviewer's comment | Determination | Disposition |
|---|---|---|
| Clause search "silently stops at 60" with no total or paging; `indemnif`, `assignment`, `agreement` all returned exactly 60 | **Confirmed.** `agreement` matches **5,565** spans, `indemnif` **193**. The UI showed 60 with no denominator | **Fixed** — totals + paging (#1). This was also her "one thing I'd add first" |
| "I could not open a contract from the Contracts register" — single and double click did nothing | **Confirmed, with a correction.** Clicking the row *body* does nothing; clicking the row's leading selection cell navigates. The feature existed but was effectively undiscoverable, and it teleported on the one affordance that worked | **Fixed** — explicit Open button (#2) |
| Searching a category's own name does not retrieve it: "Governing Law: 437 by facet vs 3 by text" | **Not a defect.** The facet counts annotated *categories*; a text search matches literal span text, and a Governing Law span usually reads "the laws of the State of New York". This is the documented "no semantic search" limit | **No change** to the number. But the *header* it exposed was a real bug — see next row |
| The register header read "0 contracts … No contract titles or counterparties match those filters" while clause matches sat below it; "twice I assumed my search had failed" | **Confirmed.** A term like `indemnification` is genuinely absent from every title, so the empty register was correct and the presentation was not | **Fixed** — the page now says so (#3): "No contract title or counterparty matches "indemnif". 193 clause-text matches are shown below." |
| Counterparty data too noisy to rely on: "Agreement", "Germany", "All Of Its Subsidiaries", "Cisco Cisco Systems"; a document line read "Newegg Inc. Newegg" | **Not a defect.** Documented and by design: CUAD's party field is free text mixing entities with role labels | **No change.** Her read of the Parties page ("27 names") did expose a docs error — corrected (see §5) |
| "Every full page reload dropped me to the sign-in screen", so URL state is only linkable while a session is live | **Partly inherent, partly a bug.** Session state in the browser session is the POC's auth model. Losing the *destination* across the forced sign-in was a bug | **Mitigated + documented** (#9). Deep links resume after sign-in, with an explicit hint |
| The register count reads "1 contracts" | **Confirmed**, cosmetic | **Fixed** (#8) |
| The search box is labelled "title, counterparty, clause" while its count only reflects titles and counterparties | **Confirmed**, minor | **Open nit.** Fix #3 explains the split in the empty state; the placeholder wording itself is unchanged. Suggested: "title or counterparty (clause text searched below)" |

### Administrator (Sasha Lindqvist)

| Reviewer's comment | Determination | Disposition |
|---|---|---|
| "The Users table is unreadable as a table" — canvas grid, text not selectable, absent from the accessibility tree until focused, and Last login scrolled off-screen (730px of columns in a ~538px container) | **Confirmed**, and I measured it: at a 1400px viewport all six columns fit; at 1000px the container is 538px and Last login was gone | **Fixed** (#7). See §4 for why the fix is an HTML table rather than narrower columns |
| The Manage account picker "resets after every action" | **Confirmed.** Reproduced: picker on `test-user-01 · Test User · lawyer · suspended` reverted to `auditor · Tomas Beck · auditor · active` after Reactivate | **Fixed** (#4), then reworked: re-testing caught the keyed picker still resetting on a *second* action, so the Manage block became per-account action rows. See §4 |
| "A suspended login is indistinguishable from a typo in the moment" | **Not a defect.** I confirmed both paths return the identical message — including a suspended account with the *correct* password. Not disclosing account status to an unauthenticated caller is correct | **No change.** The operator's need is already met by the Logins report, which shows the reason (`account suspended`) |
| "Almost nothing about a user is editable or inspectable": no delete, edit-role, edit-name, change-password, bulk, search/pagination, or per-user detail; never shows who suspended an account or when, though `SUSPENDED_BY`/`SUSPENDED_AT` are stored | **Confirmed as a design gap**, not a bug. No delete is deliberate and enforced below the UI | **Deferred.** This was the admin's "one thing I'd add first" and is the largest single improvement left. See §6 |
| The one-time password "is a flash that disappears on the next click" — no show-again, no non-invalidating re-issue, no expiry indication | **By design**, with a real UX cost. `admin.py` shows it once and pops it, because "an admin UI that persists plaintext passwords is worse than one that shows them once" | **No change** to the one-time display. See §6 |

### Auditor (Tomas Beck)

| Reviewer's comment | Determination | Disposition |
|---|---|---|
| "No report can be filtered by user or by document" — "Most accessed contracts" gives `Viewers = 2` as a number, not the names | **Confirmed.** The join keys (`ACTOR`, `DOC_ID`) are populated; the UI never exposes them | **Deferred.** His "one thing I'd add first". Fixed only the *visibility* half — see next row |
| "Silent truncation": `LIMIT 100` (and 200 for Activity) with no total and no warning | **Confirmed** in `reports.py`. At current volume nothing was hidden, which is precisely why it was dangerous | **Fixed** (#5) — true totals plus a visible "Rows per list" control |
| "A denied access leaves no trace": forced `?nav=document…` showed "Not authorised for this page." and wrote **nothing**; no `ACCESS_DENIED` event type at all | **Confirmed**, and the most audit-significant finding in the set | **Fixed** (#6). Verified in `ACCESS_LOG`: `ACCESS_DENIED | auditor | auditor | page=document` |
| "The data needed to answer 'who could see contract Y?' is not modelled anywhere" — no entitlement table | **Not a defect.** The POC deliberately has no document-level access control; roles gate pages | **No change.** A product decision, documented as a residual limit |
| "`EVENT_ID` is not chronological" — 10 inversions; ids also skip in blocks | **Confirmed** (I measured 11, more events having accrued). Cause is Snowflake `AUTOINCREMENT` under concurrent writers, not a bug in the app | **Documented** — `sql/07_audit.sql` now says to order by `EVENT_TS`, and points out why |

---

## 4. Two fixes that changed shape when verified

Automated re-testing caught both of these, which is the argument for having it.

**#7 — the user list.** The obvious fix for the user list was to remove the
fixed column widths. I did that first, and measured again: overflow dropped
from 192px to 68px at a 1000px viewport, but did not disappear — a canvas grid
has a minimum width it will not shrink below, and the text stayed unselectable.

So the list became a plain HTML table instead. For six rows that is strictly
better: it wraps at any width, its text is selectable, and it is exposed to
assistive technology — which closes the accessibility half of the original
comment as well as the layout half. What it gives up is grid sorting and
fullscreen, which six rows do not need.

**#4 — the account picker.** Keying the selectbox and using usernames as its
options looked sufficient: the picker held through one Reactivate. It did not
hold through the reverse action — the re-test showed it back on `auditor`, with
the intended `Suspend` never applied. A picker that can silently retarget an
action is worse than the re-selection it costs, so the Manage block was
replaced with one row of actions per account. There is no shared widget left to
drift, and it answers the administrator's "one-at-a-time dropdown" complaint as
a side effect.

In both cases the reviewer's framing was accepted as a symptom but not as the
solution.

---

## 5. Things the reviewers read that were wrong in the *docs*, not the app

**Counterparty counts.** The lawyer's report noted the Parties page says 27
names appear in more than one contract, while `README.md` and
`architecture.md` said 29 repeat. I checked the tables directly:

```
CONTRACT_PARTY rows: 915 | distinct names: 881
names in 2+ contracts: 27 | names with exactly one row: 854
```

27 is right, and 854 + 27 = 881. The documentation had been carrying row
counts (885 / 29 sum to 914 ≈ 915 rows) mislabelled as names. **Corrected** in
both files. Small, but it is exactly the kind of number a lawyer would quote
back at you.

---

## 6. Deliberately not changed, and why

| Item | Why not |
|---|---|
| Suspended login returns the generic message | Correct security behaviour. Disclosing account status to an unauthenticated caller is worse than the confusion it saves |
| Search terms and attempted usernames stored verbatim | Deliberate and disclosed in the UI. Whether to mask them is the data owner's call |
| One-time password shown once and popped | Deliberate: persisting plaintext passwords would be worse. A "copy it now" warning and a non-invalidating re-issue are reasonable polish, not fixes |
| Search-box placeholder wording | Fix #3 removes the misleading consequence; changing the placeholder is cosmetic |
| `EVENT_ID` ordering | Not app-controlled. Documented instead |
| Counterparty noise; `Unclassified` / `Not stated` | Documented design limits. Surfacing the gaps was the point |

## 7. Follow-ups worth doing, in the reviewers' own priority order

1. **A per-user detail view in the admin console** (admin's top ask): click a
   user, see role, status, created, last login, suspended-by/at, and their
   recent audit events, with actions on the panel. The data already exists.
2. **Actor and document filters on every report** (auditor's top ask), plus a
   `SESSION_ID` timeline view — the correlation key is already captured and
   never surfaced.
3. **Document-level entitlement**, so "who *could* see contract Y?" becomes
   answerable instead of unanswerable by design.
4. **Tamper-evidence and retention for the audit log**: hash-chain or sign
   rows, sink to append-only storage, and raise the 1-day retention.
5. **Log more of what a reviewer needs**: denials are now logged; downloads,
   source IP and user agent are not.
6. **Alerting** on failure spikes, off-hours access and mass document pulls.

## 8. Not reproducible as stated

The administrator reported that the user grid's values "are absent from the
accessibility tree until you click in and move keyboard focus". In my run the
DOM contained 45 `gridcell` elements with readable text and the full header
list was present — so the a11y tree was populated. The genuine defect was the
**horizontal overflow** (#7), which is what got fixed. Her underlying
complaints about the grid (unselectable text, hard to read) were real and are
also resolved by moving to a table.

One further note for the record: the assistant's own browser tool could not
click a canvas cell at all ("Node does not have a layout object"), which is why
verification used Playwright. That is a limitation of the tool, not a finding
about the app.

---

## 9. Reproducing the checks

`make verify-ui` runs all of it against a **running** app (start it with
`make app` first): 15 assertions across the nine issues, exiting non-zero if
any fail. `tests/verify_ui.py` is the script; it needs Playwright — see its
docstring for the two ways to run it. Screenshots land in `build/verify-ui/`.

The one stateful check suspends and then reactivates a throwaway account whose
name starts with `test-`, so a real login is never touched; it skips itself if
no such account exists, and it restores whatever status it found.

Manual equivalents, if you would rather click:

1. Search `indemnif` → expect "Showing 1–60 of 193", and a Next page.
2. Search `indemnif` → expect the info line naming 193 clause-text matches, and
   no "0 contracts" heading.
3. Search `2Themart` → expect "1 contract".
4. Contracts register → select a row → Open enables → clicking it opens the
   document.
5. Admin → Users → at a narrow window, Last login is still visible and its text
   selects.
6. Admin → each account has its own Suspend/Reactivate and Reset password
   buttons; an action applies to the row it sits on.
7. Auditor → Reports → each table shows "All N row(s) shown." or "Showing X of
   N", and "Rows per list" is present.
8. Auditor → force a document URL → "Not authorised for this page.", and an
   `ACCESS_DENIED` row appears in `ACCESS_LOG`.
9. Open a deep link while logged out → the login screen names the destination →
   sign in → you land on it.

## 10. State and artefacts

- `test-user-01` exists and is **suspended**; the five seeded accounts are
  **active** (verified in `APP_USERS`).
- Testing added audit noise to `ACCESS_LOG`: `LOGIN_FAILURE` rows for the
  throwaway user, `SEARCH` / `DOCUMENT_VIEW` / `REPORT_RUN` rows from the test
  sessions, and two `ACCESS_DENIED` rows.
- No app objects, grants or SQL tables were changed; the only SQL edit is a
  comment in `sql/07_audit.sql`.
