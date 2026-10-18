# Architecture

## The corpus

CUAD v1 ships as a single SQuAD 2.0 JSON file: 510 contracts, each with one
"paragraph" whose `context` is the entire contract text, and 41 question/answer
pairs — one per clause category. Answers are character spans into the context.

| | |
|---|---|
| Contracts | 510 |
| Questions | 20,910 (510 × 41) |
| Answer spans | 13,823 |
| Categories | 41 |
| Contract length | 645 – 338,211 chars, median 33,425 |

**`CLAUSES` holds one row per answer span, not per question.** 20,910 questions
produce 13,823 spans; the 7,087 unanswered questions carry nothing a lawyer can
search, so they are not stored.

Offsets are validated at build time — every span is checked against
`context[answer_start:answer_end]` and the build fails on a mismatch — which is
what makes the highlight rendering trustworthy.

## Data model

```
CUAD_DB.CORPUS
  -- as loaded ---------------------------------------------------------------
  CONTRACTS                510  (DOC_ID, TITLE, CHAR_LEN)
  CONTRACT_TEXT            510  (DOC_ID, FULL_TEXT)         -- whole-doc search
  CLAUSES               13,823  one row per answer span
  CLAUSE_CATEGORIES         41  (CATEGORY, DESCRIPTION, ANSWER_FORMAT, GRP)
  APP_USERS                  5  logins: role + status + PBKDF2 hash only
  ACCESS_LOG                    every login, search, view and admin action
  -- derived by scripts/build_dimensions.py ----------------------------------
  CONTRACT_DIM             510  DOC_TYPE, AGREEMENT_YEAR, JURISDICTION, CLAUSE_COUNT
  CONTRACT_PARTY           915  parsed counterparties
  RELATED_DOC            2,430  top 5 related per contract, with reasons
  CATEGORY_STATS            41  DISTINCT documents per clause category
  -- views -------------------------------------------------------------------
  V_CONTRACT_METADATA           document register pivoted from clause answers
  V_CONTRACT_CATEGORY_STATUS    every doc x category, FOUND + SPAN_COUNT
  V_CONTRACT_BROWSE             register + derived dimensions, one row per doc
  V_FACET_TYPE / _YEAR / _JURISDICTION / _PARTY    facet values with counts
  V_CATEGORY_INDEX              clause index: contracts per category
  V_RELATED_DOC                 related docs joined to title, type, year
```

## There is no metadata in CUAD

Parties, dates and governing law are not columns. They exist only as clause
answers, as free text. Everything in the derived tables is therefore *parsed*,
and the parse rate is part of the design rather than a footnote:

| Dimension | Parsed | Notes |
|---|---|---|
| Agreement type | 500/510 (98%) | from the annotated contract name; 207 distinct types, of which the top 20 cover half the corpus |
| Agreement year | 450/510 (88%) | handles `June 21, 1999`, `9/21/98`, and typos like `14t h day of April, 2015` |
| Jurisdiction | 404/510 (79%) | `the laws of the State of New York` and `the laws of England` both normalize to a single value; the designation is stripped |

**Unparseable values are never dropped.** They become `Unclassified` or
`Not stated` and remain selectable facets, so the UI shows you the gap instead
of quietly shrinking the corpus. `make verify` reports all three rates so a
regression is visible.

### Counterparties are the weak axis

CUAD's party field mixes entity names with role labels (`Licensor`, `Party A`,
`INDIVIDUALLY`). After suffix-aware splitting and a role stoplist: **915 party
mentions across 881 distinct names. 854 of those names appear exactly once and
only 27 appear in more than one contract.**

That is why the Parties page lists only names appearing in two or more
contracts, and why counterparty contributes to just 71 of the 2,430
related-document rows. Counterparty navigation is honest about being thin rather
than pretending otherwise.

## Related documents

For each contract, the top five others by score:

```
score = 3 × shared counterparty
      + 3 × Jaccard overlap of the 41-category signature
      + 2 × same agreement type
      + 1 × same jurisdiction
      + 1 × agreement year within ±1          (minimum score 3)
```

Each result carries the reasons it scored, because a bare list of five titles
reads as noise while *"same counterparty · 4 shared clauses"* reads as a system
that understands the corpus. 498 of 510 contracts have at least one match.

## UI navigation

Four index pages all drill into the same filtered register, and navigation state
lives in the URL:

| Page | Shows | Drilling in |
|---|---|---|
| Contracts | the register, with facets: clause categories, type, jurisdiction, decade, counterparty | opens the document |
| Clauses | the 41 categories with distinct-document counts (13 → 510) | filters the register to that clause |
| Types | agreement types with counts, long tail included | filters the register |
| Parties | counterparties appearing in ≥ 2 contracts | filters the register |

A document page shows the parsed dimensions, clause coverage (`13 of 41`), three
tabs (clauses with surrounding context, a checklist of all 41, and the annotated
full text), and the related-contracts panel.

Because state is in the URL, filtered views are linkable — which is also what
makes the demo video scriptable without clicking dataframes.

## What this deliberately does not do

- **No semantic search.** Substring matching plus structured filters.
- **No document-level access control.** Roles gate *pages*, not contracts.
- **No PDFs.** CUAD ships text.
- **No clients or matters.** The corpus has none; inventing them would make the
  demo look more like a product than it is.

## Loading notes

- **NDJSON, not CSV.** Contract text contains embedded newlines, quotes and
  commas, which Snowflake's CSV loader handles badly and its JSON loader handles
  natively.
- **Category names disagree between the two source files.** `CUADv1.json`
  title-cases them (`Notice Period To Terminate Renewal`) while
  `category_descriptions.csv` does not (`...to...`). Ten categories differ.
  `build_load_files.py` normalizes case-insensitively and stores the CSV
  spelling, so `CLAUSES.CATEGORY` joins cleanly to `CLAUSE_CATEGORIES`.
- **`make load` truncates before copying**, so re-running replaces rather than
  appends.
