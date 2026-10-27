"""Conservative keyword/pattern PICO spans against the exact original string.

This baseline is a reviewer aid, not a trained biomedical tagger. Population and
intervention candidates use caller-supplied terms and grammatical cues; comparator
and outcome candidates use generic phrases. Topic vocabulary is never hardcoded.
"""

import re

MAX_PHRASE_WORDS = 12
POPULATION_CUE = re.compile(
    r"\b(?:patients?|adults?|children|adolescents?|participants?|people|subjects?|volunteers?|infants?|women|men)\b",
    re.I,
)
POPULATION_PHRASE = re.compile(
    r"\b(?:patients?|adults?|children|adolescents?|participants?|people|subjects?|volunteers?|infants?|women|men)(?:\s+(?:with|aged|diagnosed\s+with)\s+[^.;:\n]+)?",
    re.I,
)
INTERVENTION_CUE = re.compile(
    r"\b(?:received|receiving|treated\s+with|assigned\s+to|randomi[sz]ed\s+to|administered|underwent)\s+",
    re.I,
)
COMPARATOR_CUE = re.compile(r"\b(?:compared\s+(?:with|to)|versus|vs\.?(?!\w))\s*", re.I)
COMPARATOR_TERM = re.compile(
    r"\b(?:placebo|usual\s+care|control\s+group|wait[ -]?list)\b", re.I
)
OUTCOME_CUE = re.compile(
    r"\b(?:primary\s+outcome|change\s+in|reduction\s+in|mean\s+difference)\b", re.I
)
SCORE_CUE = re.compile(r"\b(?:[\w]+[ -]){0,3}scores?\b", re.I)
STOP_PHRASE = re.compile(
    r"\s+(?:were|was|received|receiving|underwent|randomi[sz]ed|assigned|versus|vs\.?|compared|and|or|but|while|after|before|at|over|during|for)\b|[.;:\n]",
    re.I,
)


def _phrase_end(text: str, start: int) -> int:
    """End a short candidate phrase at punctuation, a clause cue or a word cap."""
    remaining = text[start:]
    boundary = STOP_PHRASE.search(remaining)
    end = start + boundary.start() if boundary else len(text)
    words = list(re.finditer(r"\S+", text[start:end]))
    if len(words) > MAX_PHRASE_WORDS:
        end = start + words[MAX_PHRASE_WORDS - 1].end()
    return end


def _query_matches(text: str, terms: list[str]) -> list[re.Match]:
    """Find literal query phrases without normalizing or changing stored offsets."""
    matches = []
    for term in terms or []:
        if not isinstance(term, str) or not term.strip():
            continue
        term = re.sub(r"\[[^\]]+\]", "", term).strip().strip('"').strip()
        if not term:
            continue
        prefix = term.endswith("*")
        term = term[:-1] if prefix else term
        if not term:
            continue
        pattern = r"\s+".join(re.escape(word) for word in term.split())
        matches.extend(
            re.finditer(
                r"(?<!\w)" + pattern + (r"\w*" if prefix else "") + r"(?!\w)",
                text,
                re.I,
            )
        )
    return matches


def tag_pico(text: str, query_terms: list[str]) -> list[dict]:
    """Return deterministic P/I/C/O spans with text[start:end] == span['text'].

    Offsets are Python Unicode code points and end-exclusive. Empty/missing text
    yields no spans. Overlaps across labels are retained for human review; exact
    duplicates and same-label contained fragments are removed.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    candidates = set()

    def add(label, start, end):
        while start < end and (text[start].isspace() or text[start] in ",;:"):
            start += 1
        while end > start and (text[end - 1].isspace() or text[end - 1] in ",;:"):
            end -= 1
        if end > start:
            candidates.add((label, start, end))

    for match in POPULATION_PHRASE.finditer(text):
        add("P", match.start(), min(match.end(), _phrase_end(text, match.start())))
    comparator_ranges = []
    for match in COMPARATOR_TERM.finditer(text):
        add("C", match.start(), match.end())
        comparator_ranges.append((match.start(), match.end()))
    for match in COMPARATOR_CUE.finditer(text):
        end = _phrase_end(text, match.end())
        add("C", match.end(), end)
        comparator_ranges.append((match.end(), end))
    for match in OUTCOME_CUE.finditer(text):
        add("O", match.start(), _phrase_end(text, match.end()))
    for match in SCORE_CUE.finditer(text):
        add("O", match.start(), match.end())
    interventions = []
    for match in INTERVENTION_CUE.finditer(text):
        end = _phrase_end(text, match.end())
        if not any(start <= match.end() < stop for start, stop in comparator_ranges):
            add("I", match.end(), end)
            interventions.append((match.end(), end))
    for match in _query_matches(text, query_terms):
        start, end = match.span()
        context_start = (
            max(
                text.rfind(".", 0, start),
                text.rfind(";", 0, start),
                text.rfind("\n", 0, start),
            )
            + 1
        )
        context = text[context_start:start]
        if any(left <= start and end <= right for left, right in comparator_ranges):
            label = "C"
        elif any(
            left <= start and end <= right
            for label, left, right in candidates
            if label == "O"
        ):
            label = "O"
        elif any(
            left <= start and end <= right
            for label, left, right in candidates
            if label == "P"
        ):
            label = "P"
        elif any(left <= start and end <= right for left, right in interventions):
            label = "I"
        elif POPULATION_CUE.search(match.group()) or re.search(
            r"\b(?:patients?|adults?|children|people)\s+(?:with|diagnosed\s+with)\s*$",
            context,
            re.I,
        ):
            label = "P"
        else:
            label = "I"  # Uncontextualized query terms are tentative intervention candidates.
        add(label, start, end)
    spans = []
    for label, start, end in candidates:
        if any(
            other_label == label
            and left <= start
            and right >= end
            and (left, right) != (start, end)
            for other_label, left, right in candidates
        ):
            continue
        spans.append(
            {"label": label, "start": start, "end": end, "text": text[start:end]}
        )
    return sorted(spans, key=lambda span: (span["start"], span["end"], span["label"]))
