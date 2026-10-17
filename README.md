# snow-cuad

Phase-1 POC: load the CUAD contract corpus into Snowflake and expose a
lawyer-facing search UI with three demo logins.

## Current status

**Step 2 of N complete: the corpus is in Snowflake.**

- [x] Python 3.14 virtualenv
- [x] Snowflake CLI + Python connector in `.venv`
- [x] `.env`-driven auth (no `config.toml`, no global state)
- [x] Download CUAD JSON
- [x] Build load files
- [x] Snowflake objects + load + verification
- [ ] Demo users
- [ ] Streamlit app

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


## Prerequisites

- Python 3.14 (`python3.14` on `PATH`)
- `openssl` (ships with macOS/Linux)
- A Snowflake account. Trial is fine.

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

## Verify

```bash
make check-env   # offline: required keys, placeholders, key file, .env perms
make doctor      # connects and reports user / role / account / version
```

`check-env` exits non-zero on placeholders, missing keys, or a missing
private key file, so it is usable as a CI gate.

## Running SQL

No connection config needed; the Makefile exports `.env` and uses
`snow --temporary-connection` (`-x`), which reads the generic
`SNOWFLAKE_*` variables directly.

```bash
make sql FILE=sql/00_setup.sql
make query Q='select current_user()'
```

## Layout

```
.env.example          template (committed)
.env                  real values (gitignored, 600)
requirements.txt      pinned deps
Makefile              bootstrap / doctor / download / build / load / verify
sql/
  00_setup.sql        warehouse, database, schema
  01_tables.sql       tables, file format, stage
  02_load.sql         PUT + COPY (rendered with the build path)
  03_views.sql        document register + category status
  99_teardown.sql     drop database and warehouse
scripts/
  bootstrap.sh        venv + install + seed .env
  gen_keypair.sh      RSA key pair + ALTER USER statement
  envcheck.py         .env validation + connection test
  download_cuad.py    fetch CUAD artifacts
  build_load_files.py CUADv1.json -> NDJSON
  verify_load.py      assert counts and integrity
  sf.py               shared connection helper
data/cuad/             downloaded source (gitignored)
build/                generated NDJSON + manifest (gitignored)
keys/                 private keys (gitignored, 700)
```

## Notes

- `snowflake-connector-python` is pinned to `4.7.5` because that is what
  `snowflake-cli 3.29.0` requires. Do not bump it independently.
- `.env` is parsed by `python-dotenv` for Python tools and by `bash`
  `source` for Make targets. Keep values free of spaces and unquoted `#`.
