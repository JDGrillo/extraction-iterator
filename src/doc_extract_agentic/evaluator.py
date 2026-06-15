from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class EvaluationResult:
    total_cells: int
    correct_cells: int
    accuracy: float
    per_field: dict[str, dict[str, Any]]
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cells": self.total_cells,
            "correct_cells": self.correct_cells,
            "accuracy": self.accuracy,
            "per_field": self.per_field,
            "failures": self.failures,
        }


def evaluate_extraction(
    extracted_path: Path,
    ground_truth_path: Path,
    max_failures: int = 250,
    include_source_files: set[str] | None = None,
) -> EvaluationResult:
    if not extracted_path.exists() or not ground_truth_path.exists():
        return EvaluationResult(0, 0, 0.0, {}, [])

    extracted = pd.read_excel(extracted_path).fillna("")
    truth = pd.read_excel(ground_truth_path).fillna("")

    if extracted.empty or truth.empty:
        return EvaluationResult(0, 0, 0.0, {}, [])

    gt_by_source: dict[str, pd.Series] = {}
    has_source = "source_file" in truth.columns and "source_file" in extracted.columns
    if has_source:
        for _, row in truth.iterrows():
            gt_by_source[str(row.get("source_file", ""))] = row

    total = 0
    correct = 0
    failures: list[dict[str, Any]] = []
    per_field: dict[str, dict[str, Any]] = {}

    fields = [c for c in extracted.columns if c != "source_file"]
    truth_col_by_norm = {
        _normalize_column_name(col): col
        for col in truth.columns
        if col != "source_file"
    }

    for idx, row in extracted.iterrows():
        source = str(row.get("source_file", idx))
        source_l = source.strip().lower()
        if include_source_files is not None and source_l not in include_source_files:
            continue
        gt_row = None

        if has_source:
            gt_row = gt_by_source.get(source)

        # Fallback to positional matching when source_file labels differ.
        if gt_row is None:
            if idx >= len(truth):
                break
            gt_row = truth.iloc[idx]

        for field in fields:
            truth_col = truth_col_by_norm.get(_normalize_column_name(field))
            if truth_col is None:
                continue
            expected = _normalize(gt_row.get(truth_col, ""))
            actual = _normalize(row.get(field, ""))

            total += 1
            bucket = per_field.setdefault(
                field, {"total": 0, "correct": 0, "accuracy": 0.0}
            )
            bucket["total"] += 1

            if expected == actual:
                correct += 1
                bucket["correct"] += 1
            elif len(failures) < max_failures:
                failures.append(
                    {
                        "source_file": source,
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    for field, stats in per_field.items():
        stats["accuracy"] = (
            round(stats["correct"] / stats["total"], 4) if stats["total"] else 0.0
        )

    accuracy = round(correct / total, 4) if total else 0.0
    return EvaluationResult(total, correct, accuracy, per_field, failures)


def write_evaluation_report(result: EvaluationResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def _normalize(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _normalize_column_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")
