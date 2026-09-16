#!/usr/bin/env python3
"""Select a reproducible entry batch from the public Signalpost universe."""

from __future__ import annotations

import argparse
import gzip
import json
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True, help="Public .jsonl or .jsonl.gz universe")
    parser.add_argument("--output", required=True, help="Output JSONL manifest")
    parser.add_argument("--bulk", default=None, help="Optional bulk CSV to filter against")
    parser.add_argument("--count", type=int, default=1000, help="At least 1000 for a valid entry")
    parser.add_argument("--seed", type=int, default=20260823)
    args = parser.parse_args()
    if args.count < 1000:
        raise SystemExit("Signalpost entries must cover at least 1,000 companies")

    path = Path(args.universe)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

    if args.bulk and Path(args.bulk).is_file():
        import csv
        bulk_path = Path(args.bulk)
        bulk_opener = gzip.open if bulk_path.suffix == ".gz" or bulk_path.name.endswith(".csv") else open
        with bulk_opener(bulk_path, "rt", encoding="utf-8-sig", errors="replace") as f:
            sample = f.read(8192)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            reader = csv.DictReader(f, dialect=dialect)
            bulk_orgs = {row.get("organisasjonsnummer") for row in reader if row.get("organisasjonsnummer")}
        rows = [r for r in rows if r.get("organisation_number") in bulk_orgs]

    if args.count > len(rows):
        raise SystemExit(f"Requested {args.count}; universe contains {len(rows)}")

    chosen = random.Random(args.seed).sample(rows, args.count)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in chosen:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(chosen):,} companies to {output}")


if __name__ == "__main__":
    main()
