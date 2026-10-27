"""Insert missing baseline criteria without changing reviewer configuration."""

from sqlalchemy.exc import IntegrityError

from .. import models as m

DEFAULTS = (
    (
        "non_human",
        "Non-human studies",
        "exclude",
        "Animals MeSH without Humans; species keyword fallback.",
        "The review concerns people.",
        "both",
    ),
    (
        "non_english",
        "Non-English studies",
        "exclude",
        "Language metadata; language detection fallback.",
        "The review team checks English text.",
        "both",
    ),
    (
        "case_report",
        "Case reports",
        "exclude",
        "Case Reports publication type; title regex fallback.",
        "Individual cases do not establish comparative effects.",
        "both",
    ),
    (
        "simulation",
        "Simulation studies",
        "exclude",
        "Simulation and computational modelling keywords.",
        "The review concerns measured patient outcomes.",
        "algorithm",
    ),
    (
        "no_abstract",
        "Missing abstract",
        "maybe",
        "Missing or empty abstract text.",
        "Abstract-level eligibility cannot be assessed.",
        "metadata",
    ),
)


def ensure_criteria(session) -> None:
    """Insert missing project-1 defaults in the caller's transaction, idempotently."""
    for key, label, kind, description, reason, source in DEFAULTS:
        if session.get(m.Criterion, key) is not None:
            continue
        try:
            with session.begin_nested():
                session.add(
                    m.Criterion(
                        key=key,
                        project_id=1,
                        label=label,
                        kind=kind,
                        description=description,
                        reason=reason,
                        source=source,
                        active=True,
                    )
                )
                session.flush()
        except IntegrityError:
            # Another startup may have inserted this same key concurrently.
            if session.get(m.Criterion, key) is None:
                raise
