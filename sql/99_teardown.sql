-- Step 2e: remove everything this POC created.
-- Run with: make teardown
--
-- Drops the database and warehouse only. The .env file, downloaded data and
-- generated build files are left alone.

DROP DATABASE IF EXISTS CUAD_DB;
DROP WAREHOUSE IF EXISTS CUAD_WH;
