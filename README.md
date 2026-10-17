# snow-cuad

Phase-1 POC: load the CUAD contract corpus into Snowflake and expose a
lawyer-facing search UI with three demo logins.

CUAD (Contract Understanding Atticus Dataset) is 510 commercial contracts
annotated with 41 types of clauses a lawyer looks for during M&A diligence.
See <https://www.atticusprojectai.org/cuad>.

## Current status

**Step 6 of N complete: least-privilege service identity.**

- [x] Python 3.14 virtualenv
- [x] Snowflake CLI + Python connector in `.venv`
- [x] `.env`-driven auth (no `config.toml`, no global state)
- [x] Download CUAD JSON
- [x] Build load files
- [x] Snowflake objects + load + verification
- [x] Demo users
- [x] Streamlit app
- [x] Derived dimensions (type, year, jurisdiction, counterparty)
- [x] Browse by clause / type / jurisdiction / counterparty + related documents
- [x] Roles: lawyer / auditor / admin
- [x] Admin console (create, suspend, reset) and an access audit log
- [x] Three-layer auth: ACCOUNTADMIN onboarding, a STREAMLITWEB service identity, app logins

---

# 1. Environment

## Prerequisites

- Python 3.14 (`python3.14` on `PATH`)
- `openssl` (ships with macOS/Linux)
- A Snowflake account. A trial is fine.

## Bootstrap

```bash
make bootstrap
```

This will:

1. create `.venv` using `python3.14` (override with `PYTHON_BIN=...`),
2. install `snowflake-cli`, `snowflake-connector-python`, `streamlit`,
   `python-dotenv` from `requirements.txt`,
3. create `keys/`, `data/`, `build/`,
4. copy `.env.example` -> `.env` with mode `600` (never overwrites an
   existing `.env`),
5. print installed versions.

Re-running is safe and idempotent.

### Why 3.14 works

Verified at bootstrap time: `snowflake-cli 3.29.0` is a pure-Python wheel
(`>=3.10`), and every binary dependency it pins has cp314 wheels --
`snowflake-connector-python 4.7.5`, `cryptography`, `pydantic-core`,
`cffi`. Streamlit's tree (pyarrow, numpy, pandas) also resolves on 3.14.

## Credentials

There are **two** Snowflake identities, with separate credentials:

| Identity | Credential | Secret in | Used by |
|---|---|---|---|
| you, as `ACCOUNTADMIN` | key pair (or password) | `.env` + `keys/snowflake_key.p8` | `make` — onboarding |
| `STREAMLITWEB` | key pair | `.env.service` + `keys/streamlitweb_key.p8` | the app |

