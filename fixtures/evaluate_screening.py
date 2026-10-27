"""Print per-criterion precision/recall against explicit reference labels.

Default data is synthetic. Real, unreviewed PubMed rows are never scored as
negatives. Run: python fixtures/evaluate_screening.py [dataset.json] [--json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.screening import CRITERIA, screen


def evaluate(dataset: dict) -> dict:
    """Evaluate each rule independently so earlier matches cannot mask recall."""
    cases = dataset.get("cases", [])
    metrics = {}
    for key in CRITERIA:
        tp = fp = fn = tn = skipped = 0
        for case in cases:
            truth = case.get("criterion_matches", {}).get(key)
            if type(truth) is not bool:
                skipped += 1
                continue
            prediction = screen(case.get("record", {}), [key])
            positive = prediction["criterion"] == key and prediction["label"] == (
                "maybe" if key == "no_abstract" else "exclude"
            )
            tp += positive and truth
            fp += positive and not truth
            fn += not positive and truth
            tn += not positive and not truth
        metrics[key] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "skipped": skipped,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }
    reviewed = correct = 0
    disagreements = []
    for case in cases:
        expected = case.get("expected", {})
        if expected.get("label") not in {
            "include",
            "exclude",
            "maybe",
        } or not isinstance(expected.get("criterion"), str):
            continue
        reviewed += 1
        result = screen(
            case.get("record", {}), case.get("active_criteria", list(CRITERIA))
        )
        if (
            result["label"] == expected["label"]
            and result["criterion"] == expected["criterion"]
        ):
            correct += 1
        else:
            disagreements.append(
                {
                    "id": case["id"],
                    "expected": expected,
                    "predicted": result,
                    "known_limitation": case.get("baseline_limitation"),
                }
            )
    return {
        "dataset": dataset.get("dataset", "unnamed"),
        "provenance": dataset.get("provenance", "unspecified"),
        "case_count": len(cases),
        "reviewed": reviewed,
        "correct": correct,
        "accuracy": correct / reviewed if reviewed else None,
        "criteria": metrics,
        "disagreements": disagreements,
    }


def main() -> int:
    """Read a labeled JSON file, print metrics, and reject wholly unreviewed data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("screening_synthetic.json"),
    )
    parser.add_argument(
        "--json", action="store_true", help="Print a machine-readable report"
    )
    args = parser.parse_args()
    try:
        report = evaluate(json.loads(args.dataset.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Cannot evaluate dataset: {exc}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Dataset: {report['dataset']} ({report['case_count']} cases)")
        print(f"Provenance: {report['provenance']}")
        print("Each rule is evaluated alone; unlabeled criterion values are skipped.")
        print(
            f"{'Criterion':<16} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'Precision':>10} {'Recall':>10} {'Skipped':>8}"
        )
        for key, result in report["criteria"].items():
            precision = (
                f"{result['precision']:.3f}"
                if result["precision"] is not None
                else "n/a"
            )
            recall = (
                f"{result['recall']:.3f}" if result["recall"] is not None else "n/a"
            )
            print(
                f"{key:<16} {result['tp']:>4} {result['fp']:>4} {result['fn']:>4} {result['tn']:>4} {precision:>10} {recall:>10} {result['skipped']:>8}"
            )
        print(
            f"Overall label + criterion agreement: {report['correct']}/{report['reviewed']} reviewed cases"
        )
        for mismatch in report["disagreements"]:
            print(
                f"  {mismatch['id']}: expected {mismatch['expected']['label']}, got {mismatch['predicted']['label']}. {mismatch['known_limitation'] or mismatch['predicted']['reason']}"
            )
    if not any(
        sum(result[field] for field in ["tp", "fp", "fn", "tn"])
        for result in report["criteria"].values()
    ):
        if not args.json:
            print(
                "No reviewed per-criterion labels. Fetch records and label them before evaluation."
            )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
