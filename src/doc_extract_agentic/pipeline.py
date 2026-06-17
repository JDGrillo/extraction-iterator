from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from statistics import mean
from datetime import datetime
from uuid import uuid4

from .auditor import write_audit_summary, write_discrepancies
from .extractors.registry import build_registry
from .io_utils import build_output_dataframe, discover_input_files, write_outputs
from .learner import append_learning_event
from .models import ExtractionCandidate, FieldResult, OutputSchema
from .planner import pick_extractors_for_file
from .reconciler import reconcile_candidates
from .rule_applier import RuleApplier
from .rule_cache import RuleCache

logger = logging.getLogger(__name__)


def _field_coverage(rows: list[dict[str, str]], schema_fields: list[str]) -> dict[str, int]:
    coverage = {field: 0 for field in schema_fields}
    for row in rows:
        for field in schema_fields:
            value = str(row.get(field, "")).strip()
            if value:
                coverage[field] += 1
    return coverage


def _summarize_tabular_quality(
    raw_rows_count: int,
    transformed_rows: list[dict[str, str]],
    schema_fields: list[str],
) -> dict:
    coverage = _field_coverage(transformed_rows, schema_fields)
    total_rows = len(transformed_rows)
    missing_by_field = {field: total_rows - count for field, count in coverage.items()}
    field_fill_rates = {
        field: (coverage[field] / total_rows if total_rows else 0.0)
        for field in schema_fields
    }

    sparsity_scores = []
    for row in transformed_rows:
        populated = sum(1 for field in schema_fields if str(row.get(field, "")).strip())
        sparsity_scores.append(populated / len(schema_fields) if schema_fields else 0.0)

    top_missing = sorted(
        missing_by_field.items(), key=lambda kv: kv[1], reverse=True
    )[:5]

    return {
        "rows_before_pipeline_rules": raw_rows_count,
        "rows_after_pipeline_rules": total_rows,
        "avg_field_fill_ratio_per_row": round(mean(sparsity_scores), 4)
        if sparsity_scores
        else 0.0,
        "field_coverage": coverage,
        "top_missing_fields": [{"field": f, "missing_rows": m} for f, m in top_missing],
        "field_fill_rates": {k: round(v, 4) for k, v in field_fill_rates.items()},
    }


def _compare_handoff_models(
    primary_rows: list[dict[str, str]],
    secondary_candidates: list[ExtractionCandidate],
    schema_fields: list[str],
) -> dict:
    secondary_by_field: dict[str, list[str]] = {field: [] for field in schema_fields}
    for cand in secondary_candidates:
        if cand.field_name not in secondary_by_field:
            continue
        value = str(cand.value).strip()
        if value:
            secondary_by_field[cand.field_name].append(value)

    primary_value_sets: dict[str, set[str]] = {field: set() for field in schema_fields}
    for row in primary_rows:
        for field in schema_fields:
            value = str(row.get(field, "")).strip()
            if value:
                primary_value_sets[field].add(value)

    primary_missing_secondary_has: list[str] = []
    conflicts: list[dict] = []
    primary_has_secondary_missing: list[str] = []

    per_field: dict[str, dict[str, float | int]] = {}

    for field in schema_fields:
        primary_vals = primary_value_sets[field]
        secondary_vals = secondary_by_field[field]
        secondary_unique = list(dict.fromkeys(secondary_vals))

        if not primary_vals and secondary_unique:
            primary_missing_secondary_has.append(field)
            per_field[field] = {
                "primary_count": 0,
                "secondary_count": len(secondary_unique),
                "overlap_count": 0,
                "overlap_ratio": 0.0,
            }
            continue

        if primary_vals and not secondary_unique:
            primary_has_secondary_missing.append(field)
            per_field[field] = {
                "primary_count": len(primary_vals),
                "secondary_count": 0,
                "overlap_count": 0,
                "overlap_ratio": 0.0,
            }
            continue

        if primary_vals and secondary_unique:
            overlap = [v for v in secondary_unique if v in primary_vals]
            overlap_ratio = len(overlap) / max(1, len(secondary_unique))
            per_field[field] = {
                "primary_count": len(primary_vals),
                "secondary_count": len(secondary_unique),
                "overlap_count": len(overlap),
                "overlap_ratio": round(overlap_ratio, 4),
            }
            if not overlap:
                conflicts.append(
                    {
                        "field": field,
                        "secondary_value": secondary_unique[0],
                        "primary_sample": sorted(primary_vals)[:3],
                    }
                )

    safe_fill_candidates = [
        field
        for field in primary_missing_secondary_has
        if len(list(dict.fromkeys(secondary_by_field.get(field, [])))) == 1
    ]

    return {
        "primary_missing_secondary_has": primary_missing_secondary_has,
        "primary_has_secondary_missing": primary_has_secondary_missing,
        "value_conflicts": conflicts,
        "secondary_candidate_count": len(secondary_candidates),
        "fields_safe_for_global_fill": safe_fill_candidates,
        "per_field_overlap": per_field,
    }


