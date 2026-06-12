from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .auditor import write_audit_summary, write_discrepancies
from .extractors.registry import build_registry
from .io_utils import build_output_dataframe, discover_input_files, write_outputs
from .learner import append_learning_event
from .models import ExtractionCandidate, OutputSchema
from .planner import pick_extractors_for_file, should_invoke_cu_fallback
from .reconciler import reconcile_candidates


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

    for file_path in files:
        plan = pick_extractors_for_file(file_path, config)
        candidates: list[ExtractionCandidate] = []

        for extractor_name in plan:
            extractor = registry.get(extractor_name)
            if extractor is None:
                continue
            candidates.extend(
                extractor.extract(file_path=file_path, schema=schema, config=config)
            )

        provisional_results = reconcile_candidates(candidates, schema, config)
        low_conf = any(r.status != "found" for r in provisional_results)

        if should_invoke_cu_fallback(low_confidence_found=low_conf, config=config):
            cu = registry.get("azure_cu")
            if cu is not None:
                plan.append("azure_cu")
                candidates.extend(
                    cu.extract(file_path=file_path, schema=schema, config=config)
                )

        final_results = reconcile_candidates(candidates, schema, config)

        append_learning_event(
            output_dir=output_dir,
            file_name=file_path.name,
            extractor_plan=plan,
            results=final_results,
        )

        all_field_results.append(final_results)
        per_file_results.append((file_path.name, final_results))
        run_trace["files"].append(
            {
                "file": file_path.name,
                "plan": plan,
                "candidate_count": len(candidates),
                "field_status": {r.field_name: r.status for r in final_results},
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
