from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .models import FieldResult


def write_audit_summary(
    output_dir: Path, run_id: str, all_results: list[list[FieldResult]]
) -> None:
    found = 0
    inferred = 0
    not_found = 0

    for result_set in all_results:
        for field in result_set:
            if field.status == "found":
                found += 1
            elif field.status == "inferred":
                inferred += 1
            else:
                not_found += 1

    summary = {
        "run_id": run_id,
        "field_status_counts": {
            "found": found,
            "inferred": inferred,
            "not_found": not_found,
        },
        "total_fields": found + inferred + not_found,
    }

    with (output_dir / "audit_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def write_discrepancies(
    output_dir: Path,
    extracted_df: pd.DataFrame,
    ground_truth_path: Path | None,
) -> None:
    if ground_truth_path is None or not ground_truth_path.exists():
        return

    gt_df = pd.read_excel(ground_truth_path)
    if gt_df.empty or extracted_df.empty:
        return

    rows = min(len(gt_df), len(extracted_df))
    discrepancies: list[dict] = []

    for i in range(rows):
        for col in extracted_df.columns:
            expected = gt_df.at[i, col] if col in gt_df.columns else None
            actual = extracted_df.at[i, col]
            if str(expected) != str(actual):
                discrepancies.append(
                    {
                        "row": i,
                        "field": col,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    if discrepancies:
        pd.DataFrame(discrepancies).to_csv(
            output_dir / "discrepancies.csv", index=False
        )
