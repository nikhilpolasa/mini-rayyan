"""CSV contract placeholder."""


def to_csv(rows: list[dict]) -> str:
    """Return only a fixed header; rows are deliberately ignored."""
    return "pmid,doi,title,abstract,year,journal,label,reason\r\n"
