from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from .auditor import write_audit_summary, write_discrepancies
from .extractors.registry import build_registry
from .io_utils import build_output_dataframe, discover_input_files, write_outputs
from .learner import append_learning_event
from .models import ExtractionCandidate, FieldResult, OutputSchema
from .planner import pick_extractors_for_file
from .reconciler import reconcile_candidates

logger = logging.getLogger(__name__)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    schema: OutputSchema,
    config: dict,
    ground_truth: Path | None = None,
) -> dict:
    run_id = str(uuid4())
    files = discover_input_files(input_dir)
    registry = build_registry()

    all_field_results = []
    per_file_results = []
    run_trace: dict = {"run_id": run_id, "files": []}

    missing_marker = config.get("pipeline", {}).get("missing_value_marker", "not_found")

    for file_path in files:
        plan = pick_extractors_for_file(file_path, config)
        candidates: list[ExtractionCandidate] = []
        extraction_errors: list[str] = []

        # --- Tabular all-rows path -------------------------------------------
        # Try extract_all_rows() first (excel_native supports this for SOV-style
        # sheets). If it returns rows, emit one output row per data row and skip
        # the single-record candidate/reconcile flow for this file.
        tabular_rows: list[dict[str, str]] = []
        for extractor_name in plan:
            extractor = registry.get(extractor_name)
            if extractor is None or not hasattr(extractor, "extract_all_rows"):
                continue
            try:
                tabular_rows = extractor.extract_all_rows(
                    file_path=file_path, schema=schema, config=config
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                extraction_errors.append(
                    f"{extractor_name}.extract_all_rows failed on {file_path.name}: {exc}"
                )
            if tabular_rows:
                break

        if tabular_rows:
            for row_num, row_data in enumerate(tabular_rows, start=1):
                source_label = f"{file_path.name}:row_{row_num}"
                row_results: list[FieldResult] = [
                    FieldResult(
                        field_name=f.name,
                        value=row_data.get(f.name) or missing_marker,
                        status="found" if row_data.get(f.name) else "not_found",
                        confidence=0.8 if row_data.get(f.name) else 0.0,
                        extractor="excel_native",
                        source_ref=source_label,
                    )
                    for f in schema.fields
                ]
                all_field_results.append(row_results)
                per_file_results.append((source_label, row_results))

            run_trace["files"].append(
                {
                    "file": file_path.name,
                    "plan": plan,
                    "tabular_rows_extracted": len(tabular_rows),
                    "extraction_errors": extraction_errors,
                }
            )
            append_learning_event(
                output_dir=output_dir,
                file_name=file_path.name,
                extractor_plan=plan,
                results=row_results,
                candidates=[],
            )
            continue

        # --- Single-record candidate/reconcile path --------------------------
        for extractor_name in plan:
            extractor = registry.get(extractor_name)
            if extractor is None:
                continue
            try:
                candidates.extend(
                    extractor.extract(file_path=file_path, schema=schema, config=config)
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                msg = f"{extractor_name} failed on {file_path.name}: {exc}"
                logger.warning(msg)
                extraction_errors.append(msg)

        final_results = reconcile_candidates(candidates, schema, config)

        append_learning_event(
            output_dir=output_dir,
            file_name=file_path.name,
            extractor_plan=plan,
            results=final_results,
            candidates=candidates,
        )

        all_field_results.append(final_results)
        per_file_results.append((file_path.name, final_results))
        run_trace["files"].append(
            {
                "file": file_path.name,
                "plan": plan,
                "candidate_count": len(candidates),
                "field_status": {r.field_name: r.status for r in final_results},
                "extraction_errors": extraction_errors,
            }
        )

    output_df = build_output_dataframe(per_file_results)
    write_outputs(output_dir=output_dir, output_df=output_df, run_trace=run_trace)
    write_audit_summary(
        output_dir=output_dir, run_id=run_id, all_results=all_field_results
    )
    write_discrepancies(
        output_dir=output_dir, extracted_df=output_df, ground_truth_path=ground_truth
    )

    return {
        "run_id": run_id,
        "input_files": len(files),
        "output_path": str(output_dir / "extracted_output.xlsx"),
    }
