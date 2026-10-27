"""Manual live check (not collected by pytest), run from the repository root:

.venv/Scripts/python.exe backend/tests/manual_pubmed_smoke.py

Set NCBI_EMAIL in the environment or root .env first. Performs one count search,
one capped ID search, and one EFetch POST. Logs metadata only, never abstracts.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pubmed import LiveSourceClient


def main() -> int:
    """Run three tiny live requests and return a shell exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="exercise[tiab] AND sleep[tiab]")
    args = parser.parse_args()
    try:
        with LiveSourceClient() as client:
            count = client.search_count(args.query, date(2016, 1, 1), date.today())
            ids = client.search_ids(args.query, date(2016, 1, 1), date.today(), limit=1)
            records = client.fetch_records(ids)
        if not ids or not records:
            logging.error(
                "No article returned; hit count=%d. Try another query or check FETCH_CAP.",
                count["hit_count"],
            )
            return 1
        assert records[0]["pmid"] == ids[0]
        logging.info(
            "Live smoke passed: hits=%d; translation=%s; fetched PMID=%s; title=%s",
            count["hit_count"],
            count["translation"],
            records[0]["pmid"],
            records[0]["title"],
        )
        return 0
    except httpx.HTTPStatusError as exc:
        logging.error("PubMed returned HTTP %d", exc.response.status_code)
        return 1
    except Exception as exc:
        # HTTP exception strings can include credentials in request URLs.
        logging.error(
            "Live smoke failed (%s); check NCBI_EMAIL and network access.",
            type(exc).__name__,
        )
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