def _schema_fingerprint(schema_fields: list[str]) -> str:
    schema_str = "|".join(sorted(schema_fields))
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]


def _append_handoff_event(
    cache_file: Path,
    run_id: str,
    file_name: str,
    schema_fields: list[str],
    model_handoff: dict | None,
) -> None:
    if model_handoff is None:
        return

    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "file": file_name,
        "schema_fingerprint": _schema_fingerprint(schema_fields),
        "schema_fields": schema_fields,
        "model_handoff": model_handoff,
    }

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event))
            f.write("\n")
    except OSError as exc:
        logger.warning("Failed to append handoff event: %s", exc)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    schema: OutputSchema,
    config: dict,
    ground_truth: Path | None = None,
    rules_file: Path | None = None,
) -> dict:
    run_id = str(uuid4())
    files = discover_input_files(input_dir)
    registry = build_registry()

    all_field_results = []
    per_file_results = []
    run_trace: dict = {"run_id": run_id, "files": []}
    handoff_analysis: dict = {"run_id": run_id, "files": []}
    handoff_history_path = Path(
        str(
            config.get("two_model_learning", {}).get(
                "handoff_history_path", ".cache/handoff/handoff_events.jsonl"
            )
        )
    )

    missing_marker = config.get("pipeline", {}).get("missing_value_marker", "not_found")
    schema_fields = [f.name for f in schema.fields]

    rule_applier = RuleApplier()
    if rules_file is not None and rules_file.exists():
        with rules_file.open("r", encoding="utf-8") as _rf:
            _rules_data = json.load(_rf)
        rule_applier.load_rules(_rules_data.get("rules", []))
        logger.info("Loaded %d rules from %s", len(_rules_data.get("rules", [])), rules_file)
    elif rules_file is not None:
        logger.warning("Rules file not found, skipping: %s", rules_file)
    else:
        cache_dir = Path(
            str(config.get("two_model_learning", {}).get("rules_cache_dir", ".cache/rules"))
        )
        cached_rules = RuleCache(cache_dir).load_rules(schema_fields)
        if cached_rules.get("rules"):
            rule_applier.load_rules(cached_rules.get("rules", []))
            logger.info(
                "Loaded %d cached rules for schema from %s",
                len(cached_rules.get("rules", [])),
                cache_dir,
            )

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
            transformed_rows: list[dict[str, str]] = []
            last_row_results: list[FieldResult] = []
            for row_num, row_data in enumerate(tabular_rows, start=1):
                row_data = rule_applier.apply_to_row(row_data, schema_fields)
                if rule_applier.should_skip_row(row_data):
                    continue
                transformed_rows.append(row_data)
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
                last_row_results = row_results
                all_field_results.append(row_results)
                per_file_results.append((source_label, row_results))

            tabular_quality = _summarize_tabular_quality(
                raw_rows_count=len(tabular_rows),
                transformed_rows=transformed_rows,
                schema_fields=schema_fields,
            )

            model_handoff = None
            if file_path.suffix.lower() in {".xlsx", ".xls"} and "llm_native" in plan:
                llm_extractor = registry.get("llm_native")
                if llm_extractor is not None:
                    try:
                        secondary_candidates = llm_extractor.extract(
                            file_path=file_path,
                            schema=schema,
                            config=config,
                        )
                        model_handoff = _compare_handoff_models(
                            primary_rows=transformed_rows,
                            secondary_candidates=secondary_candidates,
                            schema_fields=schema_fields,
                        )
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        extraction_errors.append(
                            f"llm_native handoff comparison failed on {file_path.name}: {exc}"
                        )

            run_trace["files"].append(
                {
                    "file": file_path.name,
                    "plan": plan,
                    "tabular_rows_extracted": len(transformed_rows),
                    "tabular_quality": tabular_quality,
                    "model_handoff": model_handoff,
                    "extraction_errors": extraction_errors,
                }
            )
            handoff_analysis["files"].append(
                {
                    "file": file_path.name,
                    "plan": plan,
                    "tabular_quality": tabular_quality,
                    "model_handoff": model_handoff,
                }
            )
            _append_handoff_event(
                cache_file=handoff_history_path,
                run_id=run_id,
                file_name=file_path.name,
                schema_fields=schema_fields,
                model_handoff=model_handoff,
            )
            append_learning_event(
                output_dir=output_dir,
                file_name=file_path.name,
                extractor_plan=plan,
                results=last_row_results,
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

        # Apply learned rules to single-record results
        row_dict = {r.field_name: (str(r.value) if r.value is not None else "") for r in final_results}
        transformed = rule_applier.apply_to_row(row_dict, schema_fields)
        for r in final_results:
            r.value = transformed.get(r.field_name, r.value)

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
        handoff_analysis["files"].append(
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
    (output_dir / "model_handoff_analysis.json").write_text(
        json.dumps(handoff_analysis, indent=2),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "input_files": len(files),
        "output_path": str(output_dir / "extracted_output.xlsx"),
    }
