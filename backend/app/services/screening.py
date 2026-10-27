"""Screening contract placeholder."""


def screen(record: dict, active_criteria: list[str]) -> dict:
    """Return a fixed Maybe result without inspecting the input."""
    return {
        "label": "maybe",
        "reason": "Scaffold stub; screening has not run.",
        "criterion": "",
    }