`make keypair` provisions the first, `make service-user` the second. The
service identity is covered in [Least privilege](#5-least-privilege).

All auth flows through environment variables, which both `snow` and the
Python connector read. Nothing is written to `~/.snowflake/config.toml`,
so this repo never interferes with your other Snowflake work.

### Either or, never one or the other

`.env` carries **both** credentials, and both stay valid in Snowflake:

```dotenv
SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8
SNOWFLAKE_PASSWORD=<your password>
```

The tooling tries key-pair first and falls back to the password. A key that is
rotated, unregistered, or missing therefore degrades to a slower login instead
of a lockout. Nothing is ever swapped out from under you:

```bash
make bootstrap          # creates .env from .env.example
make keypair            # generates AND registers a key pair, alongside your password
```

`make keypair` does the whole job against the connection you already have:

1. connect using whatever credential currently works
2. generate `keys/snowflake_key.p8` (reused if present; `FORCE=1` to rotate)
3. register the public half in Snowflake's spare slot, `RSA_PUBLIC_KEY_2`
4. **verify** the new key authenticates
5. promote it to `RSA_PUBLIC_KEY` and free the spare slot
6. rewrite `.env` so both credentials are present and active

If verification fails at step 4, the spare slot is unset, the staged key file is
removed, and `.env` is untouched — so a bad rotation cannot cost you access.
`--no-switch` stops after step 3.

Because both are present, a fallback is reported rather than hidden:

```
warning: fell back to password auth (key-pair: 390144 (28000): ... JWT token is invalid)
```

### The `snow` CLI needs a hint

The Python connector falls back on its own. The Snowflake CLI does not: given a
private key path and no authenticator it refuses outright, and given both it
still will not retry. So `scripts/snow.sh` resolves which credential works
before every invocation and exports exactly one:

```
note: snow CLI using password auth (key-pair unavailable)
```

This is why `make` survives a broken key end to end — verified by running a
full `make pipeline` against an unregistered key: exit 0, 14 fallback notices.

### How key-pair auth works

The key is generated **once**, not per step or per session:

- the **private** half never leaves the machine (`keys/snowflake_key.p8`, mode 600)
- the **public** half is registered on the Snowflake user
- each connection derives a short-lived **JWT** signed with the private key,
  which Snowflake verifies against the stored public key

No secret is transmitted. And because this is not password auth, the account's
MFA-for-passwords policy does not apply — which is what lets `make` run
unattended.

Snowflake keeps two key slots (`RSA_PUBLIC_KEY` and `RSA_PUBLIC_KEY_2`). That
is what makes the rotation above non-destructive: the new key is proven in the
spare slot before it replaces the live one.

### Where to find the account identifier

Snowflake UI -> bottom-left account menu -> **Account identifier**. It
looks like `myorg-myaccount` (or legacy `xy12345.us-east-1`). It is **not**
the full URL and not the hostname.

## Verify the connection

```bash
make check-env   # offline: required keys, placeholders, key file, .env perms
make doctor      # connects and reports user / role / account / version
```

`check-env` exits non-zero on placeholders, missing keys, or a missing
private key file, so it is usable as a CI gate.

---

# 2. Load the corpus

## Run it

One command does the whole corpus:

```bash
make pipeline
```

Or step by step:

| Command | Does | Expected |
|---|---|---|
| `make download` | Fetch `CUADv1.json` + `category_descriptions.csv` into `data/cuad/` | 510 contracts, 13,823 spans, 41 categories |
| `make build` | Write the 8 NDJSON load files + both manifests | 510 / 510 / 13,823 / 41 and the dimensions |
| `make setup` | Create `CUAD_WH`, `CUAD_DB.CORPUS`, the tables, stage, `APP_USERS` | objects created |
| `make load` | `PUT` + `COPY INTO` all eight data tables | 8x `LOADED`, 0 errors |
| `make views` | Create the corpus views and `ACCESS_LOG` | views + log created |
| `make grants` | Create `STREAMLITWEB_ROLE` and apply its grants | role + grants applied |
| `make service-user` | Create the `STREAMLITWEB` user, key pair, `.env.service` | service identity ready |
| `make users` | Seed 3 lawyers + 1 auditor + 1 admin, write `credentials.txt` | 5 logins |
| `make verify` | Assert counts, integrity, roles and parse rates | `all checks passed` |
| `make verify-privileges` | Assert the service identity is least-privilege | `least-privilege` |

`make pipeline` runs download → build → setup → load → views → grants →
service-user → users → verify, so a rebuild leaves a **usable** system: corpus
loaded, service identity provisioned, logins seeded, everything verified.

`make users` is idempotent — it only creates missing accounts. That matters
after `make teardown`, which drops `APP_USERS` with the database: the next
`make pipeline` recreates all five logins with **new passwords** and rewrites
`credentials.txt`. Plan for that rather than being surprised by it.

`make download` and `make build` need no Snowflake access. `make verify`
exits non-zero on any mismatch, so it works as a gate.

## Data model

```
CUAD_DB.CORPUS
  -- as loaded ---------------------------------------------------------------
├── CONTRACTS                510  (DOC_ID, TITLE, CHAR_LEN)
├── CONTRACT_TEXT            510  (DOC_ID, FULL_TEXT)          -- whole-doc search
├── CLAUSES               13,823  one row per answer span
│                                 (CLAUSE_ID, DOC_ID, CATEGORY, QUESTION,
│                                  ANSWER_TEXT, ANSWER_START, ANSWER_END)
├── CLAUSE_CATEGORIES         41  (CATEGORY, DESCRIPTION, ANSWER_FORMAT, GRP)
├── APP_USERS                  5  logins: role + status + PBKDF2 hash only
├── ACCESS_LOG                    every login, search, document view and admin action
  -- derived by scripts/build_dimensions.py ----------------------------------
├── CONTRACT_DIM             510  DOC_TYPE, AGREEMENT_YEAR, JURISDICTION, CLAUSE_COUNT
├── CONTRACT_PARTY           915  parsed counterparties
├── RELATED_DOC            2,430  top 5 related per contract, with reasons
├── CATEGORY_STATS            41  DISTINCT documents per clause category
  -- views -------------------------------------------------------------------
├── V_CONTRACT_METADATA           document register pivoted from clause answers
├── V_CONTRACT_CATEGORY_STATUS    every doc x category, FOUND + SPAN_COUNT
├── V_CONTRACT_BROWSE             register + derived dimensions, one row per doc
├── V_FACET_TYPE / _YEAR / _JURISDICTION / _PARTY    facet values with counts
├── V_CATEGORY_INDEX              clause index: contracts per category
└── V_RELATED_DOC                 related docs joined to title, type, year
```

Things worth knowing:

- **There is no metadata column in CUAD.** Parties, dates and governing law
  exist only as clause answers. Everything in the derived tables is *parsed*
  out of free text, which is why parse rates matter (below).
- **`CLAUSES` holds one row per answer span**, not per question. 20,910
  questions produce 13,823 spans; unanswered questions carry nothing to search.

## Loading notes

- **NDJSON, not CSV.** Contract text contains embedded newlines, quotes and
  commas. Snowflake's JSON loader handles that natively; CSV does not.
- **Category names disagree between the two source files.** `CUADv1.json`
  title-cases them (`Notice Period To Terminate Renewal`) while
  `category_descriptions.csv` does not (`...to...`). Ten categories differ.
  `build_load_files.py` normalizes case-insensitively and stores the CSV
  spelling, so `CLAUSES.CATEGORY` joins cleanly to `CLAUSE_CATEGORIES`.
- **`make load` truncates before copying**, so re-running replaces rather than
  appends. `PUT ... OVERWRITE = TRUE` replaces the staged file.
- An empty `APP_USERS` is a real failure mode: the app runs, the connection
  works, and every login is rejected. The login screen now says so explicitly
  rather than reporting "invalid password", and `make pipeline` seeds the
  logins so a rebuild cannot leave you there.
- Offsets are validated at build time: every span is checked against
  `context[answer_start:answer_end]` and the build fails on mismatch.

## Running SQL by hand

No connection config needed; the Makefile exports `.env` and uses
`snow --temporary-connection` (`-x`), which reads the generic
`SNOWFLAKE_*` variables directly. `DATABASE`/`SCHEMA`/`WAREHOUSE` are unset
for the connection so that pre-setup runs do not fail; every SQL file sets
them explicitly.

```bash
make sql FILE=sql/00_setup.sql
make query Q='select current_user()'
```

## Reset

```bash
make teardown    # DROP DATABASE CUAD_DB; DROP WAREHOUSE CUAD_WH
make clean-stage # empty @CUAD_LOAD, keep the data
```

---

# 3. Application

## Demo logins

```bash
make users          # create lawyer-001..003, write credentials.txt
FORCE=1 make users  # rotate all three passwords
```

| Username | Name | Role |
|---|---|---|
| `lawyer-001` | Ada Whitfield | lawyer |
| `lawyer-002` | Marcus Iyer | lawyer |
| `lawyer-003` | Noor Castellanos | lawyer |
| `admin` | Sasha Lindqvist | admin |
| `auditor` | Tomas Beck | auditor |

- Passwords are 16 random characters, printed to the terminal once and
  written to `credentials.txt` (mode `600`, gitignored).
- Only a salted **PBKDF2-SHA256** hash (200,000 iterations) is stored, in
  `CUAD_DB.CORPUS.APP_USERS`. Nothing reversible reaches Snowflake.
- Re-running without `FORCE=1` leaves existing passwords untouched.

These are **app-level logins, deliberately not Snowflake users.** The app
connects with the single role from `.env`, so per-lawyer Snowflake users
would add MFA friction without adding isolation. The reasoning is in the
header comment of `sql/04_users.sql`.

## Run the UI

```bash
make app              # http://localhost:8501
make app PORT=8502    # different port
```

Sign in with a username and the password from `credentials.txt`.

### What the UI does

Four index pages, all drilling into one filtered register, plus a document page.
Navigation lives in the URL, so `?nav=contracts&clause=Source%20Code%20Escrow`
is a working link (you sign in, then land on the filtered result).

| Page | Shows | Selecting a row |
|---|---|---|
| **Contracts** | the register, with facets: clause categories, type, jurisdiction, decade, counterparty | opens the document |
| **Clauses** | the 41 categories with distinct-document counts (13 → 510) | filters the register to that clause |
| **Types** | agreement types with counts, long tail included | filters the register to that type |
| **Parties** | counterparties appearing in ≥ 2 contracts | filters the register to that party |

**Contract detail** shows type, year, jurisdiction, clause coverage
(`13 of 41`), and three tabs: *Clauses* (each span with ~260 characters of
context), *Checklist* (all 41 categories, present or not), and *Full text*
(annotated, capped at 200,000 characters, downloadable).

**Related contracts** at the bottom of each document, top 5, each with the
reasons it scored:

```
score = 3 × shared counterparty
      + 3 × Jaccard overlap of the 41-category signature
      + 2 × same agreement type
      + 1 × same jurisdiction
      + 1 × agreement year within ±1        (minimum score 3)
```

Search hits highlight green, clause spans amber. All contract text is
HTML-escaped, every query is parameterised, and raw HTML goes through
`st.html` rather than `st.markdown` — contract text contains blank lines,
and those end Markdown's HTML block, which would leak the rest of a snippet
as literal tags.

### Derived dimensions and their parse rates

`scripts/build_dimensions.py` parses the free-text answers, and `make verify`
reports the rates so a regression is visible:

| Dimension | Parsed | Note |
|---|---|---|
| Agreement type | 500/510 (98%) | from the annotated contract name; 207 distinct types, top 20 cover 50% |
| Agreement year | 450/510 (88%) | handles `June 21, 1999`, `9/21/98`, `14t h day of April, 2015` |
| Jurisdiction | 404/510 (79%) | `State of New York` and `laws of England` both normalize to one value; the designation is stripped |

Counterparty is the honest weak spot: 915 parsed names, of which only **29
appear in more than one contract**. CUAD's party field is free text that mixes
entity names with role labels (`Licensor`, `Party A`, `INDIVIDUALLY`), so a
role stoplist gets the obvious ones and the rest is noise. That is why Parties
lists only the ≥ 2 names and why counterparty contributes to just 71 of the
2,430 related-document rows — related documents are driven by clause overlap
and agreement type.

Unparseable values are never dropped: they become `Unclassified` / `Not
stated` and stay selectable facets.

### What it does not do

No semantic or vector search, no relevance ranking, no summarisation, no PDF
rendering (CUAD ships text, not PDFs), no clients or matters (CUAD has none),
and no per-document scoping — every lawyer sees the whole corpus. Roles
control which *pages* you get, not which contracts.

---

# 4. Roles, admin and audit

## Roles

One `APP_ROLE` column on `APP_USERS`, three values, no roles table:

| Role | Pages |
|---|---|
| `lawyer` | Contracts / Clauses / Types / Parties |
| `auditor` | Reports only |
| `admin` | everything, plus Admin |

The sidebar only renders pages your role reaches, and every privileged page
calls `auth.require_role(...)` as a backstop for direct URL access. An auditor
who pastes `?nav=contracts` gets "Not authorised" rather than the register.

`APP_ROLE` is named that way on purpose: a column literally called `ROLE` is
fine in `CREATE TABLE` but Snowflake rejects it in `ALTER TABLE ... ADD
COLUMN`. A related trap, documented in `sql/04_users.sql`: `ADD COLUMN IF NOT
EXISTS ... NOT NULL DEFAULT` fails with "ambiguous column name" when the
column already exists, so the upgrade path uses plain `ADD COLUMN IF NOT
EXISTS` plus an explicit backfill.

## Admin console

Three actions, all audited:

- **Create user** — username, display name, role. The password is generated
  once and shown once; it is never written anywhere.
- **Suspend / reactivate** — a status change, never a delete, so `ACCESS_LOG`
  rows keep resolving. It takes effect on the target's next rerun, and
  `SUSPENDED_AT` / `SUSPENDED_BY` record who did it.
- **Reset password** — new salt and hash, new password shown once.

You cannot suspend your own account: last-admin lockout is unrecoverable
through the UI.

## Access reporting

The auditor and admin get four reports over a date range, each with a CSV
download:

| Report | Shows |
|---|---|
| Logins | per username: events, successes, failures, last success |
| Logins | recent failed attempts, with attempted username and reason |
| Searches | most frequent terms, number of users, last search |
| Documents | most accessed contracts, viewers, last view |
| Activity | every event in the range |

Generating a report writes a `REPORT_RUN` event: an auditor auditing
themselves is the correct behaviour.

## The audit log

One table, `ACCESS_LOG`, discriminated by `EVENT_TYPE`, rather than a table per
event. Nullable columns are deliberate: `ACTOR_ROLE` is null when there is no
session, `DOC_ID` only applies to `DOCUMENT_VIEW`, and `DETAIL` carries a
search term or an admin action's target.

```
LOGIN_SUCCESS  LOGIN_FAILURE  LOGOUT  SESSION_REVOKED
SEARCH         DOCUMENT_VIEW  REPORT_RUN
USER_CREATED   USER_SUSPENDED USER_REACTIVATED PASSWORD_RESET
```

Writes happen at four chokepoints only: `auth.check_login` and the sign-out
button, the search form (once per submitted search, not per keystroke), the
document page, and the admin actions.

Two details that matter:

- **Streamlit re-runs the script on every interaction.** `page_document()`
  compares the open `doc_id` against `st.session_state.last_doc` before
  logging; without that guard, one viewed contract produces dozens of rows.
  Report generation uses the same pattern.
- **Passwords are never recorded.** A failed login stores the attempted
  username verbatim but truncated to 64 characters — useful forensics, and the
  only field a mistyped password could ever land in.

### Trust boundary

There are no aggregation views: every report is date filtered, so aggregation
lives in `app/reports.py` where the cutoff is a parameter. Query `ACCESS_LOG`
directly for ad-hoc analysis:

```sql
SELECT ACTOR, COUNT_IF(EVENT_TYPE = 'LOGIN_FAILURE') AS FAILURES
FROM ACCESS_LOG GROUP BY ACTOR ORDER BY FAILURES DESC;
```

Everything runs on one service role, so this log records what the
*application* did. It is not tamper-proof against anyone holding that role's
credentials, and it cannot audit lawyers the way Snowflake's own
`LOGIN_HISTORY` / `ACCESS_HISTORY` would: from Snowflake's point of view, all
five logins are the same user.

---


# 5. Least privilege

Everything up to here ran the app as `ACCOUNTADMIN`. It now runs as a
purpose-built service identity that can read the corpus, append audit rows and
manage app users - and nothing else.

## Three layers

| # | Identity | Lives in | Held by | Can do |
|---|---|---|---|---|
| 1 | `ACCOUNTADMIN` | Snowflake | you, the human | **Onboarding only.** `make` - DDL, grants, seeding, teardown |
| 2 | `STREAMLITWEB` (user) + `STREAMLITWEB_ROLE` (role) | Snowflake | the app | Read the corpus and views, append audit rows, manage app users |
| 3 | `lawyer-001/002/003`, `admin`, `auditor` | application (`APP_USERS`) | people in a browser | Sign in to the app |

Two things about layer 3 worth stating plainly:

- **It is not a Snowflake layer.** All five logins share layer 2's single
  session. Snowflake sees exactly one user, `STREAMLITWEB`.
- Therefore **Snowflake RBAC cannot separate one lawyer from another**, and
  `LOGIN_HISTORY` will never show a lawyer logging in. That separation lives in
  the app (the `APP_ROLE` column plus `require_role()`), which is why
  `ACCESS_LOG` exists.

## The grants

`sql/08_grants.sql`, applied by `make grants`:

| Object | Granted | Withheld, deliberately |
|---|---|---|
| warehouse, database, schema | `USAGE` | - |
| all + future tables and views | `SELECT` | - |
| `APP_USERS` | `INSERT`, `UPDATE` | **`DELETE`** - suspension is a status change, so "never delete a user" is enforced by privilege, not convention |
| `ACCESS_LOG` | `INSERT` | **`UPDATE`, `DELETE`** - an audit row the writer can rewrite is not an audit row |

Object privileges can only be granted to roles in Snowflake, which is why layer
2 is two objects wearing one name: the role carries the grants, the user
carries the authentication.

### Why the grants are re-applied every run

`make setup` uses `CREATE OR REPLACE TABLE`. Replacing a table **drops its
grants** - verified directly:

```
after GRANT, before replace          -> OWNERSHIP + SELECT
after CREATE OR REPLACE              -> OWNERSHIP only        <- grant gone
future grant, then CREATE OR REPLACE -> OWNERSHIP + SELECT    <- survives
```

So `make grants` is the last data step of `make pipeline`, and
`sql/08_grants.sql` includes `ON FUTURE TABLES/VIEWS`. Without those, every
pipeline run would silently revoke the app's access.

## The service identity

`make service-user` generates an RSA key pair and provisions the user:

- **Key-pair, no password.** A user with no password cannot be challenged for
  MFA and cannot sign in interactively at all.
- `DEFAULT_ROLE = STREAMLITWEB_ROLE`, `DEFAULT_WAREHOUSE = CUAD_WH`.
- `STATEMENT_TIMEOUT_IN_SECONDS = 60`, so a pathological query cannot pin the
  warehouse.
- Reuses an existing key unless `--force`, and re-syncs the public key onto the
  user on every run.

Files (both gitignored, mode 600):

```
keys/streamlitweb_key.p8    private key
keys/streamlitweb_key.pub   public key
.env.service                credentials for the app / server
```

## Running as the service identity

```bash
CUAD_ENV_FILE=.env.service make app
```

`CUAD_ENV_FILE` selects which credentials file the app reads. Locally it
defaults to `.env` (your `ACCOUNTADMIN` login, which is what `make` needs); on a
server, point it at `.env.service`. No renaming, no code edit.

## Proving it

```bash
make verify-privileges
```

Connects as `STREAMLITWEB` and asserts both directions: 16 statements the app
needs must succeed, and 10 it must never be able to run must be **denied**.

```
drop a corpus table      denied       truncate a corpus table   denied
insert a fake contract   denied       update a clause           denied
delete an app user       denied       rewrite an audit row      denied
delete an audit row      denied       create a table            denied
read account usage       denied       create a role             denied
insert into ACCESS_LOG   allowed (rolled back)
```

The insert is proved inside a transaction that is rolled back, so verifying the
grant does not pollute the audit log. Any denial that succeeds fails the command.

## Cost guardrails (one-time, not in the pipeline)

```sql
CREATE RESOURCE MONITOR CUAD_WH_MONITOR WITH CREDIT_QUOTA = 5
  TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE CUAD_WH SET RESOURCE_MONITOR = CUAD_WH_MONITOR;
```

Deliberately not in `make pipeline`: `CREATE OR REPLACE RESOURCE MONITOR` would
reset the credit counter on every run, so the quota could never trip.

---

# Layout

```
.env.example          template (committed)
.env                  onboarding credentials (gitignored, 600)
.env.service          STREAMLITWEB credentials for the app (gitignored, 600)
credentials.txt       demo passwords (gitignored, 600, written by make users)
requirements.txt      pinned deps
Makefile              bootstrap / doctor / corpus / users / app
.streamlit/
  config.toml         headless, no usage stats
sql/
  00_setup.sql        warehouse, database, schema
  01_tables.sql       nine tables, file format, stage
  02_load.sql         PUT + COPY for the corpus (rendered with the build path)
  03_views.sql        document register + category status
  04_users.sql        APP_USERS: roles, status, credentials (app logins)
  05_dimensions.sql   PUT + COPY for the derived dimensions
  06_dimension_views.sql  register, facet, clause index and related-doc views
  07_audit.sql        ACCESS_LOG (one table, event-typed)
  08_grants.sql       STREAMLITWEB_ROLE and its grants
  99_teardown.sql     drop user, role, database and warehouse
scripts/
  bootstrap.sh        venv + install + seed .env
  manage_keypair.py   generate + register the admin key pair (either-or .env)
  envcheck.py         .env validation + connection test
  download_cuad.py    fetch CUAD artifacts
  build_load_files.py CUADv1.json -> NDJSON
  build_dimensions.py clause text -> type, year, jurisdiction, counterparties, related
  verify_load.py      assert counts, integrity and parse rates
  create_users.py     seed 3 lawyers + auditor + admin, write credentials.txt
  credentials.py      password generation and PBKDF2 hashing (shared)
  create_service_user.py  STREAMLITWEB user + key pair + .env.service
  resolve_auth.py     decide which credential the snow CLI should use
  snow.sh             snow wrapper: load .env, resolve auth, exec
  verify_privileges.py    prove the service identity is least-privilege
  sf.py               shared connection helper (env_file selectable)
app/
  streamlit_app.py    login gate, role routing, index pages, document view
  auth.py             check_login + require_role
  admin.py            users table, create / suspend / reset
  reports.py          four access reports with CSV export
  audit.py            the single audit write path
  queries.py          every corpus query the UI runs
  db.py               cached connection + query helpers
data/cuad/             downloaded source (gitignored)
build/                generated NDJSON + manifest (gitignored)
keys/                 private keys (gitignored, 700)
  snowflake_key.p8      optional, for your own admin key-pair auth
  streamlitweb_key.p8   the service identity's key
```

# Notes

- `snowflake-connector-python` is pinned to `4.7.5` because that is what
  `snowflake-cli 3.29.0` requires. Do not bump it independently.
- `.env` is parsed by `python-dotenv` for Python tools and by `bash`
  `source` for Make targets. Keep values free of spaces and unquoted `#`.
- The app connects as the role in `.env` (`ACCOUNTADMIN` by default). That
  is fine for a throwaway trial and wrong for anything real: a dedicated
  role with `USAGE` on the warehouse and `SELECT` on the five tables and
  two views is the correct shape.
- CUAD data is CC BY 4.0, from The Atticus Project. Clause spans are expert
  annotations, not model output. This is a demo, not legal advice.
- The service identity is a normal user with key-pair auth and no password.
  `TYPE = SERVICE` is the stricter variant if your account allows it and you
  want interactive login forbidden outright - worth verifying before relying
  on it.
- `.env.service` is generated, so do not edit it by hand: re-run
  `make service-user` after rotating the key (`--force`) or changing the
  account.
- The two identities are independent. Rotating the admin key with
  `FORCE=1 make keypair` does not touch `STREAMLITWEB`, and `FORCE=1 make
  service-user` does not touch yours.
- `SNOWFLAKE_AUTHENTICATOR` is optional and only sets which credential is tried
  first. It is not a filter: the other one is still attempted.
- `sf.py` pins the Snowflake session to `TIMEZONE = 'UTC'` so `CREATED_AT` and
  `ACCESS_LOG.EVENT_TS` are comparable with UTC report cutoffs instead of
  inheriting the account's default session timezone.
- Audit logging never breaks the app: a failed insert is reported to stderr and
  swallowed, because an audit table that can block a login is worse than a
  missing row.
