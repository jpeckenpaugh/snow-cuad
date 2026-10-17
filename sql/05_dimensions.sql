-- Step 3b: load the derived navigation dimensions.
-- Run with: make load   (renders __BUILD_DIR__, then executes via `snow sql`)
--
-- Same shape as 02_load.sql: truncate, PUT with OVERWRITE, COPY INTO.

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

TRUNCATE TABLE IF EXISTS CONTRACT_DIM;
TRUNCATE TABLE IF EXISTS CONTRACT_PARTY;
TRUNCATE TABLE IF EXISTS RELATED_DOC;
TRUNCATE TABLE IF EXISTS CATEGORY_STATS;

PUT file://__BUILD_DIR__/contract_dim.ndjson    @CUAD_LOAD/contract_dim/    OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/contract_party.ndjson  @CUAD_LOAD/contract_party/  OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/related_doc.ndjson     @CUAD_LOAD/related_doc/     OVERWRITE = TRUE AUTO_COMPRESS = TRUE;
PUT file://__BUILD_DIR__/category_stats.ndjson  @CUAD_LOAD/category_stats/  OVERWRITE = TRUE AUTO_COMPRESS = TRUE;

COPY INTO CONTRACT_DIM (DOC_ID, DOC_TYPE, AGREEMENT_YEAR, JURISDICTION, AGREEMENT_DATE_RAW, CLAUSE_COUNT)
FROM (
  SELECT
    $1:doc_id::STRING,
    $1:doc_type::STRING,
    $1:agreement_year::NUMBER,
    $1:jurisdiction::STRING,
    $1:agreement_date_raw::STRING,
    $1:clause_count::NUMBER
  FROM @CUAD_LOAD/contract_dim/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO CONTRACT_PARTY (DOC_ID, PARTY_NAME)
FROM (
  SELECT $1:doc_id::STRING, $1:party_name::STRING
  FROM @CUAD_LOAD/contract_party/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO RELATED_DOC (DOC_ID, RELATED_DOC_ID, RANK, SCORE, REASONS)
FROM (
  SELECT
    $1:doc_id::STRING,
    $1:related_doc_id::STRING,
    $1:rank::NUMBER,
    $1:score::NUMBER,
    $1:reasons::STRING
  FROM @CUAD_LOAD/related_doc/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;

COPY INTO CATEGORY_STATS (CATEGORY, DOC_COUNT, SPAN_COUNT)
FROM (
  SELECT $1:category::STRING, $1:doc_count::NUMBER, $1:span_count::NUMBER
  FROM @CUAD_LOAD/category_stats/
)
FILE_FORMAT = (TYPE = JSON)
ON_ERROR = ABORT_STATEMENT;
