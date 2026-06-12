from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .models import FieldResult


def discover_input_files(input_dir: Path) -> list[Path]:
    supported = {".xlsx", ".xls", ".pdf"}
    return sorted(
        [
            p
            for p in input_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in supported
        ]
    )


def build_output_dataframe(
    file_results: list[tuple[str, list[FieldResult]]],
) -> pd.DataFrame:
    rows: list[dict] = []
    for file_name, fields in file_results:
        row = {"source_file": file_name}
        for field in fields:
            row[field.field_name] = field.value
        rows.append(row)
    return pd.DataFrame(rows)


def write_outputs(output_dir: Path, output_df: pd.DataFrame, run_trace: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(output_dir / "extracted_output.xlsx", index=False)
    with (output_dir / "run_trace.json").open("w", encoding="utf-8") as f:
        json.dump(run_trace, f, indent=2)
