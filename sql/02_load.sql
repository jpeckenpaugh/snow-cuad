-- Step 2c: upload NDJSON and load the four tables.
-- Run with: make load   (renders __BUILD_DIR__, then executes via `snow sql`)
--
-- TRUNCATE first so re-running is idempotent: PUT with OVERWRITE replaces the
-- staged file, and COPY would otherwise append a second copy of every row.

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

TRUNCATE TABLE IF EXISTS CLAUSES;
TRUNCATE TABLE IF EXISTS CONTRACT_TEXT;
TRUNCATE TABLE IF EXISTS CONTRACTS;
TRUNCATE TABLE IF EXISTS CLAUSE_CATEGORIES;

PUT file://__BUILD_DIR__/contracts.ndjson      @CUAD_LOAD/contracts/      OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/contract_text.ndjson  @CUAD_LOAD/contract_text/  OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/clauses.ndjson        @CUAD_LOAD/clauses/        OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/categories.ndjson     @CUAD_LOAD/categories/     OVERWRITE = TRUE AUTO_COMPRESS = TRUE;

COPY INTO CONTRACTS (DOC_ID, TITLE, CHAR_LEN)
FROM (
  SELECT $1:doc_id::STRING, $1:title::STRING, $1:char_len::NUMBER
  FROM @CUAD_LOAD/contracts/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO CONTRACT_TEXT (DOC_ID, FULL_TEXT)
FROM (
  SELECT $1:doc_id::STRING, $1:full_text::STRING
  FROM @CUAD_LOAD/contract_text/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAUSES (CLAUSE_ID, DOC_ID, CATEGORY, QUESTION, ANSWER_TEXT, ANSWER_START, ANSWER_END)
FROM (
  SELECT
    $1:clause_id::STRING,
    $1:doc_id::STRING,
    $1:category::STRING,
    $1:question::STRING,
    $1:answer_text::STRING,
    $1:answer_start::NUMBER,
    $1:answer_end::NUMBER
  FROM @CUAD_LOAD/clauses/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAUSE_CATEGORIES (CATEGORY, DESCRIPTION, ANSWER_FORMAT, GRP)
FROM (
  SELECT
    $1:category::STRING,
    $1:description::STRING,
    $1:answer_format::STRING,
    $1:grp::STRING
  FROM @CUAD_LOAD/categories/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;
