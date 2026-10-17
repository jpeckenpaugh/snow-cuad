#!/usr/bin/env python3
"""Turn CUADv1.json into NDJSON load files for Snowflake.

Outputs (build/):
  contracts.ndjson       510 rows  doc_id, title, char_len
  contract_text.ndjson   510 rows  doc_id, full_text
  clauses.ndjson      13,823 rows  one row per answer span
  categories.ndjson       41 rows  category, description, answer_format, grp
  manifest.json                   counts + hashes for `make verify`

NDJSON (not CSV) because contract text contains embedded newlines, quotes and
commas; Snowflake's JSON loader handles that natively.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "cuad"
OUT = ROOT / "build"

EXPECTED = {
    "contracts": 510,
    "contract_text": 510,
    "clauses": 13823,
    "categories": 41,
}


def slug(title: str) -> str:
    """Stable, ASCII-only, filename-safe id from a contract title."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_title.lower())).strip("-")


def category_slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")


def norm_category(category: str) -> str:
    """Case/whitespace-insensitive key.

    CUADv1.json title-cases category names ("Notice Period To Terminate
    Renewal") while category_descriptions.csv does not ("...to..."). They
    differ only in casing, so normalize before matching.
    """
    return " ".join(category.lower().split())


def write_ndjson(path: Path, rows: list[dict]) -> str:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_categories() -> tuple[dict[str, dict], dict[str, str]]:
    path = SRC / "category_descriptions.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        cat_col, desc_col, fmt_col, grp_col = cols

        out: dict[str, dict] = {}
        for raw in reader:
            if not raw.get(cat_col):
                continue
            category = raw[cat_col].removeprefix("Category: ").strip()
            out[category] = {
                "category": category,
                "description": raw[desc_col].removeprefix("Description: ").strip(),
                "answer_format": raw[fmt_col].removeprefix("Answer Format: ").strip(),
                "grp": raw[grp_col].removeprefix("Group: ").strip(),
            }

    lookup = {norm_category(k): k for k in out}
    if len(lookup) != len(out):
        raise SystemExit("error: category names collide after normalization")
    return out, lookup


def main() -> int:
    src_json = SRC / "CUADv1.json"
    if not src_json.exists():
        print(f"error: {src_json} missing. Run `make download` first.", file=sys.stderr)
        return 1

    categories, category_lookup = load_categories()

    with src_json.open(encoding="utf-8") as fh:
        docs = json.load(fh)["data"]

    contracts: list[dict] = []
    contract_text: list[dict] = []
    clauses: list[dict] = []
    seen_ids: set[str] = set()
    ids_in_data: set[str] = set()

    for doc in sorted(docs, key=lambda d: d["title"]):
        title = doc["title"]
        doc_id = slug(title)
        if not doc_id:
            raise SystemExit(f"error: empty doc_id for title {title!r}")
        if doc_id in seen_ids:
            raise SystemExit(f"error: duplicate doc_id {doc_id!r} (title {title!r})")
        seen_ids.add(doc_id)

        # CUAD puts one paragraph per contract; be defensive anyway.
        context = "\n".join(p["context"] for p in doc["paragraphs"])
        contracts.append({"doc_id": doc_id, "title": title, "char_len": len(context)})
        contract_text.append({"doc_id": doc_id, "full_text": context})

        for para in doc["paragraphs"]:
            for qa in para["qas"]:
                raw_category = qa["id"].rpartition("__")[2].strip()
                category = category_lookup.get(norm_category(raw_category))
                if category is None:
                    raise SystemExit(
                        f"error: unknown category {raw_category!r} in qa {qa['id']!r}"
                    )
                ids_in_data.add(category)

                for idx, ans in enumerate(qa["answers"]):
                    start = int(ans["answer_start"])
                    text = ans["text"]
                    end = start + len(text)

                    # Offsets are only useful if they actually point at the text.
                    actual = para["context"][start:end]
                    if actual != text:
                        raise SystemExit(
                            f"error: offset mismatch in {qa['id']!r} span {idx}: "
                            f"expected {text!r}, found {actual!r}"
                        )

                    clauses.append(
                        {
                            "clause_id": f"{doc_id}|{category_slug(category)}|{idx}",
                            "doc_id": doc_id,
                            "category": category,
                            "question": qa["question"],
                            "answer_text": text,
                            "answer_start": start,
                            "answer_end": end,
                        }
                    )

    missing = set(categories) - ids_in_data
    if missing:
        raise SystemExit(f"error: categories with no QAs: {sorted(missing)}")

    OUT.mkdir(parents=True, exist_ok=True)
    payloads = {
        "contracts": contracts,
        "contract_text": contract_text,
        "clauses": clauses,
        "categories": [categories[k] for k in sorted(categories)],
    }

    hashes = {}
    for name, rows in payloads.items():
        path = OUT / f"{name}.ndjson"
        hashes[name] = write_ndjson(path, rows)
        expected = EXPECTED[name]
        if len(rows) != expected:
            raise SystemExit(f"error: {name} has {len(rows)} rows, expected {expected}")

    manifest = {
        "counts": {name: len(rows) for name, rows in payloads.items()},
        "sha256": hashes,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("build OK")
    for name, rows in payloads.items():
        print(f"  {name:<14} {len(rows):>6} rows -> build/{name}.ndjson")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
