"""Catch documentation paths that would break on case-sensitive filesystems."""

from pathlib import Path


def test_backend_and_scripts_use_lowercase_documentation_paths():
    root = Path(__file__).resolve().parents[2]
    upper = "D" + "ocs"
    forbidden = (upper + "/", upper + "\\", f'"{upper}"', f"'{upper}'")
    offenders = []
    for directory in (root / "backend", root / "scripts"):
        for path in directory.rglob("*"):
            if not path.is_file() or {"__pycache__", ".pytest_cache", ".venv"} & set(
                path.parts
            ):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if any(token in line for token in forbidden):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{number}")
    assert not offenders, "Use lowercase documentation paths: " + ", ".join(offenders)
