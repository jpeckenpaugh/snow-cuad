-- Step 3d: access audit log.
-- Run by: make views
--
-- One table, discriminated by EVENT_TYPE, rather than a table per event.
-- Nullable columns are deliberate: ACTOR/ACTOR_ROLE are null for events with no
-- session, DOC_ID only applies to DOCUMENT_VIEW, DETAIL carries the search
-- term or the admin action's target.
--
-- Known event types:
--   LOGIN_SUCCESS  LOGIN_FAILURE  LOGOUT  SESSION_REVOKED
--   ACCESS_DENIED  SEARCH         DOCUMENT_VIEW  REPORT_RUN
--   USER_CREATED   USER_SUSPENDED USER_REACTIVATED PASSWORD_RESET
--
-- There are deliberately no aggregation views here: every report is date
-- filtered, so the aggregation lives in app/reports.py where the cutoff can
-- be parameterised. Query ACCESS_LOG directly for ad-hoc analysis, e.g.
--   SELECT ACTOR, COUNT_IF(EVENT_TYPE='LOGIN_FAILURE') AS FAILURES
--   FROM ACCESS_LOG GROUP BY ACTOR ORDER BY FAILURES DESC;
--
-- Order by EVENT_TS, not EVENT_ID. EVENT_ID is an AUTOINCREMENT, and with
-- concurrent writers it is not monotonic against the clock: a handful of rows
-- sort in the opposite order to their timestamp, so `ORDER BY EVENT_ID DESC`
-- quietly misleads.
--
-- Writes go through the same service role the app uses, so this log is
-- application-level and not tamper-proof: it records what the app did, not
-- what a determined operator with the role's credentials could do.

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

CREATE TABLE IF NOT EXISTS ACCESS_LOG (
  EVENT_ID    NUMBER AUTOINCREMENT START 1 INCREMENT 1,
  EVENT_TS    TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  EVENT_TYPE  STRING NOT NULL,
  ACTOR       STRING,
  ACTOR_ROLE  STRING,
  SESSION_ID  STRING,
  DOC_ID      STRING,
  DETAIL      STRING
);
