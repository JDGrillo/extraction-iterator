"""CLI: Bootstrap example store from a golden labeled spreadsheet."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from ..config import load_schema
from ..example_store import ExampleRecord, ExampleStore
from ..sheet_serializer import serialize_excel_for_llm

app = typer.Typer(help="Bootstrap training examples from golden labels")


@app.command()
def bootstrap_examples(
    input_dir: str = typer.Option("./input", "--input-dir"),
    labels_xlsx: str = typer.Option(..., "--labels-xlsx"),
    output_store: str = typer.Option(
        "./examples/training_examples.jsonl", "--output-store"
    ),
    schema: str | None = typer.Option(None, "--schema"),
    validation_ratio: float = typer.Option(0.1, "--validation-ratio"),
    holdout_ratio: float = typer.Option(0.1, "--holdout-ratio"),
    min_labeled_field_ratio: float = typer.Option(0.3, "--min-labeled-field-ratio"),
    max_sheets: int = typer.Option(5, "--max-sheets"),
    max_rows_per_sheet: int = typer.Option(80, "--max-rows-per-sheet"),
    max_cols_per_sheet: int = typer.Option(20, "--max-cols-per-sheet"),
    max_cell_chars: int = typer.Option(120, "--max-cell-chars"),
) -> None:
    input_path = Path(input_dir)
    labels_path = Path(labels_xlsx)
    output_path = Path(output_store)

    if not input_path.exists() or not input_path.is_dir():
        typer.echo(f"Error: input directory not found: {input_path}", err=True)
        raise typer.Exit(1)
    if not labels_path.exists() or not labels_path.is_file():
        typer.echo(f"Error: labels file not found: {labels_path}", err=True)
        raise typer.Exit(1)

    if (
        validation_ratio < 0
        or holdout_ratio < 0
        or validation_ratio + holdout_ratio >= 1
    ):
        typer.echo(
            "Error: validation_ratio + holdout_ratio must be >= 0 and < 1.", err=True
        )
        raise typer.Exit(1)

    labels_df = pd.read_excel(labels_path).fillna("")
    if "source_file" not in labels_df.columns:
        typer.echo("Error: labels file must include a source_file column.", err=True)
        raise typer.Exit(1)

    if schema:
        schema_fields = [field.name for field in load_schema(Path(schema)).fields]
    else:
        schema_fields = [col for col in labels_df.columns if col != "source_file"]

    store = ExampleStore(output_path)
    input_files = _index_input_files(input_path)

    inserted = 0
    skipped_missing_file = 0
    skipped_empty_sheet = 0
    skipped_low_label_density = 0

    for _, row in labels_df.iterrows():
        source_file = str(row.get("source_file", "")).strip()
        if not source_file:
            continue

        doc_path = input_files.get(source_file.lower())
        if doc_path is None:
            skipped_missing_file += 1
            continue

        output = _build_output_payload(row=row, schema_fields=schema_fields)
        if not output:
            skipped_low_label_density += 1
            continue

        labeled_ratio = len(output) / max(1, len(schema_fields))
        if labeled_ratio < min_labeled_field_ratio:
            skipped_low_label_density += 1
            continue

        sheet_markdown = serialize_excel_for_llm(
            file_path=doc_path,
            max_sheets=max_sheets,
            max_rows_per_sheet=max_rows_per_sheet,
            max_cols_per_sheet=max_cols_per_sheet,
            max_cell_chars=max_cell_chars,
        )
        if not sheet_markdown:
            skipped_empty_sheet += 1
            continue

        split = _pick_split(
            source_file=source_file,
            validation_ratio=validation_ratio,
            holdout_ratio=holdout_ratio,
        )

        record = ExampleRecord(
            source_file=source_file,
            sheet_markdown=sheet_markdown,
            output=output,
            quality_score=1.0,
            split=split,
            metadata={
                "bootstrap": True,
                "label_source": str(labels_path),
                "labeled_field_ratio": round(labeled_ratio, 4),
            },
        )
        store.append(record, deduplicate=True)
        inserted += 1

    typer.echo("Bootstrap complete")
    typer.echo(f"Inserted/updated records: {inserted}")
    typer.echo(f"Skipped (missing file): {skipped_missing_file}")
    typer.echo(f"Skipped (empty workbook serialization): {skipped_empty_sheet}")
    typer.echo(f"Skipped (low label density): {skipped_low_label_density}")
    typer.echo(f"Example store: {output_path}")


def _index_input_files(input_dir: Path) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    for path in input_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".xlsx", ".xls"}:
            continue
        indexed[path.name.lower()] = path
    return indexed


def _build_output_payload(row: pd.Series, schema_fields: list[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field_name in schema_fields:
        raw = row.get(field_name, "")
        if isinstance(raw, str):
            value = raw.strip()
        else:
            value = raw
        if value == "":
            continue
        output[field_name] = value
    return output


def _pick_split(source_file: str, validation_ratio: float, holdout_ratio: float) -> str:
    digest = hashlib.md5(source_file.lower().encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF

    if bucket < holdout_ratio:
        return "holdout"
    if bucket < holdout_ratio + validation_ratio:
        return "validation"
    return "train"


if __name__ == "__main__":
    app()
