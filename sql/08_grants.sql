-- Step 3e: the least-privilege role the app's Snowflake session uses.
-- Run by: make grants   (also the last data step of `make pipeline`)
--
-- The three auth layers:
--   1. ACCOUNTADMIN   the human; runs onboarding (DDL, users, grants)
--   2. STREAMLITWEB   the app's Snowflake user; holds STREAMLITWEB_ROLE
--   3. the 5 logins   application-level, all sharing layer 2's one session
--
-- Must be re-run after anything that uses CREATE OR REPLACE: replacing a
-- table drops its grants. That is why the FUTURE grants below exist.
--
-- Requires the ACCOUNTADMIN role and the objects from 00-07 to exist.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

CREATE ROLE IF NOT EXISTS STREAMLITWEB_ROLE
  COMMENT = 'Least privilege role for the Streamlit app (layer 2 of 3)';

-- Without these the app authenticates and then fails on its first query.
GRANT USAGE ON WAREHOUSE CUAD_WH        TO ROLE STREAMLITWEB_ROLE;
GRANT USAGE ON DATABASE  CUAD_DB        TO ROLE STREAMLITWEB_ROLE;
GRANT USAGE ON SCHEMA    CUAD_DB.CORPUS TO ROLE STREAMLITWEB_ROLE;

-- Read everything in the schema, now and in future.
GRANT SELECT ON ALL TABLES IN SCHEMA CUAD_DB.CORPUS TO ROLE STREAMLITWEB_ROLE;
GRANT SELECT ON ALL VIEWS  IN SCHEMA CUAD_DB.CORPUS TO ROLE STREAMLITWEB_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA CUAD_DB.CORPUS TO ROLE STREAMLITWEB_ROLE;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA CUAD_DB.CORPUS TO ROLE STREAMLITWEB_ROLE;

-- The only two writes the app performs.
--
-- APP_USERS deliberately has no DELETE: suspension is a status change, so
-- "never delete a user" is enforced by privilege rather than by convention.
-- ACCESS_LOG deliberately has no UPDATE or DELETE: an audit row that the
-- writer can rewrite is not an audit row.
GRANT INSERT, UPDATE ON TABLE CUAD_DB.CORPUS.APP_USERS  TO ROLE STREAMLITWEB_ROLE;
GRANT INSERT         ON TABLE CUAD_DB.CORPUS.ACCESS_LOG TO ROLE STREAMLITWEB_ROLE;
