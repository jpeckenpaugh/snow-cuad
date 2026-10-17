#!/usr/bin/env python3
"""Derive navigable dimensions from the CUAD clause text.

The clause answers are free text, not columns, so this is a parsing job:

  contract_dim.ndjson   510 rows   type, year, jurisdiction, clause_count
  contract_party.ndjson           one row per extracted party mention
  related_doc.ndjson               top-5 related contracts with reasons
  category_stats.ndjson  41 rows   distinct document count per category
  dimensions.json                 counts + parse rates for `make verify`

Parsing is deliberate and lossy: unparseable values become an explicit
"Unclassified" / "Not stated" rather than being dropped, so the UI can show
them as selectable facet values and `make verify` can report the rates.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "build"
OUT = ROOT / "build"

UNCLASSIFIED = "Unclassified"
NOT_STATED = "Not stated"

# --- document type -----------------------------------------------------------

TYPE_RE = re.compile(
    r"([A-Z][A-Z0-9 &/\-]{2,50}?"
    r"(?:AGREEMENT|CONTRACT|ADDENDUM|LICENSE|LEASE|DEED|NOTE|POLICY|PLAN|GUARANTEE|PROTOCOL))"
    r"(?![A-Z])"
)
TYPE_PREFIX_RE = re.compile(r"^(THE|THIS|AMENDED AND RESTATED|FORM OF)\s+")

ACRONYMS = {"IP", "IT", "US", "UK", "TV", "LLC", "LLP", "LP", "M&A", "SaaS", "SLA", "NDA"}


def smart_title(value: str) -> str:
    words = []
    for word in value.split():
        if word.upper() in ACRONYMS:
            words.append(word.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def document_type(answers: list[str]) -> str:
    for answer in answers:
        text = re.sub(r"\s+", " ", answer.upper())
        hits = TYPE_RE.findall(text)
        if hits:
            best = TYPE_PREFIX_RE.sub("", max(hits, key=len)).strip()
            return smart_title(best)
    return UNCLASSIFIED


# --- agreement year ----------------------------------------------------------

YEAR4_RE = re.compile(r"\b(19|20)\d{2}\b")
YEAR2_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{2})\b")


def agreement_year(answer: str | None) -> int | None:
    if not answer:
        return None
    match = YEAR4_RE.search(answer)
    if match:
        return int(match.group(0))
    match = YEAR2_RE.search(answer)
    if match:
        two = int(match.group(1))
        return 1900 + two if two > 30 else 2000 + two
    return None


# --- jurisdiction ------------------------------------------------------------

JUR_RE = re.compile(
    r"(?:(?:STATE|COMMONWEALTH|PROVINCE|COUNTRY|FEDERAL REPUBLIC|REPUBLIC) OF(?:\s+THE)?"
    r"|LAWS OF(?:\s+THE)?)\s+"
    r"([A-Z][A-Za-z]+(?:[\s-][A-Z][A-Za-z]+){0,3})",
    re.IGNORECASE,
)
JUR_DESIGNATION_RE = re.compile(
    r"^(STATE|COMMONWEALTH|PROVINCE|COUNTRY|FEDERAL REPUBLIC|REPUBLIC)\s+OF(?:\s+THE)?\s+",
    re.IGNORECASE,
)
JUR_STOP = {
    "WITHOUT", "WITH", "GIVING", "AND", "BUT", "EXCLUDING", "INCLUDING", "ANY",
    "FOR", "TO", "THE", "ITS", "SUCH", "THIS", "THAT", "REGARDLESS", "WILL",
    "SHALL", "ARE", "IS", "AS", "IN",
}


def jurisdiction(answer: str | None) -> str:
    """Extract the place from a governing-law clause.

    Handles both "the laws of the State of New York" and "the laws of England"
    and strips the designation so both spellings land on one facet value.
    """
    if not answer:
        return NOT_STATED
    match = JUR_RE.search(answer)
    if not match:
        return NOT_STATED

    place = JUR_DESIGNATION_RE.sub("", match.group(1), count=1)
    kept: list[str] = []
    for word in place.split():
        if word.upper() in JUR_STOP:
            break
        kept.append(word)
    place = " ".join(kept).strip(" ,.")
    return place.title() if place else NOT_STATED


# --- parties -----------------------------------------------------------------

PARTY_SUFFIX = re.compile(
    r"^(INC|LLC|LTD|CORP|CORPORATION|COMPANY|CO|LIMITED|L P|LP|LLP|PLC|GMBH|SA|NV|AG|BV|"
    r"INCORPORATED|INTERNATIONAL)$"
)
PARTY_ROLE = re.compile(
    r"^(THE )?(COMPANY|DISTRIBUTOR|SPONSOR|PARTY A|PARTY B|PARTY|PARTIES|A PARTY|B PARTY|"
    r"LICENSOR|LICENSEE|PROVIDER|CUSTOMER|CLIENT|VENDOR|PURCHASER|SELLER|BUYER|"
    r"CONTRACTOR|CONSULTANT|ISSUER|SUPPLIER|PARTNER|PARTNERS|EMPLOYER|EMPLOYEE|"
    r"ASSIGNOR|ASSIGNEE|AGENT|SHIPPER|OWNER|FRANCHISEE|FRANCHISOR|RESELLER|DEVELOPER|"
    r"TRANSPORTER|TRUST|MANAGER|ADVISOR|BROKER|UNDERWRITER|GUARANTOR|"
    r"BOTH PARTIES|EACH A PARTY|EACH PARTY|INDIVIDUALLY AS A PARTY|INDIVIDUALLY|"
    r"COLLECTIVELY AS THE PARTIES|COLLECTIVELY|AND|OR|A|B|US|WE|THEM|EACH|HEREINAFTER|"
    r"HE|SHE|IT|THEY)$",
    re.IGNORECASE,
)
PARTY_NOISE = re.compile(r"^[^A-Za-z]*$")
PARTY_REJECT = re.compile(
    r"(\bON THE (ONE|OTHER) HAND\b|\bTOGETHER\b|\bASSIGNS?\b|\bCOLLECTIVELY\b|"
    r"\bEACH OF\b|\bINDIVIDUALLY\b|\bHEREINAFTER\b|\bAS THE PARTIES\b|\bET AL\b|"
    r"\bENTITIES\b|\bAND\b|\bEACH\b|\bBOTH\b|\bA PARTY\b|\bTO THIS AGREEMENT\b)",
    re.IGNORECASE,
)
PARTY_LEADING_SUFFIX = re.compile(
    r"^(INC|LLC|LTD|CORP|CORPORATION|COMPANY|CO|LIMITED|L P|LP|LLP|PLC)\.?\s+",
    re.IGNORECASE,
)
# Tokens that describe a role rather than an entity. A name built only from
# these is not a counterparty ("Licensor Licensee", "Contractor Company").
ROLE_TOKENS = {
    "COMPANY", "COMPANIES", "DISTRIBUTOR", "SPONSOR", "PARTY", "PARTIES", "LICENSOR",
    "LICENSEE", "LICENSING", "LICENSED", "PROVIDER", "CUSTOMER", "CLIENT", "VENDOR",
    "PURCHASER", "SELLER", "BUYER", "CONTRACTOR", "CONSULTANT", "ISSUER", "SUPPLIER",
    "PARTNER", "PARTNERS", "EMPLOYER", "EMPLOYEE", "ASSIGNOR", "ASSIGNEE", "AGENT",
    "SHIPPER", "OWNER", "FRANCHISEE", "FRANCHISOR", "RESELLER", "DEVELOPER",
    "TRANSPORTER", "TRUST", "MANAGER", "ADVISOR", "BROKER", "UNDERWRITER",
    "GUARANTOR", "AFFILIATE", "SUBSIDIARY", "PARENT", "INC", "LLC", "LTD", "CORP",
    "CORPORATION", "CO", "LIMITED", "LP", "L", "P", "LLP", "PLC",
    "MANAGEMENT", "A", "B", "TO", "THIS",
}


def all_tokens_are_roles(cleaned: str) -> bool:
    tokens = [t.strip(".,") for t in re.findall(r"[A-Z0-9.]+", cleaned)]
    return bool(tokens) and all(token in ROLE_TOKENS for token in tokens)


def strip_leading_roles(cleaned: str) -> str:
    tokens = cleaned.split()
    while len(tokens) > 1 and tokens[0].strip(".,") in ROLE_TOKENS:
        tokens.pop(0)
    return " ".join(tokens)


def clean_party(candidate: str) -> str | None:
    """Normalize one candidate into a display name, or reject it."""
    cleaned = candidate.upper().strip()
    cleaned = re.sub(r"[^A-Z0-9 &.,'/\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,")

    for _ in range(3):
        cleaned = re.sub(r"^(THE|EACH OF|EACH)\s+", "", cleaned)
    for _ in range(2):
        cleaned = PARTY_LEADING_SUFFIX.sub("", cleaned)
    cleaned = strip_leading_roles(cleaned)

    if len(cleaned) < 4 or PARTY_NOISE.match(cleaned):
        return None
    if PARTY_ROLE.match(cleaned) or PARTY_SUFFIX.match(cleaned):
        return None
    if PARTY_REJECT.search(cleaned) or all_tokens_are_roles(cleaned):
        return None
    if len(cleaned.split()) > 8:
        return None
    return smart_title(cleaned)


def party_names(answer: str) -> list[str]:
    """Split a Parties answer into entity names, keeping 'Group, Inc.' intact."""
    found: list[str] = []
    for chunk in re.split(r"\s*(?:;|\band\b|&)\s*", answer):
        tokens = [t for t in chunk.split(",") if t.strip()]
        merged: list[str] = []
        index = 0
        while index < len(tokens):
            current = tokens[index].strip()
            if index + 1 < len(tokens) and PARTY_SUFFIX.match(tokens[index + 1].strip().upper()):
                current = f"{current}, {tokens[index + 1].strip()}"
                index += 2
            else:
                index += 1
            merged.append(current)

        for candidate in merged:
            name = clean_party(candidate)
            if name:
                found.append(name)

    # de-duplicate, preserve order
    return list(dict.fromkeys(found))


# --- related documents -------------------------------------------------------

WEIGHT_PARTY = 3
WEIGHT_JACCARD = 3
WEIGHT_TYPE = 2
WEIGHT_JURISDICTION = 1
WEIGHT_YEAR = 1
MIN_SCORE = 3
TOP_N = 5


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def main() -> int:
    for name in ("clauses.ndjson", "contracts.ndjson"):
        if not (SRC / name).exists():
            print(f"error: build/{name} missing. Run `make build` first.", file=sys.stderr)
            return 1

    contracts = [json.loads(line) for line in (SRC / "contracts.ndjson").open()]
    clauses = [json.loads(line) for line in (SRC / "clauses.ndjson").open()]

    by_doc: dict[str, list[dict]] = collections.defaultdict(list)
    for clause in clauses:
        by_doc[clause["doc_id"]].append(clause)

    contract_dim: list[dict] = []
    contract_party: list[dict] = []
    signatures: dict[str, set[str]] = {}

    year_ok = juris_ok = type_ok = 0

    for contract in sorted(contracts, key=lambda c: c["doc_id"]):
        doc_id = contract["doc_id"]
        rows = by_doc.get(doc_id, [])

        def answers(category: str) -> list[str]:
            return [r["answer_text"] for r in rows if r["category"] == category]

        doc_type = document_type(answers("Document Name"))
        raw_date = next(iter(answers("Agreement Date")), None)
        year = agreement_year(raw_date)
        jur = jurisdiction(next(iter(answers("Governing Law")), None))

        type_ok += doc_type != UNCLASSIFIED
        year_ok += year is not None
        juris_ok += jur != NOT_STATED

        signature = {r["category"] for r in rows}
        signatures[doc_id] = signature

        contract_dim.append(
            {
                "doc_id": doc_id,
                "doc_type": doc_type,
                "agreement_year": year,
                "jurisdiction": jur,
                "agreement_date_raw": raw_date,
                "clause_count": len(signature),
            }
        )

        for party in party_names(" ".join(answers("Parties"))):
            contract_party.append({"doc_id": doc_id, "party_name": party})

    # related documents
    parties_of: dict[str, set[str]] = collections.defaultdict(set)
    for row in contract_party:
        parties_of[row["doc_id"]].add(row["party_name"].upper())

    dim_of = {row["doc_id"]: row for row in contract_dim}
    doc_ids = sorted(dim_of)
    related: list[dict] = []

    for doc_id in doc_ids:
        left = dim_of[doc_id]
        scored: list[tuple[int, str, list[str]]] = []
        for other_id in doc_ids:
            if other_id == doc_id:
                continue
            right = dim_of[other_id]
            score = 0
            reasons: list[str] = []

            shared_parties = parties_of[doc_id] & parties_of[other_id]
            if shared_parties:
                score += WEIGHT_PARTY
                reasons.append(f"same counterparty: {smart_title(sorted(shared_parties)[0])}")

            overlap = jaccard(signatures[doc_id], signatures[other_id])
            if overlap >= 0.4:
                score += round(WEIGHT_JACCARD * overlap)
                reasons.append(
                    f"shares {len(signatures[doc_id] & signatures[other_id])} clause categories"
                )

            if left["doc_type"] == right["doc_type"]:
                score += WEIGHT_TYPE
                reasons.append(f"same type: {left['doc_type']}")

            if (
                left["jurisdiction"] == right["jurisdiction"]
                and left["jurisdiction"] != NOT_STATED
            ):
                score += WEIGHT_JURISDICTION
                reasons.append(f"same jurisdiction: {left['jurisdiction']}")

            if (
                left["agreement_year"] is not None
                and right["agreement_year"] is not None
                and abs(left["agreement_year"] - right["agreement_year"]) <= 1
            ):
                score += WEIGHT_YEAR
                reasons.append(f"year {right['agreement_year']}")

            if score >= MIN_SCORE:
                scored.append((score, other_id, reasons))

        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (score, other_id, reasons) in enumerate(scored[:TOP_N], start=1):
            related.append(
                {
                    "doc_id": doc_id,
                    "related_doc_id": other_id,
                    "rank": rank,
                    "score": score,
                    "reasons": " | ".join(reasons),
                }
            )

    # category stats: DISTINCT DOCUMENTS, not spans
    stats = []
    for category in sorted({c["category"] for c in clauses}):
        rows = [c for c in clauses if c["category"] == category]
        stats.append(
            {
                "category": category,
                "doc_count": len({r["doc_id"] for r in rows}),
                "span_count": len(rows),
            }
        )

    payloads = {
        "contract_dim": contract_dim,
        "contract_party": contract_party,
        "related_doc": related,
        "category_stats": stats,
    }

    hashes = {}
    for name, rows in payloads.items():
        path = OUT / f"{name}.ndjson"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        import hashlib

        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    total = len(contract_dim)
    diagnostics = {
        "counts": {name: len(rows) for name, rows in payloads.items()},
        "sha256": hashes,
        "rates": {
            "type_classified": type_ok,
            "year_parsed": year_ok,
            "jurisdiction_parsed": juris_ok,
            "documents": total,
        },
    }
    (OUT / "dimensions.json").write_text(json.dumps(diagnostics, indent=2) + "\n")

    print("dimensions OK")
    for name, rows in payloads.items():
        print(f"  {name:<16} {len(rows):>6} rows -> build/{name}.ndjson")
    print("\nparse rates")
    print(f"  type classified      {type_ok:>4}/{total}")
    print(f"  year parsed          {year_ok:>4}/{total}")
    print(f"  jurisdiction parsed  {juris_ok:>4}/{total}")
    multi = sum(1 for d in doc_ids if any(r["doc_id"] == d for r in related))
    counterparty = sum(1 for r in related if "same counterparty" in r["reasons"])
    print(f"  documents with >=1 related: {multi}/{total}")
    print(f"  related rows citing a shared counterparty: {counterparty}/{len(related)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
