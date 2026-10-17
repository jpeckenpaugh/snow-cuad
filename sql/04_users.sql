-- Step 3a: demo application logins.
-- Run with: make users
--
-- These are APP-level logins, not Snowflake users. The Streamlit app
-- authenticates against this table and connects to Snowflake with the single
-- role from .env. Real Snowflake users would hit MFA-on-password and cannot
-- be impersonated by a shared app session.
--
-- Only PBKDF2 hashes are stored; plaintext passwords live in credentials.txt
-- (gitignored) and are written once at creation time.

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

CREATE TABLE IF NOT EXISTS APP_USERS (
  USERNAME      STRING NOT NULL,
  DISPLAY_NAME  STRING NOT NULL,
  SALT          STRING NOT NULL,
  PWD_HASH      STRING NOT NULL,
  ITERATIONS    NUMBER NOT NULL,
  CREATED_AT    TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT PK_APP_USERS PRIMARY KEY (USERNAME)
);
