# Build notes

Sharp edges encountered while building this, in the order they hurt. Most were
found by testing rather than by reading, and several are the reason the code
looks the way it does.

## Snowflake

**A column named `ROLE` parses in `CREATE TABLE` but not in `ALTER TABLE`.**

```sql
CREATE TABLE t (ROLE STRING);                        -- fine
ALTER TABLE t ADD COLUMN IF NOT EXISTS ROLE STRING;  -- "ambiguous column name 'ROLE'"
```

`ROLE` is a keyword, and `ALTER` resolves it differently. Hence `APP_ROLE`, and
`ACTOR_ROLE` in the audit log.

**`ADD COLUMN IF NOT EXISTS … NOT NULL DEFAULT` fails when the column already
exists** — with the same "ambiguous column name" error, for a column that is not
a keyword at all. The upgrade path in `sql/04_users.sql` therefore uses a plain
`ADD COLUMN IF NOT EXISTS` plus an explicit backfill:

```sql
ALTER TABLE APP_USERS ADD COLUMN IF NOT EXISTS APP_ROLE STRING;
UPDATE APP_USERS SET APP_ROLE = 'lawyer' WHERE APP_ROLE IS NULL;
```

**`CREATE OR REPLACE` drops grants.** Proven with a throwaway role:

```
after GRANT, before replace          -> OWNERSHIP + SELECT
after CREATE OR REPLACE              -> OWNERSHIP only        <- grant gone
future grant, then CREATE OR REPLACE -> OWNERSHIP + SELECT    <- survives
```

This is why `make grants` runs as the last data step of `make pipeline` and why
`sql/08_grants.sql` grants `ON FUTURE TABLES/VIEWS`. Without it, every rebuild
silently revokes the app's access.

**Object privileges can only be granted to roles.** There is no
`GRANT SELECT … TO USER`. So a service identity is two objects: a role carrying
the grants, and a user carrying the authentication.

**A user with no password cannot be MFA-challenged.** Key-pair auth is not
password auth, so the account's MFA-for-passwords policy does not apply. This is
what makes unattended `make` runs possible at all.

**The CLI has no credential fallback.** Given a private key path and no
authenticator, `snow` hard-errors ("Private Key authentication requires
authenticator set to SNOWFLAKE_JWT") and will not retry with a password. Hence
`scripts/resolve_auth.py` and the `scripts/snow.sh` wrapper, which ask the
Python connector which credential actually works and export exactly one.

**Durations and timezones.** `CURRENT_TIMESTAMP()` follows the session timezone,
so audit timestamps drifted by hours from local time. `sf.py` pins the session to
UTC.

## Streamlit

**The script re-runs on every interaction.** `page_document()` compares the open
`doc_id` against `st.session_state.last_doc` before writing a `DOCUMENT_VIEW`
row. Without that guard, one viewed contract produces dozens of audit rows.
Report generation uses the same pattern.

**`st.dataframe` renders to canvas.** Its rows are not in the DOM or the
accessibility tree, so table rows cannot be clicked by text and are not readable
by automation. Every index page uses row *selection* and reports a
`StreamlitDuplicateElementKey` risk if you key widgets on cell contents.

**Result tables can have duplicate keys.** Keying the clause-match `Open` buttons
on `doc_id + category` collides when one contract has several spans for the same
category — which is common. Key on the row index instead.

**Contract text contains blank lines, which end a Markdown HTML block.** Raw
HTML through `st.markdown(..., unsafe_allow_html=True)` leaks the rest of the
snippet as literal tags after the first blank line. All raw HTML goes through
`st.html`, which does no Markdown parsing.

**An empty `APP_USERS` looks exactly like a wrong password.** `check_login` used
to swallow every database error and return `None`, so the app could connect
fine, have no logins, and reject everyone with "Invalid username or password".
It now raises `AuthBackendError` for a store it cannot read, and the login screen
names the empty-table case explicitly.

**Returning early hides the useful part.** `page_contracts` originally returned
when the register was empty, which suppressed the clause-text matches — the one
thing you want when a term appears in clause bodies and in no title.

## Playwright and video

**`get_by_role(name=...)` matches substrings**, and Streamlit's own facet
dropdowns carry `aria-label="Open"` — four of them, in the sidebar, first in DOM
order. An unscoped `get_by_role("button", name="Open")` therefore resolves to a
dropdown toggle, and the click silently opens a multiselect instead of a
document. No error; just a beat that never advances. Scope to
`[data-testid="stMain"]`.

**CSS `zoom` breaks coordinate clicks.** Chromium reports element boxes unzoomed,
so Playwright computes coordinates wrong by the zoom factor — clicks work near
the top-left corner and miss everywhere else. This cost a full debugging cycle
before the real cause (`aria-label="Open"`) turned out to be different.

**`page.video` is a property in Python Playwright**, not a method, despite
reading like one. `page.video()` raises `TypeError: 'Video' object is not
callable`.

**`waitUntil: "networkidle"` does not work against Streamlit.** It holds a
websocket open indefinitely, so the page never goes idle. Wait on text instead.

**Never `sleep` and hope.** Every beat waits for its expected text, then sleeps
only long enough for the UI to be readable on camera.

## Data

**Category names disagree between the two CUAD source files.** `CUADv1.json`
title-cases them (`Notice Period To Terminate Renewal`) while
`category_descriptions.csv` does not (`...to...`). Ten categories differ.
`build_load_files.py` normalizes case-insensitively and stores the CSV spelling,
so the join works.

**`category_descriptions.csv` has a UTF-8 BOM.** Read it with `utf-8-sig` or the
first column name arrives mangled.

**NDJSON, not CSV.** Contract text contains embedded newlines, quotes and commas
— which Snowflake's CSV loader handles badly and its JSON loader handles
natively.

**The dataset is smaller than its headline.** "13,000+ labels" means 13,823
answer *spans*, across 6,702 answered questions out of 20,910. The corpus is also
dirtier than it reads: 10 contracts have no parseable year, and free-text dates
include `14t h day of April, 2015` and `[●]`.
