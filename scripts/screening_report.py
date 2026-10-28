"""Count synthetic screening decisions by criterion and evidence source."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.screening import CRITERIA, screen


def summarize(dataset: dict) -> dict[str, Counter]:
    counts = {key: Counter() for key in CRITERIA}
    for case in dataset.get("cases", []):
        for key in CRITERIA:
            result = screen(case.get("record", {}), [key])
            if result["criterion"] != key:
                continue
            source = "metadata" if "[metadata: " in result["reason"] else "algorithm" if "[algorithm: " in result["reason"] else "unattributed"
            counts[key][source] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=ROOT / "fixtures" / "screening_synthetic.json")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    print(f"Dataset: {dataset.get('dataset', 'unnamed')} ({len(dataset.get('cases', []))} cases; {dataset.get('provenance', 'provenance unknown')})")
    print("Criterion        Metadata  Algorithm  Unattributed  Total")
    for key, values in summarize(dataset).items():
        print(f"{key:16} {values['metadata']:8} {values['algorithm']:10} {values['unattributed']:13} {sum(values.values()):5}")


if __name__ == "__main__":
    main()
