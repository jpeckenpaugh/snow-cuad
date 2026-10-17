# snow-cuad

Phase-1 POC: load the CUAD contract corpus into Snowflake and expose a
lawyer-facing search UI with three demo logins.

CUAD (Contract Understanding Atticus Dataset) is 510 commercial contracts
annotated with 41 types of clauses a lawyer looks for during M&A diligence.
See <https://www.atticusprojectai.org/cuad>.

## Current status

**Step 4 of N complete: derived dimensions and a browsable UI.**

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
| `make build` | Write the 8 NDJSON load files + both manifests | 510 / 510 / 13,823 / 41 and the dimensions |
| `make setup` | Create `CUAD_WH`, `CUAD_DB.CORPUS`, 9 tables, stage | objects created |
| `make load` | `PUT` + `COPY INTO` all eight data tables | 8x `LOADED`, 0 errors |
| `make views` | Create the register, facet, clause index and related-doc views | 9 views created |
| `make verify` | Assert counts, integrity and parse rates | `all checks passed` |

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
├── APP_USERS                  3  demo logins (PBKDF2 hashes only)
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
and no per-user access control — all three lawyers see the whole corpus.

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
  01_tables.sql       nine tables, file format, stage
  02_load.sql         PUT + COPY for the corpus (rendered with the build path)
  03_views.sql        document register + category status
  04_users.sql        APP_USERS (app logins, not Snowflake users)
  05_dimensions.sql   PUT + COPY for the derived dimensions
  06_dimension_views.sql  register, facet, clause index and related-doc views
  99_teardown.sql     drop database and warehouse
scripts/
  bootstrap.sh        venv + install + seed .env
  gen_keypair.sh      RSA key pair + ALTER USER statement
  envcheck.py         .env validation + connection test
  download_cuad.py    fetch CUAD artifacts
  build_load_files.py CUADv1.json -> NDJSON
  build_dimensions.py clause text -> type, year, jurisdiction, counterparties, related
  verify_load.py      assert counts, integrity and parse rates
  create_users.py     three demo logins + credentials.txt
  sf.py               shared connection helper
app/
  streamlit_app.py    login gate, four index pages, document view, related docs
  queries.py          every query the UI runs
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
