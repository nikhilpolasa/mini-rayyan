"""Matching contract placeholders; no normalization or scoring logic yet."""


def normalize_title(title: str) -> str:
    """Return a fixed empty title."""
    return ""


def pair_score(a: dict, b: dict) -> dict:
    """Return a fixed non-match."""
    return {"score": 0.0, "match_type": "none"}
