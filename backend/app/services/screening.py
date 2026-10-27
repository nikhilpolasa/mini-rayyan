"""Deterministic, topic-independent screening rules (AGENTS 9 / PRD S1-S6).

Metadata takes precedence for species and language. An inconclusive language
detection never excludes a record. Query concepts are supplied by the pipeline;
this module neither parses queries nor contains review-topic vocabulary.
"""

import re

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

# The library otherwise randomizes results on short/ambiguous text.
DetectorFactory.seed = 0
LANGUAGE_CONFIDENCE = 0.90
MIN_LANGUAGE_LETTERS = 20
CRITERIA = ("non_human", "non_english", "case_report", "simulation", "no_abstract")

ANIMAL_PATTERN = re.compile(
    r"\b(?:rats?|mice|mouse|murine|zebrafish)\b|\bin[\s-]+vitro\b", re.I
)
CASE_PATTERN = re.compile(r"\bcase[\s-]+reports?\b", re.I)
SIMULATION_PATTERN = re.compile(
    r"\bin[\s-]+silico\b|\bmonte[\s-]+carlo\b|\bsimulations?\b|\bcomputational[\s-]+models?\b",
    re.I,
)


def _text(value) -> str:
    """Normalize comparison text, treating absent/non-string values as empty."""
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _values(value) -> list[str]:
    """Accept a metadata string or a sequence; ignore malformed/missing entries."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := _text(item))]


def _non_human(record: dict, text: str) -> str:
    """Prefer decisive MeSH subject tags, then use bounded animal keywords."""
    mesh = set(_values(record.get("mesh")))
    if "humans" in mesh:
        return ""
    if "animals" in mesh:
        return "MeSH Animals without Humans"
    match = ANIMAL_PATTERN.search(text)
    return f"non-human keyword: {match.group()}" if match else ""


def _language(record: dict, abstract: str) -> tuple[str, bool]:
    """Return an exclusion reason and an uncertainty flag for language."""
    languages = set(_values(record.get("language")))
    languages -= {"und", "unknown", "unk"}
    if languages:
        if languages & {"eng", "en", "english"}:
            return "", False
        return f"non-English language metadata: {', '.join(sorted(languages))}", False
    if sum(char.isalpha() for char in abstract) < MIN_LANGUAGE_LETTERS:
        return "", True
    try:
        candidates = detect_langs(abstract)
    except LangDetectException:
        return "", True
    if not candidates or candidates[0].prob < LANGUAGE_CONFIDENCE:
        return "", True
    language = candidates[0].lang
    return (
        (f"non-English abstract detected: {language}", False)
        if language != "en"
        else ("", False)
    )


def _has_term(text: str, term: str) -> bool:
    """Match a case-insensitive phrase at word boundaries; allow trailing *."""
    term = _text(term)
    if not term:
        return False
    truncated = term.endswith("*")
    term = term[:-1] if truncated else term
    if not term:
        return False
    pattern = r"\s+".join(re.escape(word) for word in term.split())
    return (
        re.search(
            r"(?<!\w)" + pattern + (r"\w*" if truncated else "") + r"(?!\w)", text
        )
        is not None
    )


def screen(record: dict, active_criteria: list[str]) -> dict:
    """Return {label, reason, criterion}, without mutating the supplied record.

    All matching active exclusions outrank Maybe. Among exclusions, the caller's
    criterion order determines the first match. Unknown keys are ignored.
    With no abstract S6 always returns Maybe: disabling no_abstract suppresses
    its criterion attribution, but cannot establish relevance without evidence.
    """
    record = record if isinstance(record, dict) else {}
    active = _values(active_criteria)
    title, abstract = _text(record.get("title")), _text(record.get("abstract"))
    text = f"{title} {abstract}"
    uncertain_language = False
    for criterion in dict.fromkeys(active):
        reason = ""
        if criterion == "non_human":
            reason = _non_human(record, text)
        elif criterion == "non_english":
            reason, uncertain_language = _language(record, abstract)
        elif criterion == "case_report":
            if set(_values(record.get("pub_types"))) & {"case report", "case reports"}:
                reason = "publication type Case Reports"
            elif CASE_PATTERN.search(title):
                reason = "case report in title"
        elif criterion == "simulation":
            match = SIMULATION_PATTERN.search(text)
            if match:
                reason = f"simulation keyword: {match.group()}"
        if reason:
            return {"label": "exclude", "reason": reason, "criterion": criterion}
    if not abstract:
        return {
            "label": "maybe",
            "reason": "no abstract",
            "criterion": "no_abstract" if "no_abstract" in active else "",
        }
    raw_groups = record.get("query_groups")
    if not isinstance(raw_groups, (list, tuple)) or not raw_groups:
        return {
            "label": "maybe",
            "reason": "query concepts unavailable",
            "criterion": "",
        }
    missing = []
    for index, group in enumerate(raw_groups, start=1):
        terms = _values(group)
        if not any(
            _has_term(title, term) or _has_term(abstract, term) for term in terms
        ):
            missing.append(" OR ".join(terms) if terms else f"group {index} (no terms)")
    if missing:
        return {
            "label": "maybe",
            "reason": "missing query concept: " + "; ".join(missing),
            "criterion": "",
        }
    if uncertain_language:
        return {
            "label": "maybe",
            "reason": "language could not be determined confidently",
            "criterion": "non_english",
        }
    return {"label": "include", "reason": "matches all query concepts", "criterion": ""}
