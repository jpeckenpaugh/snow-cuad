-- Step 2a: warehouse, database, schema.
-- Run with: make setup
--
-- Deliberately does NOT rely on SNOWFLAKE_DATABASE/SCHEMA being set on the
-- connection, because those objects do not exist on a first run.

CREATE WAREHOUSE IF NOT EXISTS CUAD_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'CUAD POC: small, aggressive auto-suspend';

CREATE DATABASE IF NOT EXISTS CUAD_DB
  COMMENT = 'CUAD POC: contract corpus';

CREATE SCHEMA IF NOT EXISTS CUAD_DB.CORPUS
  COMMENT = 'CUAD POC: contracts, clause labels, search';

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;
