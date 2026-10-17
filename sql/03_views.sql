-- Step 2d: the document register the UI reads.
-- Run with: make views

USE WAREHOUSE CUAD_WH;
USE DATABASE CUAD_DB;
USE SCHEMA CORPUS;

-- Document-level metadata is not a column in CUAD: it exists only as clause
-- answers. Pivot the 8 documentary categories into a register, taking the
-- earliest span when a category matched more than once.
CREATE OR REPLACE VIEW V_CONTRACT_METADATA AS
WITH first_span AS (
  SELECT DOC_ID, CATEGORY, ANSWER_TEXT
  FROM CLAUSES
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY DOC_ID, CATEGORY
    ORDER BY ANSWER_START, ANSWER_END
  ) = 1
)
SELECT
  c.DOC_ID,
  c.TITLE,
  c.CHAR_LEN,
  MAX(IFF(f.CATEGORY = 'Document Name',                        f.ANSWER_TEXT, NULL)) AS DOCUMENT_NAME,
  MAX(IFF(f.CATEGORY = 'Parties',                              f.ANSWER_TEXT, NULL)) AS PARTIES,
  MAX(IFF(f.CATEGORY = 'Agreement Date',                       f.ANSWER_TEXT, NULL)) AS AGREEMENT_DATE,
  MAX(IFF(f.CATEGORY = 'Effective Date',                       f.ANSWER_TEXT, NULL)) AS EFFECTIVE_DATE,
  MAX(IFF(f.CATEGORY = 'Expiration Date',                      f.ANSWER_TEXT, NULL)) AS EXPIRATION_DATE,
  MAX(IFF(f.CATEGORY = 'Renewal Term',                         f.ANSWER_TEXT, NULL)) AS RENEWAL_TERM,
  MAX(IFF(f.CATEGORY = 'Notice Period to Terminate Renewal',   f.ANSWER_TEXT, NULL)) AS NOTICE_PERIOD_TO_TERMINATE_RENEWAL,
  MAX(IFF(f.CATEGORY = 'Governing Law',                        f.ANSWER_TEXT, NULL)) AS GOVERNING_LAW
FROM CONTRACTS c
LEFT JOIN first_span f
  ON f.DOC_ID = c.DOC_ID
GROUP BY c.DOC_ID, c.TITLE, c.CHAR_LEN;

-- Which categories were found per document (the document page checklist).
CREATE OR REPLACE VIEW V_CONTRACT_CATEGORY_STATUS AS
SELECT
  c.DOC_ID,
  cc.CATEGORY,
  cc.GRP,
  IFF(COUNT(cl.CLAUSE_ID) > 0, TRUE, FALSE) AS FOUND,
  COUNT(cl.CLAUSE_ID)                       AS SPAN_COUNT
FROM CONTRACTS c
CROSS JOIN CLAUSE_CATEGORIES cc
LEFT JOIN CLAUSES cl
  ON cl.DOC_ID = c.DOC_ID
 AND cl.CATEGORY = cc.CATEGORY
GROUP BY c.DOC_ID, cc.CATEGORY, cc.GRP;
