from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .example_store import ExampleRecord, ExampleStore
from .sheet_serializer import serialize_excel_for_llm


@dataclass
class ExamplePromotionResult:
    considered_rows: int
    promoted_rows: int
    skipped_low_accuracy: int
    skipped_missing_input: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered_rows": self.considered_rows,
            "promoted_rows": self.promoted_rows,
            "skipped_low_accuracy": self.skipped_low_accuracy,
            "skipped_missing_input": self.skipped_missing_input,
        }


def promote_validated_examples(
    *,
    input_dir: Path,
    run_dir: Path,
    ground_truth_path: Path,
    schema_field_names: list[str],
    example_store_path: Path,
    split_by_source: dict[str, str],
    promote_split: str = "train",
    min_row_accuracy: float = 0.98,
    min_labeled_fields: int = 2,
    max_promoted_per_iteration: int = 50,
    max_sheets: int = 5,
    max_rows_per_sheet: int = 80,
    max_cols_per_sheet: int = 20,
    max_cell_chars: int = 120,
) -> ExamplePromotionResult:
    extracted_path = run_dir / "extracted_output.xlsx"
    if not extracted_path.exists() or not ground_truth_path.exists():
        return ExamplePromotionResult(0, 0, 0, 0)

    extracted_df = pd.read_excel(extracted_path).fillna("")
    truth_df = pd.read_excel(ground_truth_path).fillna("")
    if extracted_df.empty or truth_df.empty:
        return ExamplePromotionResult(0, 0, 0, 0)

    truth_by_source: dict[str, pd.Series] = {}
    if "source_file" in truth_df.columns:
        for _, row in truth_df.iterrows():
            source = str(row.get("source_file", "")).strip()
            if source:
                truth_by_source[source] = row

    input_file_index = _index_input_files(input_dir)
    store = ExampleStore(example_store_path)

    considered_rows = 0
    promoted_rows = 0
    skipped_low_accuracy = 0
    skipped_missing_input = 0

    for idx, row in extracted_df.iterrows():
        if promoted_rows >= max_promoted_per_iteration:
            break

        source = str(row.get("source_file", "")).strip()
        if not source:
            source = str(idx)

        assigned_split = split_by_source.get(source.lower(), "train")
        if assigned_split != promote_split:
            continue

        gt_row = truth_by_source.get(source)
        if gt_row is None and idx < len(truth_df):
            gt_row = truth_df.iloc[idx]
        if gt_row is None:
            continue

        considered_rows += 1

        comparable_fields = [
            field
            for field in schema_field_names
            if field in extracted_df.columns and field in truth_df.columns
        ]
        if not comparable_fields:
            continue

        matches = 0
        labeled = 0
        output: dict[str, Any] = {}
        for field in comparable_fields:
            expected = _normalize(gt_row.get(field, ""))
            actual = _normalize(row.get(field, ""))
            if not expected:
                continue
            labeled += 1
            output[field] = gt_row.get(field)
            if expected == actual:
                matches += 1

        if labeled < min_labeled_fields:
            skipped_low_accuracy += 1
            continue

        row_accuracy = matches / labeled if labeled else 0.0
        if row_accuracy < min_row_accuracy:
            skipped_low_accuracy += 1
            continue

        input_doc = input_file_index.get(source.lower())
        if input_doc is None:
            skipped_missing_input += 1
            continue

        sheet_markdown = serialize_excel_for_llm(
            file_path=input_doc,
            max_sheets=max_sheets,
            max_rows_per_sheet=max_rows_per_sheet,
            max_cols_per_sheet=max_cols_per_sheet,
            max_cell_chars=max_cell_chars,
        )
        if not sheet_markdown:
            skipped_missing_input += 1
            continue

        run_id = _read_run_id(run_dir)
        record = ExampleRecord(
            source_file=source,
            sheet_markdown=sheet_markdown,
            output=output,
            quality_score=round(row_accuracy, 4),
            split=promote_split,
            metadata={
                "auto_promoted": True,
                "run_dir": str(run_dir),
                "run_id": run_id,
                "row_accuracy": round(row_accuracy, 4),
                "labeled_fields": labeled,
            },
        )
        store.append(record, deduplicate=True)
        promoted_rows += 1

    return ExamplePromotionResult(
        considered_rows=considered_rows,
        promoted_rows=promoted_rows,
        skipped_low_accuracy=skipped_low_accuracy,
        skipped_missing_input=skipped_missing_input,
    )


def _normalize(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _index_input_files(input_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in input_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".xlsx", ".xls"}:
            continue
        out[path.name.lower()] = path
    return out


def _read_run_id(run_dir: Path) -> str:
    trace_path = run_dir / "run_trace.json"
    if not trace_path.exists():
        return ""
    try:
        import json

        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        return str(payload.get("run_id", ""))
    except (OSError, ValueError):
        return ""
