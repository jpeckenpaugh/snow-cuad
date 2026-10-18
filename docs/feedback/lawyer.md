# Feedback — Lawyer (Ada Whitfield, lawyer-001)

## What I did
- Signed in at http://localhost:8501 as `lawyer-001`. Landed as "Ada Whitfield / lawyer":
  a Browse sidebar (Contracts, Clauses, Types, Parties), a Search box, a Filter panel and
  Sign out. No admin or audit entry was offered to me.
- Ran clause-text searches with the terms: `governing law`, `change of control`, `indemnif`,
  `indemnification`, `assignment`, `non-compete`, `exclusivity`, `agreement`, `2Themart`,
  `the parties`.
- Pushed on awkward input: a single letter `a`, a period `.`, punctuation-only `(((("`,
  nonsense `zzqqxyzzy`, embedded markup `<b>the</b>`, an ampersand `&`, CUAD redaction
  markers `***`, and a 2,100-character string ("governing law " repeated 150 times).
- Checked case handling with `GOVERNING LAW`, `Indemnif`, `NON-COMPETE`.
- Opened documents from the clause-match list and read the Clauses / Checklist / Full text
  tabs plus the Related contracts panel (worked through the Allied Esports / Newegg
  Sponsorship Agreement, reported as 15 of 41 clauses).
- Browsed by facet: clause category `Governing Law` (437 contracts); Agreement type
  `Unclassified` (10); Jurisdiction `Not stated` (106); Agreement decade `Not stated` (60);
  type+jurisdiction together (7), all three together (0); clause `Governing Law` + jurisdiction
  `New York` (94); Counterparty `Bank of America` (4); Counterparty `Bank of America` +
  jurisdiction `California` (0).
- Visited the Clauses, Types and Parties index pages and read their copy; tried to open a
  document by single- and double-clicking a row in the Contracts register; exercised the
  register toolbar (Show/hide columns, Download as CSV, in-grid Search, Fullscreen).
- Tried a deep link (`?nav=contracts&clause=Governing+Law&jur=New+York`) and a full page
  reload, which dropped me back to the sign-in screen.

## Liked
1. Clause-text search highlights the matched span in yellow and shows it inside the clause
   text, so I can judge relevance without opening the file — `indemnif` returned 60 cards,
   each with surrounding context and the match highlighted (one rival snippet ran to roughly
   1,850 characters, not a stub).
2. The Checklist tab of a document lists all 41 categories with `✔ N span(s)` or
   `· not present` and a "15 of 41" coverage bar — that is exactly the triage view I want
   first, and it took two clicks.
3. The Full text tab renders the entire contract with every annotated clause span highlighted,
   so I can see where the annotations sit and where the gaps are.
4. The Related contracts panel is scored and explained ("shares 12 clause categories",
   "same jurisdiction: California", "year 2018") rather than being a bare top-5 list; the
   reasons are what made me trust the ranking.
5. The parsing gaps are surfaced rather than hidden: `Unclassified` and `Not stated` are
   selectable facets with real counts (type 10, jurisdiction 106, decade 60), and the Parties
   page states plainly that only 27 names appear in more than one contract.

## Frustrated by
1. Clause-text search silently stops at 60 matches. `indemnif`, `indemnification`,
   `assignment`, `exclusivity`, `agreement`, `&` and `***` all returned exactly 60 results,
   with no total, no "showing 60 of N" and no paging or "load more" — I have no way to know
   whether I have seen everything.
2. I could not open a contract from the Contracts register. Single-clicking a Title row and
   double-clicking it both did nothing (the URL stayed on `?nav=contracts`); the only route
   into a document is to type a text search and press `Open` in the clause-match list. So
   filtering by Type, Jurisdiction or Counterparty and then trying to read a contract is a
   dead end.
3. Searching a category's own name does not retrieve the category. The Clauses page says
   Governing Law appears in 437 contracts, but the text search `governing law` returned only
   3 clause matches. Worse, the register header read "0 contracts … No contract titles or
   counterparties match those filters" while clause matches sat right below it — twice I
   assumed my search had failed before I scrolled down.
4. Counterparty data is too noisy to rely on. The Parties page lists "Agreement", "Germany",
   "All Of Its Subsidiaries" and "Cisco Cisco Systems" as counterparties, and a document's
   Counterparties line read "Newegg Inc. Newegg". I would not run a diligence check on these.
5. Every full page reload dropped me to the sign-in screen (I re-signed in repeatedly), so the
   URL state is only linkable while a session is already live; and the register search box is
   labelled "title, counterparty, clause" while its contract count only reflects titles and
   counterparties. Minor, but the count also reads "1 contracts" for a single hit.

## The one thing I'd add first
Show the true number of clause-text matches and let me page through all of them. The silent
60 result cap is the one thing that most undermines trust: when `indemnif`, `assignment` and
`agreement` all stop at exactly 60, I cannot tell whether the corpus is small or whether I am
being shown an arbitrary slice, and for a lawyer reviewing a clause type that difference is
the whole point. A result count plus "next 60" would turn the strongest feature of the app
into something I could actually sign off a review against.

## Honest limits I noticed
- **No semantic search.** It is substring matching, so a category's name often does not
  retrieve the category (Governing Law: 437 contracts by facet vs 3 matches by text), and
  there is no stemming beyond shared prefixes like `indemnif`.
- **No document-level access control.** As `lawyer-001` (role "lawyer") I could see all 510
  contracts; roles appear to gate pages, not contracts. Every lawyer would see the whole corpus.
- **The counterparty dimension is thin and noisy.** Only 27 names repeat; the rest are free
  text mixing entities with role labels ("Licensor", "Party A", "Agreement").
- **No PDFs or executed documents.** CUAD ships text only, so there is nothing to check the
  extracted clause against.
- **No clients, matters or per-matter isolation, and no saved searches.** The register can be
  downloaded as CSV, but I could not save a query or annotate a result to come back to.
- **Derived metadata is parsed from free text and incomplete.** 10 contracts have no type, 60
  no year, 106 no jurisdiction — visible as `Unclassified` / `Not stated`, which is honest but
  means facet counts never sum to 510 in a way I can reconcile myself.
- **No admin or audit pages were offered to my role** (I did not sign in as admin or auditor).
  The footer is clear that this is a demo and not legal advice.
