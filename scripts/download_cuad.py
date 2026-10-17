#!/usr/bin/env python3
"""Download the CUAD v1 artifacts the POC needs.

Source: https://github.com/The-Atticus-Project/cuad
  data.zip                  -> CUADv1.json (510 contracts, SQuAD 2.0 format)
  category_descriptions.csv -> the 41 clause categories

Writes to data/cuad/ and records hashes in data/cuad/SOURCE.json.
Idempotent: re-uses valid downloads unless --force is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cuad"

BASE = "https://raw.githubusercontent.com/The-Atticus-Project/cuad/main"
FILES = {
    "data.zip": f"{BASE}/data.zip",
    "category_descriptions.csv": f"{BASE}/category_descriptions.csv",
}

EXPECTED_CONTRACTS = 510
EXPECTED_CATEGORIES = 41


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    print(f"  GET {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.replace(dest)


def validate() -> dict:
    """Parse the extracted artifacts and return a summary."""
    import csv

    json_path = DATA / "CUADv1.json"
    if not json_path.exists():
        raise SystemExit(f"error: {json_path} missing")

    with json_path.open(encoding="utf-8") as fh:
        payload = json.load(fh)

    docs = payload.get("data", [])
    if len(docs) != EXPECTED_CONTRACTS:
        raise SystemExit(f"error: expected {EXPECTED_CONTRACTS} contracts, found {len(docs)}")

    qas = sum(len(p["qas"]) for d in docs for p in d["paragraphs"])
    spans = sum(len(q["answers"]) for d in docs for p in d["paragraphs"] for q in p["qas"])

    with (DATA / "category_descriptions.csv").open(encoding="utf-8-sig", newline="") as fh:
        categories = [r for r in csv.DictReader(fh) if r]
    if len(categories) != EXPECTED_CATEGORIES:
        raise SystemExit(f"error: expected {EXPECTED_CATEGORIES} categories, found {len(categories)}")

    return {
        "contracts": len(docs),
        "qas": qas,
        "answer_spans": spans,
        "categories": len(categories),
        "sha256": {
            "data.zip": sha256(DATA / "data.zip"),
            "category_descriptions.csv": sha256(DATA / "category_descriptions.csv"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)

    if args.force or not (DATA / "data.zip").exists():
        print("downloading data.zip")
        fetch(FILES["data.zip"], DATA / "data.zip")
    else:
        print("data.zip present (use --force to re-download)")

    if args.force or not (DATA / "category_descriptions.csv").exists():
        print("downloading category_descriptions.csv")
        fetch(FILES["category_descriptions.csv"], DATA / "category_descriptions.csv")
    else:
        print("category_descriptions.csv present")

    json_path = DATA / "CUADv1.json"
    if args.force or not json_path.exists():
        print("extracting CUADv1.json")
        with zipfile.ZipFile(DATA / "data.zip") as zf:
            names = zf.namelist()
            if "CUADv1.json" not in names:
                raise SystemExit(f"error: CUADv1.json not in data.zip; found {names}")
            zf.extract("CUADv1.json", DATA)

    summary = validate()
    (DATA / "SOURCE.json").write_text(
        json.dumps(
            {
                "source": FILES,
                **summary,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\ndownload OK")
    for key, val in summary.items():
        if key != "sha256":
            print(f"  {key:<14} {val}")
    print(f"  {'data dir':<14} {DATA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
