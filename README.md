# snow-cuad

Phase-1 POC: load the CUAD contract corpus into Snowflake and expose a
lawyer-facing search UI with three demo logins.

CUAD (Contract Understanding Atticus Dataset) is 510 commercial contracts
annotated with 41 types of clauses a lawyer looks for during M&A diligence.
See <https://www.atticusprojectai.org/cuad>.

## Current status

**Step 3 of N complete: demo logins and the search UI.**

- [x] Python 3.14 virtualenv
- [x] Snowflake CLI + Python connector in `.venv`
- [x] `.env`-driven auth (no `config.toml`, no global state)
- [x] Download CUAD JSON
- [x] Build load files
- [x] Snowflake objects + load + verification
- [x] Demo users
- [x] Streamlit app

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

All auth flows through environment variables, which both `snow` and the
Python connector read. Nothing is written to `~/.snowflake/config.toml`,
so this repo never interferes with your other Snowflake work.

### Option A - key pair (recommended)

Recommended because Snowflake now enforces MFA for human users signing in
with passwords, which is awkward for scripted `snow sql` calls.

```bash
make bootstrap          # creates .env
make keypair            # writes keys/snowflake_key.p8, prints ALTER USER
```

Then in a Snowflake worksheet (as `ACCOUNTADMIN`, or a role that owns the
user), run the `ALTER USER ... SET RSA_PUBLIC_KEY='...'` statement that
`make keypair` printed. That has to be done out-of-band: the key is not
trusted yet, so the CLI cannot do it for you.

`.env` should contain:

```dotenv
SNOWFLAKE_ACCOUNT=myorg-myaccount
SNOWFLAKE_USER=MY_LOGIN
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_DATABASE=CUAD_DB
SNOWFLAKE_SCHEMA=CORPUS

SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT
SNOWFLAKE_PRIVATE_KEY_PATH=./keys/snowflake_key.p8
PRIVATE_KEY_PASSPHRASE=
```

### Option B - password

```dotenv
SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE
SNOWFLAKE_PASSWORD=...
```

May trigger an MFA prompt on every `snow` invocation. Fine for a one-off
trial, unpleasant in a loop.

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
| `make build` | Write `build/*.ndjson` + `manifest.json` | 510 / 510 / 13,823 / 41 rows |
| `make setup` | Create `CUAD_WH`, `CUAD_DB.CORPUS`, tables, stage | objects created |
| `make load` | `PUT` + `COPY INTO` the four tables | 4x `LOADED`, 0 errors |
| `make views` | Create `V_CONTRACT_METADATA`, `V_CONTRACT_CATEGORY_STATUS` | views created |
| `make verify` | Assert counts + referential integrity | `all checks passed` |

`make download` and `make build` need no Snowflake access. `make verify`
exits non-zero on any mismatch, so it works as a gate.

## Data model

```
CUAD_DB.CORPUS
├── CONTRACTS                510  (DOC_ID, TITLE, CHAR_LEN)
├── CONTRACT_TEXT            510  (DOC_ID, FULL_TEXT)          -- whole-doc search
├── CLAUSES               13,823  one row per answer span
│                                 (CLAUSE_ID, DOC_ID, CATEGORY, QUESTION,
│                                  ANSWER_TEXT, ANSWER_START, ANSWER_END)
├── CLAUSE_CATEGORIES         41  (CATEGORY, DESCRIPTION, ANSWER_FORMAT, GRP)
├── V_CONTRACT_METADATA      510  document register, pivoted from clause answers
└── V_CONTRACT_CATEGORY_STATUS    every doc x category, FOUND + SPAN_COUNT
```

Two things worth knowing:

- **There is no metadata column in CUAD.** Parties, dates and governing law
  exist only as clause answers, so `V_CONTRACT_METADATA` pivots 8 documentary
  categories out of `CLAUSES`. Coverage: parties 509/510, agreement date
  470/510, governing law 437/510.
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

| Username | Name |
|---|---|
| `lawyer-001` | Ada Whitfield |
| `lawyer-002` | Marcus Iyer |
| `lawyer-003` | Noor Castellanos |

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

**Search** (sidebar box, case-insensitive substring over clause answers):

- clause matches — contract, category, the matched clause text, `Open`
- contracts whose full text contains the term
- optional filter by any of the 41 clause categories

**Document view** (`Open` on any result):

- metadata header: parties, agreement/effective/expiration dates, renewal
  term, notice period, governing law
- coverage bar: how many of the 41 categories are present in that contract
- *Matched clauses* — each span with ~260 characters of surrounding context
- *Category checklist* — every category marked present or not present
- *Full text* — the whole contract with clause spans highlighted, plus a
  download button; rendering is capped at 200,000 characters

Search hits are highlighted in green, clause spans in amber. Contract text
is HTML-escaped before rendering, and every query is parameterised.

### What it does not do

No semantic search, no ranking, no summarisation, no PDF rendering (CUAD
ships text, not PDFs), and no per-matter access control — all three lawyers
see the whole corpus. Those are phase-2 decisions.

---


# Layout

```
.env.example          template (committed)
.env                  real values (gitignored, 600)
credentials.txt       demo passwords (gitignored, 600, written by make users)
requirements.txt      pinned deps
Makefile              bootstrap / doctor / corpus / users / app
.streamlit/
  config.toml         headless, no usage stats
sql/
  00_setup.sql        warehouse, database, schema
  01_tables.sql       tables, file format, stage
  02_load.sql         PUT + COPY (rendered with the build path)
  03_views.sql        document register + category status
  04_users.sql        APP_USERS (app logins, not Snowflake users)
  99_teardown.sql     drop database and warehouse
scripts/
  bootstrap.sh        venv + install + seed .env
  gen_keypair.sh      RSA key pair + ALTER USER statement
  envcheck.py         .env validation + connection test
  download_cuad.py    fetch CUAD artifacts
  build_load_files.py CUADv1.json -> NDJSON
  verify_load.py      assert counts and integrity
  create_users.py     three demo logins + credentials.txt
  sf.py               shared connection helper
app/
  streamlit_app.py    login gate, search, document view
  db.py               cached connection + query helper
data/cuad/             downloaded source (gitignored)
build/                generated NDJSON + manifest (gitignored)
keys/                 private keys (gitignored, 700)
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
