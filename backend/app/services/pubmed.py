"""Synchronous PubMed adapter; snapshot parsing remains unimplemented."""

import os
import re
from datetime import date
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PAGE_SIZE = 200
SEARCH_MAX = 10_000
REQUEST_INTERVAL = 0.34
MAX_RETRIES = 3
_request_lock = Lock()
_last_request: float | None = None


def _text(element: ET.Element | None) -> str:
    """Extract text including nested inline markup; missing elements are empty."""
    return "" if element is None else "".join(element.itertext()).strip()


def parse_records(xml: str | bytes) -> list[dict]:
    """Parse PubMed article XML, skipping books and entries without a PMID.

    Authors are display names (surname first), MeSH entries are descriptor names,
    structured abstract sections are joined with newlines, and absent scalar
    metadata is None. Titles without text are empty strings. No database IDs or
    query-specific fields are assigned by the source adapter.
    """
    root = ET.fromstring(xml)
    error = root.find(".//ERROR")
    if error is not None:
        raise ValueError(f"PubMed EFetch error: {_text(error)}")
    if root.tag != "PubmedArticleSet":
        raise ValueError("Expected a PubmedArticleSet response")
    records = []
    for item in root.findall("PubmedArticle"):
        citation = item.find("MedlineCitation")
        pmid = _text(item.find("MedlineCitation/PMID"))
        if citation is None or not pmid:
            continue
        article = citation.find("Article")
        if article is None:
            continue
        authors = []
        for author in article.findall("AuthorList/Author"):
            name = _text(author.find("CollectiveName"))
            if not name:
                given = _text(author.find("ForeName")) or _text(author.find("Initials"))
                name = " ".join(
                    part
                    for part in [
                        _text(author.find("LastName")),
                        given,
                        _text(author.find("Suffix")),
                    ]
                    if part
                )
            if name:
                authors.append(name)
        pub_date = article.find("Journal/JournalIssue/PubDate")
        year_text = "" if pub_date is None else _text(pub_date.find("Year"))
        year_match = re.fullmatch(r"\d{4}", year_text)
        if year_match is None and pub_date is not None:
            year_match = re.search(r"\b\d{4}\b", _text(pub_date.find("MedlineDate")))
        abstract = (
            "\n".join(
                text
                for section in article.findall("Abstract/AbstractText")
                if (text := _text(section))
            )
            or None
        )
        doi = next(
            (
                value
                for identifier in item.findall("PubmedData/ArticleIdList/ArticleId")
                if identifier.get("IdType") == "doi" and (value := _text(identifier))
            ),
            None,
        )
        records.append(
            {
                "pmid": pmid,
                "doi": doi,
                "title": _text(article.find("ArticleTitle")),
                "abstract": abstract,
                "authors": authors,
                "year": int(year_match.group()) if year_match else None,
                "journal": _text(article.find("Journal/Title"))
                or _text(article.find("Journal/ISOAbbreviation"))
                or None,
                "language": _text(article.find("Language")) or None,
                "pub_types": [
                    value
                    for element in article.findall(
                        "PublicationTypeList/PublicationType"
                    )
                    if (value := _text(element))
                ],
                "mesh": [
                    value
                    for element in citation.findall(
                        "MeshHeadingList/MeshHeading/DescriptorName"
                    )
                    if (value := _text(element))
                ],
                "source": "pubmed",
            }
        )
    return records


class SourceClient:
    """Synchronous source interface reserved for future background jobs."""

    def search_count(self, text: str, date_from: date, date_to: date) -> dict:
        """Return {hit_count: int, translation: str} when implemented."""
        raise NotImplementedError

    def search_ids(
        self,
        text: str,
        date_from: date,
        date_to: date,
        limit: int = 500,
        offset: int = 0,
    ) -> list[str]:
        """Return a page of PMIDs when implemented."""
        raise NotImplementedError

    def fetch_records(self, pmids: list[str]) -> list[dict]:
        """Return normalized record dictionaries when implemented."""
        raise NotImplementedError


