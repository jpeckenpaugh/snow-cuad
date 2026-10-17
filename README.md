# snow-cuad

Phase-1 POC: load the CUAD contract corpus into Snowflake and expose a
lawyer-facing search UI with three demo logins.

## Current status

**Step 1 of N complete: local environment + credentials.**

- [x] Python 3.14 virtualenv
- [x] Snowflake CLI + Python connector in `.venv`
- [x] `.env`-driven auth (no `config.toml`, no global state)
- [ ] Download CUAD JSON
- [ ] Build load files
- [ ] Snowflake objects + load
- [ ] Demo users
- [ ] Streamlit app

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
Makefile              bootstrap / doctor / sql / query
scripts/
  bootstrap.sh        venv + install + seed .env
  gen_keypair.sh      RSA key pair + ALTER USER statement
  envcheck.py         .env validation + connection test
keys/                 private keys (gitignored, 700)
data/                 CUAD download (gitignored)
build/                generated load files (gitignored)
```

## Notes

- `snowflake-connector-python` is pinned to `4.7.5` because that is what
  `snowflake-cli 3.29.0` requires. Do not bump it independently.
- `.env` is parsed by `python-dotenv` for Python tools and by `bash`
  `source` for Make targets. Keep values free of spaces and unquoted `#`.
