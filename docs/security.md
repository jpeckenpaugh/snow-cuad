# Security

The interesting problem here is that an application-level login system sits
inside a Snowflake account. That gives three layers of identity, only two of
which Snowflake knows about.

## Three layers

| # | Identity | Lives in | Held by | Can do |
|---|---|---|---|---|
| 1 | `ACCOUNTADMIN` | Snowflake | you, the human | **Onboarding only.** `make` — DDL, grants, seeding, teardown |
| 2 | `STREAMLITWEB` (user) + `STREAMLITWEB_ROLE` (role) | Snowflake | the app | Read the corpus and views, append audit rows, manage app users |
| 3 | the five logins in `APP_USERS` | application | people in a browser | Sign in to the app |

Two consequences of layer 3 that are worth stating plainly:

- **It is not a Snowflake layer.** All five logins share layer 2's single
  session. Snowflake sees exactly one user, `STREAMLITWEB`.
- Therefore **Snowflake RBAC cannot separate one lawyer from another**, and
  `LOGIN_HISTORY` will never show a lawyer logging in. That separation lives in
  the app (the `APP_ROLE` column plus `require_role()`), which is exactly why
  `ACCESS_LOG` exists.

Object privileges can only be granted to roles in Snowflake, which is why layer
2 is two objects wearing one name: the role carries the grants, the user carries
the authentication.

## The grants

`sql/08_grants.sql`, applied by `make grants`:

| Object | Granted | Withheld, deliberately |
|---|---|---|
| warehouse, database, schema | `USAGE` | — |
| all + future tables and views | `SELECT` | — |
| `APP_USERS` | `INSERT`, `UPDATE` | **`DELETE`** — suspension is a status change, so "never delete a user" is enforced by privilege rather than convention |
| `ACCESS_LOG` | `INSERT` | **`UPDATE`, `DELETE`** — an audit row the writer can rewrite is not an audit row |

Without the `USAGE` grants the app authenticates successfully and then fails on
its first query, which is a confusing way to lose twenty minutes.

### Why the grants are re-applied on every run

`make setup` uses `CREATE OR REPLACE TABLE`, and replacing a table **drops its
grants**. Verified directly:

```
after GRANT, before replace          -> OWNERSHIP + SELECT
after CREATE OR REPLACE              -> OWNERSHIP only        <- grant gone
future grant, then CREATE OR REPLACE -> OWNERSHIP + SELECT    <- survives
```

So `make grants` is the last data step of `make pipeline`, and the file includes
`ON FUTURE TABLES/VIEWS`. Without those, every pipeline run would silently
revoke the app's access and you would not find out until a query failed.

## The service identity

`make service-user` generates an RSA key pair and provisions the user:

- **Key-pair, no password.** A user without a password cannot be challenged for
  MFA and cannot sign in interactively at all.
- `DEFAULT_ROLE = STREAMLITWEB_ROLE`, `DEFAULT_WAREHOUSE = CUAD_WH`.
- `STATEMENT_TIMEOUT_IN_SECONDS = 60`, so a pathological query cannot pin the
  warehouse.
- Reuses an existing key unless `FORCE=1`, and re-syncs the public key onto the
  user on every run.

Files (gitignored, mode 600):

```
keys/streamlitweb_key.p8    private key
keys/streamlitweb_key.pub   public key
.env.service                credentials for the app / server
```

### How key-pair auth works

The key is generated **once**, not per step or per session:

- the **private** half never leaves the machine
- the **public** half is registered on the Snowflake user
- each connection derives a short-lived **JWT** signed with the private key,
  which Snowflake verifies against the stored public key

No secret is transmitted, and because this is not password auth the account's
MFA-for-passwords policy does not apply — which is what lets `make` run
unattended.

Snowflake keeps two key slots (`RSA_PUBLIC_KEY` and `RSA_PUBLIC_KEY_2`), which
is what makes rotation non-destructive: the new key is proven in the spare slot
before it replaces the live one.

### Either or, never one or the other

`.env` carries **both** a key path and a password, and both stay valid. The
tooling tries key-pair first and falls back to the password, so a key that is
rotated, unregistered or missing degrades to a slower login instead of a
lockout. The fallback is reported rather than hidden:

```
warning: fell back to password auth (key-pair: 390144 (28000): ... JWT token is invalid)
```

The Snowflake CLI has no fallback of its own — given a private key and no
authenticator it refuses outright — so `scripts/snow.sh` resolves which
credential works before each invocation and hands the CLI exactly one.

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

Connects as `STREAMLITWEB` and asserts both directions: **16 statements the app
needs must succeed, and 10 it must never be able to run must be denied.**

```
drop a corpus table      denied       truncate a corpus table   denied
insert a fake contract   denied       update a clause           denied
delete an app user       denied       rewrite an audit row      denied
delete an audit row      denied       create a table            denied
read account usage       denied       create a role             denied
insert into ACCESS_LOG   allowed (rolled back)
```

The insert is proved inside a transaction that is rolled back, so verifying the
grant does not pollute the audit log. Any denial that succeeds fails the
command.

## Trust boundary

The audit log is application-level. Writes go through the same service role the
app uses, so it records what the **application** did — it is not tamper-proof
against anyone holding that role's credentials.

It also cannot audit lawyers the way Snowflake's own `LOGIN_HISTORY` and
`ACCESS_HISTORY` would, because from Snowflake's point of view all five logins
are one user. That is the price of application-level authentication, and it is
why `ACCESS_LOG` has to exist.

## Cost guardrails (one-time, not in the pipeline)

```sql
CREATE RESOURCE MONITOR CUAD_WH_MONITOR WITH CREDIT_QUOTA = 5
  TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE CUAD_WH SET RESOURCE_MONITOR = CUAD_WH_MONITOR;
```

Deliberately not in `make pipeline`: `CREATE OR REPLACE RESOURCE MONITOR` would
reset the credit counter on every run, so the quota could never trip.

If you ever expose this beyond localhost, do that first — and note that the
password fallback in `.env` is an `ACCOUNTADMIN` credential. A public deployment
should carry only `.env.service`.
