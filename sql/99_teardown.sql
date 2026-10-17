-- Step 2f: remove everything this POC created.
-- Run with: make teardown
--
-- Drops the database, warehouse, and the service identity. The .env files,
-- downloaded data and generated build files are left alone.
--
-- Ordering matters: drop the user before the role.

DROP USER IF EXISTS STREAMLITWEB;
DROP ROLE IF EXISTS STREAMLITWEB_ROLE;

DROP DATABASE IF EXISTS CUAD_DB;
DROP WAREHOUSE IF EXISTS CUAD_WH;
