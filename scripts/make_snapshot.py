"""Capture a provisional offline snapshot from a newline-separated query list."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.pubmed import LiveSourceClient, SnapshotSourceClient  # noqa: E402


def make_snapshot(queries_file: Path, output: Path, start: date, end: date) -> dict:
    queries = [
        line.strip()
        for line in queries_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not queries:
        raise ValueError("The query file contains no queries")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    snapshot = {"version": 1, "queries": {}, "records": {}}
    try:
        with LiveSourceClient() as client:
            for text in queries:
                key = SnapshotSourceClient.normalize_query(text)
                result = client.search_count(text, start, end)
                ids = client.search_ids(text, start, end, limit=client.fetch_cap)
                records = client.fetch_records(ids)
                snapshot["queries"][key] = {
                    "count": result["hit_count"],
                    "pmids": ids,
                }
                snapshot["records"].update(
                    {record["pmid"]: record for record in records}
                )
    except httpx.RequestError as exc:
        raise RuntimeError(
            "Live PubMed connection failed; check network access and retry"
        ) from exc
    with output.open("x", encoding="utf-8") as destination:
        json.dump(snapshot, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queries", type=Path, help="UTF-8 text file, one query per line")
    parser.add_argument("output", type=Path, help="new provisional snapshot JSON file")
    parser.add_argument("--date-from", type=date.fromisoformat, default=date(1900, 1, 1))
    parser.add_argument("--date-to", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    try:
        snapshot = make_snapshot(args.queries, args.output, args.date_from, args.date_to)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Snapshot capture failed: {exc}\n")
    print(
        f"Wrote provisional snapshot: {len(snapshot['queries'])} queries, "
        f"{len(snapshot['records'])} records -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
