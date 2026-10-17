-- Step 3a: application users: credentials, roles, status.
-- Run by: make setup (create) and make users (seed)
--
-- These are APP-level logins, not Snowflake users. The Streamlit app
-- authenticates against this table and connects to Snowflake with the single
-- role from .env, so from Snowflake's perspective there is only one user.
-- That is also why Snowflake's LOGIN_HISTORY / ACCESS_HISTORY cannot be used
-- to audit lawyers: they never touch Snowflake as themselves.
--
-- Suspension is a status change, never a delete: ACCESS_LOG rows reference
-- usernames and have to keep resolving.

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

-- IF NOT EXISTS (not CREATE OR REPLACE) so re-running setup keeps the users.
CREATE TABLE IF NOT EXISTS APP_USERS (
  USERNAME      STRING NOT NULL,
  DISPLAY_NAME  STRING NOT NULL,
  APP_ROLE      STRING NOT NULL DEFAULT 'lawyer',
  STATUS        STRING NOT NULL DEFAULT 'active',
  SALT          STRING NOT NULL,
  PWD_HASH      STRING NOT NULL,
  ITERATIONS    NUMBER NOT NULL,
  CREATED_AT    TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  SUSPENDED_AT  TIMESTAMP_NTZ,
  SUSPENDED_BY  STRING,
  CONSTRAINT PK_APP_USERS PRIMARY KEY (USERNAME)
);

-- Upgrade path for databases created before roles and status existed.
--
-- Deliberately plain ADD COLUMN IF NOT EXISTS with no NOT NULL / DEFAULT:
-- Snowflake rejects that combination with "ambiguous column name" when the
-- column is already present. Fresh tables get the constraints from the CREATE
-- above; upgraded tables get a backfill instead.
ALTER TABLE APP_USERS ADD COLUMN IF NOT EXISTS APP_ROLE     STRING;
ALTER TABLE APP_USERS ADD COLUMN IF NOT EXISTS STATUS       STRING;
ALTER TABLE APP_USERS ADD COLUMN IF NOT EXISTS SUSPENDED_AT TIMESTAMP_NTZ;
ALTER TABLE APP_USERS ADD COLUMN IF NOT EXISTS SUSPENDED_BY STRING;

UPDATE APP_USERS SET APP_ROLE = 'lawyer' WHERE APP_ROLE IS NULL;
UPDATE APP_USERS SET STATUS   = 'active' WHERE STATUS   IS NULL;
