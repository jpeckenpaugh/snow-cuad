# Operations

The playbook: prerequisites, every command, and the full teardown / rebuild
cycle.

## Prerequisites

- Python 3.14 (`python3.14` on `PATH`)
- `openssl` (ships with macOS/Linux)
- A Snowflake account. A trial is fine.
- Docker — only for `make demo-video`

## First run

```bash
make bootstrap     # venv, dependencies, .env from .env.example
$EDITOR .env       # account identifier, login, password
make doctor        # prove the connection works
make pipeline      # corpus + service identity + logins + verification
make app           # http://localhost:8501
```

### Why Python 3.14

`snowflake-cli 3.29.0` is a pure-Python wheel (`>=3.10`), and every binary
dependency it pins has cp314 wheels — `snowflake-connector-python 4.7.5`,
`cryptography`, `pydantic-core`, `cffi`. Streamlit's tree (pyarrow, numpy,
pandas) resolves too, though pyarrow must be held at **23.0.1**: the connector
rejects `>=24`, and Streamlit would otherwise pull the newest. That pin is in
`requirements.txt` and is not cosmetic.

`.env` needs an account identifier — from the Snowflake UI's bottom-left account
menu — your login name, and a password. It deliberately does **not** need a
warehouse; the objects do not exist yet, and every SQL file names the warehouse
explicitly.

`make pipeline` ends with `all checks passed` and writes `credentials.txt` in the
repo root (mode 600, gitignored) with the five logins.

## Every target

| Command | Does | Expected |
|---|---|---|
| `make bootstrap` | Create `.venv` (Python 3.14), install deps, seed `.env` | versions printed |
| `make check-env` | Validate `.env` offline | `env OK` |
| `make doctor` | Validate `.env` and connect | `connection OK` |
| `make keypair` | Generate **and register** an admin key pair, switch `.env` | `verified key-pair login` |
| `make download` | Fetch `CUADv1.json` + `category_descriptions.csv` into `data/cuad/` | 510 / 13,823 / 41 |
| `make build` | Write 8 NDJSON load files + manifests | parse rates printed |
| `make setup` | Create warehouse, database, schema, tables, stage, `APP_USERS` | objects created |
| `make load` | `PUT` + `COPY INTO` all eight data tables | 8× `LOADED`, 0 errors |
| `make views` | Create the corpus views and `ACCESS_LOG` | views + log created |
| `make grants` | Create `STREAMLITWEB_ROLE` and apply its grants | role + grants applied |
| `make service-user` | Create the `STREAMLITWEB` user, key pair, `.env.service` | service identity ready |
| `make users` | Seed 3 lawyers + 1 auditor + 1 admin, write `credentials.txt` | 5 logins |
| `make verify` | 21 integrity checks, 8 table counts, parse rates | `all checks passed` |
| `make verify-privileges` | 16 allowed + 10 denied statements as the service user | `least-privilege` |
| `make pipeline` | All of the above, in order | `all checks passed` |
| `make app` | Run the Streamlit UI (`PORT=8501`) | localhost URL |
| `make demo-video` | Build the demo video in Docker | `build/demo/demo-720p.mp4` |
| `make sql FILE=…` | Run a SQL file through the `snow` CLI | — |
| `make query Q='…'` | Run one statement | — |
| `make clean-stage` | Empty the internal stage | — |
| `make teardown` | Drop database, warehouse, service user, role | four `dropped` |
| `make clean` | Remove `.venv` and `build/` | keeps `.env`, `keys/`, `data/` |

`make download` and `make build` need no Snowflake access. `make verify` exits
non-zero on any mismatch, so it works as a CI gate.

## Teardown and rebuild

```bash
make teardown      # stop `make app` first
make pipeline
```

`make pipeline` runs download → build → setup → load → views → grants →
service-user → users → verify, so a rebuild leaves a **usable** system: corpus
loaded, service identity provisioned, logins seeded, everything verified.

### What survives a teardown

| Survives | Removed |
|---|---|
| `.env`, `.env.service` | `CUAD_DB` — with every table, view, `APP_USERS` and `ACCESS_LOG` |
| `keys/` (both key pairs) | `CUAD_WH` |
| `credentials.txt` (stale — see below) | the `STREAMLITWEB` user and role |
| `data/`, `build/`, `.venv` | |

Two things to plan for rather than be surprised by:

1. **The rebuild rotates all five passwords.** `APP_USERS` lives inside
   `CUAD_DB`, so teardown deletes it and the rebuild recreates the accounts from
   scratch and rewrites `credentials.txt`. Anyone holding an old password is out.
2. **Your keys are not regenerated.** The rebuild re-registers the same public
   keys, so `.env` and `.env.service` stay valid. Only if you delete `keys/`
   would you need `make keypair` again — and even then the rebuild still works,
   because the password fallback carries it.

`make teardown` is idempotent: running it when nothing exists is fine.

### Total reset, including local files

```bash
make teardown
make clean
rm -rf data/cuad keys credentials.txt .env .env.service
make bootstrap
```

That means re-entering your account identifier and login by hand, so it is only
worth doing when handing the repo to someone else.

## Troubleshooting

**Every login is rejected, but the app runs.** `APP_USERS` is empty — the
database was rebuilt without seeding logins. The login screen says so
explicitly; `make users` fixes it. (`make pipeline` now includes it.)

**`warning: fell back to password auth`.** The key pair is not registered or has
been rotated. Harmless in the sense that everything still works, but run
`make keypair` to restore key-pair auth.

**`JWT token is invalid`.** Same cause. `make keypair` re-registers the public
key using whichever credential currently works.

**A pipeline run fails partway.** `make setup` uses `CREATE OR REPLACE`, so a
failure after setup leaves the corpus tables empty. Simply re-run
`make pipeline` — it is idempotent.

**`no credentials in .env`.** Neither `SNOWFLAKE_PASSWORD` nor
`SNOWFLAKE_PRIVATE_KEY_PATH` is set. `make check-env` names the problem.

## Running SQL by hand

The Makefile loads `.env` and uses `snow --temporary-connection` (`-x`), which
reads the generic `SNOWFLAKE_*` variables. `DATABASE`/`SCHEMA`/`WAREHOUSE` are
unset for the connection so pre-setup runs do not fail; every SQL file sets them
explicitly.

```bash
make sql FILE=sql/00_setup.sql
make query Q='select current_user()'
```

## Where things live

```
data/cuad/     downloaded source (gitignored)
build/         generated NDJSON, manifests, demo video (gitignored)
keys/          private keys (gitignored, 700)
.env           onboarding credentials (gitignored, 600)
.env.service   service identity credentials (gitignored, 600)
credentials.txt  demo logins (gitignored, 600)
```
