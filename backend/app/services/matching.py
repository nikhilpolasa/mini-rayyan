"""Conservative bibliographic matching; scores feed the grouping service.

Scores are confidence-gated: missing/conflicting bibliographic evidence and
conference reports cannot reach AUTO_THRESHOLD without a shared identifier.
"""

import math
import re
import unicodedata

from rapidfuzz import fuzz

AUTO_THRESHOLD = 0.95
UNCERTAIN_THRESHOLD = 0.85
UNCERTAIN_MAX_SCORE = math.nextafter(AUTO_THRESHOLD, 0.0)
MAX_YEAR_DIFFERENCE = 1
CONFERENCE_PATTERN = re.compile(
    r"\b(?:conference|congress(?:es)?|proceedings|meeting abstracts?)\b", re.I
)


def normalize_title(title: str) -> str:
    """Casefold Unicode titles, replace punctuation with spaces, collapse whitespace."""
    if not isinstance(title, str):
        return ""
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(
        "".join(
            char if char.isalnum() or char.isspace() else " " for char in normalized
        ).split()
    )


def _identifier(value) -> str:
    """Normalize a nonempty bibliographic identifier; missing values never match."""
    if isinstance(value, str):
        return value.strip().casefold()
    return (
        str(value)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else ""
    )


def _doi(value) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", _identifier(value))


def _year(value) -> int | None:
    text = _identifier(value)
    return int(text) if re.fullmatch(r"[1-9]\d{3}", text) else None


def _first_author(record: dict) -> str:
    """Read surname-first names from the source contract, including collective names."""
    authors = record.get("authors") or record.get("authors_json") or []
    first = (
        authors[0]
        if isinstance(authors, (list, tuple)) and authors
        else authors if isinstance(authors, str) else None
    )
    if isinstance(first, dict):
        return normalize_title(
            first.get("last_name") or first.get("LastName") or first.get("family") or ""
        )
    if not isinstance(first, str) or not first.strip():
        return ""
    if re.search(r"\b(?:group|consortium|collaboration|committee)\b", first, re.I):
        return normalize_title(first)
    surname = first.split(",")[0].split()
    return normalize_title(surname[0]) if surname else ""


def _conference(record: dict) -> bool:
    types = record.get("pub_types") or []
    if not isinstance(types, (list, tuple)):
        types = [types]
    return any(
        CONFERENCE_PATTERN.search(value)
        for value in [*types, record.get("journal"), record.get("title")]
        if isinstance(value, str)
    )


def pair_score(a: dict, b: dict) -> dict:
    """Return {score, match_type}: exact identifiers, fuzzy candidate, or none.

    A fuzzy score >= .95 permits auto-grouping only with matching first surname,
    years within one, no conference marker and no journal/page disagreement.
    Scores [.85, .95) require review. Distinct known DOIs are not fuzzy-merged.
    Shared PMIDs/DOIs identify the same paper even when metadata differs.
    """
    a, b = a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}
    pmid_a, pmid_b = _identifier(a.get("pmid")), _identifier(b.get("pmid"))
    doi_a, doi_b = _doi(a.get("doi")), _doi(b.get("doi"))
    if (pmid_a and pmid_a == pmid_b) or (doi_a and doi_a == doi_b):
        return {"score": 1.0, "match_type": "exact"}
    if doi_a and doi_b:
        return {"score": 0.0, "match_type": "none"}
    title_a, title_b = normalize_title(a.get("title")), normalize_title(b.get("title"))
    if not title_a or not title_b:
        return {"score": 0.0, "match_type": "none"}
    score = fuzz.ratio(title_a, title_b) / 100.0
    if score < UNCERTAIN_THRESHOLD:
        return {"score": score, "match_type": "none"}
    year_a, year_b = _year(a.get("year")), _year(b.get("year"))
    author_a, author_b = _first_author(a), _first_author(b)
    journal_a, journal_b = normalize_title(a.get("journal")), normalize_title(
        b.get("journal")
    )
    pages_a, pages_b = normalize_title(a.get("pages")), normalize_title(b.get("pages"))
    year_matches = (
        year_a is not None
        and year_b is not None
        and abs(year_a - year_b) <= MAX_YEAR_DIFFERENCE
    )
    author_matches = bool(author_a and author_a == author_b)
    pages_match = bool(pages_a and pages_a == pages_b)
    journal_conflict = bool(
        journal_a and journal_b and journal_a != journal_b and not pages_match
    )
    page_conflict = bool(pages_a and pages_b and pages_a != pages_b)
    if (
        not year_matches
        or not author_matches
        or _conference(a)
        or _conference(b)
        or journal_conflict
        or page_conflict
    ):
        score = min(score, UNCERTAIN_MAX_SCORE)
    return {"score": score, "match_type": "fuzzy"}