class LiveSourceClient(SourceClient):
    """Live E-utilities access with process-wide pacing and bounded retries.

    Use as a context manager or call close(). A supplied HTTP client belongs to
    its caller. Configuration is read from the environment (or the root .env).
    """

    def __init__(self, *, client: httpx.Client | None = None):
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
        self.email = os.getenv("NCBI_EMAIL", "").strip()
        if not self.email:
            raise ValueError("NCBI_EMAIL must be configured for live PubMed access")
        self.tool = os.getenv("NCBI_TOOL", "mini-rayyan").strip() or "mini-rayyan"
        self.api_key = os.getenv("NCBI_API_KEY", "").strip()
        self.fetch_cap = int(os.getenv("FETCH_CAP", "500"))
        if self.fetch_cap < 0:
            raise ValueError("FETCH_CAP must be nonnegative")
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the internally created HTTP client, if any."""
        if self._owns_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _request(
        self, endpoint: str, params: dict, *, post: bool = False
    ) -> httpx.Response:
        """Send a paced request, retrying 429/5xx at most three times."""
        global _last_request
        params = {**params, "db": "pubmed", "tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        for attempt in range(MAX_RETRIES + 1):
            # ponytail: one process-wide lock; use a shared limiter if deployed with multiple workers.
            with _request_lock:
                if _last_request is not None:
                    delay = REQUEST_INTERVAL - (monotonic() - _last_request)
                    if delay > 0:
                        sleep(delay)
                try:
                    response = self._client.request(
                        "POST" if post else "GET",
                        f"{BASE_URL}/{endpoint}",
                        **({"data": params} if post else {"params": params}),
                    )
                finally:
                    _last_request = monotonic()
            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if not retryable or attempt == MAX_RETRIES:
                response.raise_for_status()
                return response
            delay = float(2**attempt)
            try:
                delay = max(delay, float(response.headers.get("Retry-After", "0")))
            except ValueError:
                pass
            sleep(delay)
        raise AssertionError("Retry loop must return or raise")

    def _search(
        self, text: str, date_from: date, date_to: date, retmax: int, retstart: int
    ) -> dict:
        """Return an ESearch JSON result for a date-bounded query."""
        if not text.strip():
            raise ValueError("Query text must not be empty")
        if date_from > date_to:
            raise ValueError("date_from must be on or before date_to")
        payload = self._request(
            "esearch.fcgi",
            {
                "term": text,
                "datetype": "pdat",
                "mindate": date_from.isoformat(),
                "maxdate": date_to.isoformat(),
                "retmode": "json",
                "retmax": retmax,
                "retstart": retstart,
            },
        ).json()
        result = payload.get("esearchresult", {})
        if payload.get("error") or result.get("ERROR") or result.get("errorlist"):
            raise ValueError("PubMed ESearch rejected the query")
        if "count" not in result:
            raise ValueError("PubMed ESearch response is missing count")
        return result

    def search_count(self, text: str, date_from: date, date_to: date) -> dict:
        """Return {hit_count, translation} using ESearch with retmax=0."""
        result = self._search(text, date_from, date_to, retmax=0, retstart=0)
        return {
            "hit_count": int(result["count"]),
            "translation": result.get("querytranslation", ""),
        }

    def search_ids(
        self,
        text: str,
        date_from: date,
        date_to: date,
        limit: int = 500,
        offset: int = 0,
    ) -> list[str]:
        """Return up to limit PMIDs from offset, bounded by FETCH_CAP and 10,000.

        FETCH_CAP caps the number returned per call, not the starting offset.
        No request is made for a zero limit or an offset beyond PubMed's ceiling.
        """
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be nonnegative")
        remaining = min(limit, self.fetch_cap, max(0, SEARCH_MAX - offset))
        ids = []
        while remaining > 0:
            page_size = min(PAGE_SIZE, remaining)
            result = self._search(
                text, date_from, date_to, retmax=page_size, retstart=offset
            )
            page = result.get("idlist", [])[:page_size]
            ids.extend(page)
            offset += len(page)
            remaining -= len(page)
            if not page or len(page) < page_size or offset >= int(result["count"]):
                break
        return ids

    def fetch_records(self, pmids: list[str]) -> list[dict]:
        """Fetch records via POST in batches of at most 200 PMIDs."""
        if any(
            not isinstance(pmid, str) or not pmid.isascii() or not pmid.isdecimal()
            for pmid in pmids
        ):
            raise ValueError("PMIDs must be nonempty ASCII digit strings")
        records = []
        for start in range(0, len(pmids), PAGE_SIZE):
            response = self._request(
                "efetch.fcgi",
                {
                    "id": ",".join(pmids[start : start + PAGE_SIZE]),
                    "retmode": "xml",
                },
                post=True,
            )
            records.extend(parse_records(response.content))
        return records


class SnapshotSourceClient(SourceClient):
    pass
