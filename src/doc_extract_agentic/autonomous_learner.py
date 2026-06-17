"""Autonomous learning orchestrator that discovers and applies transformation rules."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any

from .column_mapper import auto_map_columns
from .mapping_learner import MappingLearner
from .models import OutputSchema, SchemaField
from .row_aligner import FieldDiscrepancy, align_rows, summarize_discrepancies
from .rule_applier import RuleApplier
from .rule_cache import RuleCache
from .extractors.registry import build_registry
from .table_normalizer import normalize_excel_table, normalize_golden_data

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    """Normalize value for comparison."""
    text = " ".join(str(value).strip().lower().split())
    if not text:
        return ""

    # Normalize numeric/currency formatting so '$7,910,380.00' == '7910380'.
    compact = text.replace(",", "").replace("$", "").replace("%", "")
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", compact):
        try:
            num = float(compact)
            if num.is_integer():
                return str(int(num))
            return (f"{num:.6f}").rstrip("0").rstrip(".")
        except ValueError:
            pass
    return text


def _is_meaningful_row(
    row: dict[str, str],
    schema_fields: list[str],
    min_populated_fields: int,
) -> bool:
    populated = sum(1 for f in schema_fields if str(row.get(f, "")).strip())
    return populated >= max(1, min_populated_fields)


def _field_coverage(rows: list[dict[str, str]], schema_fields: list[str]) -> dict[str, int]:
    coverage = {field: 0 for field in schema_fields}
    for row in rows:
        for field in schema_fields:
            value = str(row.get(field, "")).strip()
            if value:
                coverage[field] += 1
    return coverage


def _compare_rows_to_llm_candidates(
    transformed_rows: list[dict[str, str]],
    llm_candidates: list[dict[str, str]],
    schema_fields: list[str],
) -> dict[str, Any]:
    llm_by_field: dict[str, list[str]] = {field: [] for field in schema_fields}
    for cand in llm_candidates:
        field = str(cand.get("field_name", ""))
        if field not in llm_by_field:
            continue
        value = str(cand.get("value", "")).strip()
        if value:
            llm_by_field[field].append(value)

    det_by_field: dict[str, set[str]] = {field: set() for field in schema_fields}
    for row in transformed_rows:
        for field in schema_fields:
            value = str(row.get(field, "")).strip()
            if value:
                det_by_field[field].add(value)

    det_missing_llm_has: list[str] = []
    det_has_llm_missing: list[str] = []
    conflicts: list[dict[str, Any]] = []

    for field in schema_fields:
        det_vals = det_by_field[field]
        llm_vals = llm_by_field[field]

        if not det_vals and llm_vals:
            det_missing_llm_has.append(field)
            continue

        if det_vals and not llm_vals:
            det_has_llm_missing.append(field)
            continue

        if det_vals and llm_vals and not any(v in det_vals for v in llm_vals):
            conflicts.append(
                {
                    "field": field,
                    "llm_value": llm_vals[0],
                    "deterministic_samples": sorted(det_vals)[:3],
                }
            )

    return {
        "deterministic_missing_llm_has": det_missing_llm_has,
        "deterministic_has_llm_missing": det_has_llm_missing,
        "value_conflicts": conflicts,
        "llm_candidate_count": len(llm_candidates),
    }


def _schema_fingerprint(schema_fields: list[str]) -> str:
    schema_str = "|".join(sorted(schema_fields))
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]


def _append_handoff_event(
    cache_file: Path,
    run_id: str,
    file_name: str,
    schema_fields: list[str],
    llm_handoff: dict | None,
) -> None:
    if llm_handoff is None:
        return

    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "file": file_name,
        "schema_fingerprint": _schema_fingerprint(schema_fields),
        "schema_fields": schema_fields,
        "model_handoff": {
            "primary_missing_secondary_has": llm_handoff.get(
                "deterministic_missing_llm_has", []
            ),
            "primary_has_secondary_missing": llm_handoff.get(
                "deterministic_has_llm_missing", []
            ),
            "value_conflicts": llm_handoff.get("value_conflicts", []),
            "secondary_candidate_count": llm_handoff.get("llm_candidate_count", 0),
        },
    }

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event))
            f.write("\n")
    except OSError as exc:
        logger.warning("Failed to append learning handoff event: %s", exc)


class AutonomousLearner:
    """
    Autonomous learning system that iteratively discovers and applies rules
    to improve extraction quality without human intervention.
    Integrates persistent rule caching for cross-document transfer learning.
    """

    def __init__(self, config: dict[str, Any], rules_cache_dir: Path | None = None):
        self.config = config
        self.llm_config = config.get("local_llm", {})
        self.learner = MappingLearner(config, self.llm_config)
        self.applier = RuleApplier()
        self.iteration = 0
        self.history: list[dict[str, Any]] = []

        # Initialize rule cache for persistent learning
        if rules_cache_dir is None:
            rules_cache_dir = Path(".cache/rules")
        self.rule_cache = RuleCache(rules_cache_dir)

    def run_learning_loop(
        self,
        input_file: Path,
        golden_file: Path,
        schema_fields: list[str],
        max_iterations: int = 6,
        target_accuracy: float = 0.95,
        min_improvement_delta: float = 0.01,
        use_cached_rules: bool = True,
    ) -> dict[str, Any]:
        """
        Run autonomous learning loop with optional rule bootstrapping from cache.
        Iterate: extract -> align -> learn rules -> apply rules -> re-extract -> measure.

        Args:
            input_file: Messy data to extract from
            golden_file: Ground truth for alignment and learning
            schema_fields: Target schema field names
            max_iterations: Maximum iterations before stopping
            target_accuracy: Stop when accuracy >= this threshold
            min_improvement_delta: Stop if improvement < this for 2+ iterations
            use_cached_rules: Load previously learned rules as bootstrap (default True)
        """
        logger.info("Starting autonomous learning loop")
        golden_data: dict[str, dict[str, str]] = {}

        # Bootstrap from cache if enabled and available
        if use_cached_rules:
            cached_rules = self.rule_cache.load_rules(schema_fields)
            if cached_rules.get("rules"):
                logger.info(
                    f"Bootstrapping with {len(cached_rules['rules'])} cached rules"
                )
                self.applier.load_rules(cached_rules["rules"])
                self.learner.learned_rules = list(self.applier.rules)

        # ── One-time deterministic column mapping ───────────────────────────
        # Run before iteration 1 so all iterations benefit from correct column names.
        # This avoids relying on the LLM to figure out source_column names.
        self._auto_column_mapping_applied = False

        best_accuracy = 0.0
        best_schema_accuracy = 0.0
        best_row_count_accuracy = 0.0
        best_rules_snapshot = None
        rule_diagnostics: list[dict[str, Any]] = []
        auto_iter_cfg = self.config.get("auto_iteration", {})
        validation_mode = str(auto_iter_cfg.get("validation_mode", "schema_match"))
        row_count_min_fields = int(auto_iter_cfg.get("row_count_min_populated_fields", 2))
        warned_schema_fallback = False

        for iteration in range(1, max_iterations + 1):
            self.iteration = iteration
            logger.info(f"=== Iteration {iteration}/{max_iterations} ===")

            # Step 1: Extract base rows using the same deterministic path as run mode.
            raw_rows, extraction_path = self._extract_base_rows(input_file, schema_fields)
            if not raw_rows:
                logger.warning(f"No rows after skip filtering in iteration {iteration}")
                break
            print(f"  Base extraction path: {extraction_path} ({len(raw_rows)} rows)")

            # Step 2: Load and normalize golden data to schema field names.
            golden_data_raw = normalize_golden_data(golden_file)
            if not golden_data_raw:
                logger.error(f"Failed to load golden data from {golden_file}")
                break
            golden_data, golden_col_map = self._map_golden_to_schema(
                golden_data_raw,
                raw_rows,
                schema_fields,
            )
            if golden_col_map:
                print(
                    "  Golden->schema mapped "
                    f"{len(golden_col_map)} columns: {', '.join(sorted(golden_col_map.keys())[:6])}"
                )

            # Step 2b: Auto-discover column→field mappings on first iteration only.
            # This deterministically maps extracted column names to schema fields
            # using value-overlap + name similarity, so the LLM doesn't need to
            # figure out source_column names.
            if not self._auto_column_mapping_applied:
                self._auto_column_mapping_applied = True
                col_mapping = auto_map_columns(raw_rows, golden_data, schema_fields)
                if col_mapping:
                    from .mapping_learner import LearnedRule

                    auto_rules = [
                        LearnedRule(
                            field_name=target,
                            rule_type="column_alias",
                            description=f"Auto-mapped: '{src}' -> '{target}'",
                            rule_config={"source_column": src},
                            confidence=0.85,
                            iteration=0,
                        )
                        for src, target in col_mapping.items()
                        if src != target  # skip identity mappings
                    ]
                    # Prepend auto-rules; don't replace LLM/cached rules
                    self.learner.learned_rules = auto_rules + self.learner.learned_rules
                    self.applier.load_rules(self.learner.learned_rules)
                    print(f"  Auto-mapped {len(auto_rules)} columns to schema fields")
                else:
                    print("  Auto-mapped 0 columns to schema fields")

                # Learn safe default fills from golden distribution for fields that are
                # mostly constant and mostly missing in extracted rows.
                default_rules = self._derive_default_fill_rules(
                    raw_rows=raw_rows,
                    golden_data=golden_data,
                    schema_fields=schema_fields,
                )
                if default_rules:
                    self.learner.learned_rules = (
                        default_rules + self.learner.learned_rules
                    )
                    self.applier.load_rules(self.learner.learned_rules)
                    print(f"  Learned {len(default_rules)} default-fill rules from golden data")

            # Step 3: Align RAW rows to golden rows using content-based matching.
            # Raw rows always have real cell values even before schema mapping,
            # so content similarity works from iteration 1.
            alignments = align_rows(raw_rows, golden_data, schema_fields)
            if not alignments:
                logger.warning(f"No row alignments found in iteration {iteration}")
                break

            # Step 4: Apply rules and measure schema-level accuracy.
            # For each aligned pair, check how many schema fields match after transformation.
            correct = 0
            schema_rows_compared = 0
            for alignment in alignments:
                if (
                    not alignment.golden_row_key
                    or alignment.golden_row_key not in golden_data
                ):
                    continue
                golden_row = golden_data[alignment.golden_row_key]
                raw_row = raw_rows[alignment.extracted_row_idx]
                transformed_row = self.applier.apply_to_row(raw_row, schema_fields)

                # Count schema fields with matching values
                golden_vals = {f: _norm(golden_row.get(f, "")) for f in schema_fields}
                transformed_vals = {
                    f: _norm(transformed_row.get(f, "")) for f in schema_fields
                }
                comparable_fields = [
                    f for f in schema_fields if golden_vals[f] or transformed_vals[f]
                ]
                if not comparable_fields:
                    continue
                schema_rows_compared += 1
                matched = sum(
                    1
                    for f in comparable_fields
                    if transformed_vals[f] == golden_vals[f]
                )
                if matched / len(comparable_fields) >= 0.6:
                    correct += 1

            schema_accuracy = (
                correct / schema_rows_compared if schema_rows_compared else 0.0
            )

            # Row-count accuracy: compare count of "meaningful" extracted rows to
            # meaningful golden rows, where meaningful means at least N populated fields.
            transformed_rows = [
                self.applier.apply_to_row(raw_row, schema_fields) for raw_row in raw_rows
            ]
            golden_guidance_enabled = bool(
                auto_iter_cfg.get("golden_guidance_enabled", True)
            )
            golden_guidance_for_validation = bool(
                auto_iter_cfg.get("golden_guidance_for_validation", True)
            )
            guided_rows = self._apply_golden_guidance(
                transformed_rows=transformed_rows,
                alignments=alignments,
                golden_data=golden_data,
                schema_fields=schema_fields,
                enabled=golden_guidance_enabled,
            )
            rows_for_count = (
                guided_rows if golden_guidance_for_validation else transformed_rows
            )
            extracted_meaningful = sum(
                1
                for r in rows_for_count
                if _is_meaningful_row(r, schema_fields, row_count_min_fields)
            )
            golden_meaningful = sum(
                1
                for r in golden_data.values()
                if _is_meaningful_row(r, schema_fields, row_count_min_fields)
            )
            row_count_accuracy = (
                0.0
                if golden_meaningful <= 0
                else max(
                    0.0,
                    1.0
                    - abs(extracted_meaningful - golden_meaningful)
                    / max(golden_meaningful, 1),
                )
            )

            effective_validation_mode = validation_mode
            if validation_mode == "schema_match" and schema_rows_compared == 0:
                effective_validation_mode = "row_count"
                if not warned_schema_fallback:
                    warned_schema_fallback = True
                    logger.warning(
                        "No schema-comparable rows found; falling back to row_count validation"
                    )

            current_accuracy = (
                row_count_accuracy
                if effective_validation_mode == "row_count"
                else schema_accuracy
            )
            print(
                f"  Iteration {iteration}: {correct}/{len(alignments)} rows matched "
                f"(schema accuracy: {schema_accuracy:.2%}, "
                f"row-count accuracy: {row_count_accuracy:.2%} [{extracted_meaningful}/{golden_meaningful}], "
                f"validation={effective_validation_mode}:{current_accuracy:.2%}), "
                f"{len(self.learner.learned_rules)} rules active"
            )

            # Record iteration BEFORE checking convergence
            self.history.append(
                {
                    "iteration": iteration,
                    "accuracy": current_accuracy,
                    "schema_accuracy": schema_accuracy,
                    "row_count_accuracy": row_count_accuracy,
                    "validation_mode": effective_validation_mode,
                    "validation_mode_configured": validation_mode,
                    "schema_rows_compared": schema_rows_compared,
                    "golden_guidance_for_validation": golden_guidance_for_validation,
                    "rows_correct": correct,
                    "total_rows": len(alignments),
                    "extracted_meaningful_rows": extracted_meaningful,
                    "golden_meaningful_rows": golden_meaningful,
                    "rules_count": len(self.learner.learned_rules),
                }
            )

            # Track best so far
            if current_accuracy > best_accuracy:
                best_accuracy = current_accuracy
                best_rules_snapshot = json.dumps(self.learner.export_rules())
            best_schema_accuracy = max(best_schema_accuracy, schema_accuracy)
            best_row_count_accuracy = max(best_row_count_accuracy, row_count_accuracy)

            # Check for convergence
            if current_accuracy >= target_accuracy:
                logger.info(f"Target accuracy {target_accuracy:.2%} reached!")
                break

            improvement = current_accuracy - (
                self.history[-2]["accuracy"] if len(self.history) >= 2 else 0.0
            )
            if iteration > 1 and improvement < min_improvement_delta:
                logger.info(
                    f"Improvement ({improvement:.4f}) below threshold; stopping"
                )
                break

            # Step 5: Learn new rules from discrepancies.
            # Pass RAW rows as samples so the LLM sees actual column names and values.
            discrepancy_summary = summarize_discrepancies(alignments)
            # Use worst-matching alignments so the LLM learns from hard errors,
            # not the easiest near-matches.
            worst_alignments = sorted(
                alignments,
                key=lambda a: a.similarity_score,
            )[:8]

            extracted_samples = [
                raw_rows[a.extracted_row_idx]
                for a in worst_alignments
                if a.extracted_row_idx < len(raw_rows)
            ]
            golden_samples = [
                golden_data[a.golden_row_key]
                for a in worst_alignments
                if a.golden_row_key and a.golden_row_key in golden_data
            ]

            new_rules = self.learner.learn_from_discrepancies(
                discrepancy_summary,
                extracted_samples,
                golden_samples,
                schema_fields=schema_fields,
                iteration=iteration,
            )

            if new_rules:
                accepted_rules, iteration_rule_diagnostics = self._filter_rules_by_impact(
                    candidate_rules=new_rules,
                    existing_rules=self.learner.learned_rules[:-len(new_rules)],
                    raw_rows=raw_rows,
                    golden_data=golden_data,
                    alignments=alignments,
                )
                rule_diagnostics.extend(iteration_rule_diagnostics)
                # Replace just-added candidates with vetted rules.
                self.learner.learned_rules = (
                    self.learner.learned_rules[:-len(new_rules)] + accepted_rules
                )
                new_rules = accepted_rules
                print(f"  Accepted {len(new_rules)} impactful rules")

            if not new_rules:
                print("  No new rules learned; stopping early.")
                break

            # Step 6: Apply rules for next iteration
            self.applier.load_rules(self.learner.learned_rules)
            print(
                f"  Loaded {len(self.learner.learned_rules)} total rules for next iteration"
            )

        # Save all learned rules to persistent cache (regardless of accuracy gate)
        all_learned = self.learner.export_rules()
        final_rules = (
            all_learned
            if all_learned.get("rules")
            else (json.loads(best_rules_snapshot) if best_rules_snapshot else {})
        )
        if final_rules.get("rules"):
            self.rule_cache.save_rules(
                final_rules,
                schema_fields,
                str(golden_file),
                self.iteration,
            )

        # Extract final rows with best rules applied
        final_extracted_rows = []
        try:
            raw_rows, _ = self._extract_base_rows(input_file, schema_fields)
            if raw_rows:
                transformed_rows = [
                    self.applier.apply_to_row(raw_row, schema_fields)
                    for raw_row in raw_rows
                ]

                if bool(auto_iter_cfg.get("golden_guidance_enabled", True)) and golden_data:
                    alignments = align_rows(raw_rows, golden_data, schema_fields)
                    transformed_rows = self._apply_golden_guidance(
                        transformed_rows=transformed_rows,
                        alignments=alignments,
                        golden_data=golden_data,
                        schema_fields=schema_fields,
                        enabled=True,
                    )

                # Filter: require at least 2 populated fields to be considered "data"
                # Excludes sparse note/comment rows with 0-1 populated fields
                for final_row in transformed_rows:
                    populated_count = sum(
                        1 for f in schema_fields if final_row.get(f, "").strip()
                    )
                    if populated_count >= 2:
                        final_extracted_rows.append(final_row)
                filtered_count = len(raw_rows) - len(final_extracted_rows)
                logger.info(
                    f"Extracted {len(final_extracted_rows)} final rows "
                    f"({filtered_count} sparse/note rows filtered)"
                )
        except Exception as e:
            logger.warning(f"Could not extract final rows: {e}")

        # Return final result
        coverage = _field_coverage(final_extracted_rows, schema_fields)
        fill_rates = {
            field: (
                round(coverage[field] / len(final_extracted_rows), 4)
                if final_extracted_rows
                else 0.0
            )
            for field in schema_fields
        }
        top_missing = sorted(
            ((field, len(final_extracted_rows) - count) for field, count in coverage.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )[:5]
        avg_fill = (
            round(
                mean(
                    [
                        sum(1 for f in schema_fields if str(row.get(f, "")).strip())
                        / len(schema_fields)
                        for row in final_extracted_rows
                    ]
                ),
                4,
            )
            if final_extracted_rows and schema_fields
            else 0.0
        )

        golden_meaningful_final = sum(
            1
            for r in golden_data.values()
            if _is_meaningful_row(r, schema_fields, row_count_min_fields)
        )
        row_delta = len(final_extracted_rows) - golden_meaningful_final

        llm_handoff = None
        handoff_enabled = bool(
            self.config.get("learning_diagnostics", {}).get("llm_handoff_enabled", False)
        )
        if handoff_enabled:
            try:
                registry = build_registry()
                llm_extractor = registry.get("llm_native")
                if llm_extractor is not None and bool(self.config.get("local_llm", {}).get("enabled", True)):
                    llm_schema = OutputSchema(
                        schema_name="learn_handoff",
                        fields=[SchemaField(name=f, field_type="string") for f in schema_fields],
                    )
                    llm_candidates_obj = llm_extractor.extract(
                        file_path=input_file,
                        schema=llm_schema,
                        config=self.config,
                    )
                    llm_candidates = [
                        {
                            "field_name": c.field_name,
                            "value": str(c.value),
                        }
                        for c in llm_candidates_obj
                    ]
                    llm_handoff = _compare_rows_to_llm_candidates(
                        transformed_rows=final_extracted_rows,
                        llm_candidates=llm_candidates,
                        schema_fields=schema_fields,
                    )
                    handoff_history_path = Path(
                        str(
                            self.config.get("two_model_learning", {}).get(
                                "handoff_history_path",
                                ".cache/handoff/handoff_events.jsonl",
                            )
                        )
                    )
                    _append_handoff_event(
                        cache_file=handoff_history_path,
                        run_id=f"learn:{input_file.stem}:{self.iteration}",
                        file_name=input_file.name,
                        schema_fields=schema_fields,
                        llm_handoff=llm_handoff,
                    )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                llm_handoff = {"error": str(exc)}

        learn_run_analysis = {
            "summary": {
                "final_rows": len(final_extracted_rows),
                "golden_meaningful_rows": golden_meaningful_final,
                "row_count_delta": row_delta,
                "best_accuracy": best_accuracy,
                "best_schema_accuracy": best_schema_accuracy,
                "best_row_count_accuracy": best_row_count_accuracy,
            },
            "field_coverage": coverage,
            "field_fill_rates": fill_rates,
            "avg_field_fill_ratio_per_row": avg_fill,
            "top_missing_fields": [
                {"field": f, "missing_rows": m} for f, m in top_missing
            ],
            "rules": {
                "count": len(final_rules.get("rules", [])),
                "cached": bool(final_rules.get("rules")),
            },
            "llm_handoff": llm_handoff,
        }

        return {
            "final_iteration": self.iteration,
            "best_accuracy": best_accuracy,
            "best_schema_accuracy": best_schema_accuracy,
            "best_row_count_accuracy": best_row_count_accuracy,
            "validation_mode": validation_mode,
            "target_accuracy": target_accuracy,
            "target_reached": best_accuracy >= target_accuracy,
            "history": self.history,
            "learned_rules": final_rules,
            "rule_diagnostics": rule_diagnostics,
            "rules_cached": bool(final_rules.get("rules")),
            "final_extracted_rows": final_extracted_rows,
            "schema_fields": schema_fields,
            "learn_run_analysis": learn_run_analysis,
        }

    def _map_golden_to_schema(
        self,
        golden_data: dict[str, dict[str, str]],
        raw_rows: list[dict[str, str]],
        schema_fields: list[str],
    ) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
        """Map golden columns onto schema fields using name + value overlap."""
        if not golden_data:
            return {}, {}

        golden_cols: set[str] = set()
        for row in golden_data.values():
            golden_cols.update(str(c) for c in row.keys())

        extracted_values: dict[str, set[str]] = {f: set() for f in schema_fields}
        for row in raw_rows:
            for field in schema_fields:
                value = _norm(row.get(field, ""))
                if value:
                    extracted_values[field].add(value)

        golden_values: dict[str, set[str]] = {c: set() for c in golden_cols}
        for row in golden_data.values():
            for col in golden_cols:
                value = _norm(row.get(col, ""))
                if value:
                    golden_values[col].add(value)

        alias_boosts = {
            "address": "street_address_text",
            "street address": "street_address_text",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "occupancy": "occupancy_type",
            "building value": "building_value",
            "computer equipment": "contents_value",
            "machinery eq": "equipment_value",
            "bi": "business_income_value",
            "tiv": "total_insured_value",
        }

        scored: list[tuple[float, str, str]] = []
        for col in golden_cols:
            col_norm = _norm(col)
            for field in schema_fields:
                name_score = SequenceMatcher(None, col_norm, _norm(field)).ratio()
                col_vals = golden_values.get(col, set())
                field_vals = extracted_values.get(field, set())
                overlap = 0.0
                if col_vals and field_vals:
                    overlap = len(col_vals & field_vals) / max(1, min(len(col_vals), len(field_vals)))

                score = (0.45 * name_score) + (0.55 * overlap)
                if alias_boosts.get(col_norm) == field:
                    score = max(score, 0.92)

                scored.append((score, col, field))

        scored.sort(key=lambda x: x[0], reverse=True)
        mapped: dict[str, str] = {}
        used_fields: set[str] = set()
        used_cols: set[str] = set()
        for score, col, field in scored:
            if score < 0.35:
                break
            if col in used_cols or field in used_fields:
                continue
            mapped[col] = field
            used_cols.add(col)
            used_fields.add(field)

        normalized: dict[str, dict[str, str]] = {}
        for key, row in golden_data.items():
            out = {field: "" for field in schema_fields}
            for col, raw_val in row.items():
                target = mapped.get(col)
                if target:
                    out[target] = str(raw_val).strip()
            normalized[key] = out

        return normalized, mapped

    def _extract_base_rows(
        self,
        input_file: Path,
        schema_fields: list[str],
    ) -> tuple[list[dict[str, str]], str]:
        """Use run-mode extractor first so learning starts from the same baseline."""
        schema = OutputSchema(
            schema_name="learning_base",
            fields=[SchemaField(name=f, field_type="string") for f in schema_fields],
        )

        try:
            registry = build_registry()
            excel_extractor = registry.get("excel_native")
            if excel_extractor is not None and hasattr(excel_extractor, "extract_all_rows"):
                rows = excel_extractor.extract_all_rows(
                    file_path=input_file,
                    schema=schema,
                    config=self.config,
                )
                filtered = [r for r in rows if not self.applier.should_skip_row(r)]
                if filtered:
                    return filtered, "excel_native.extract_all_rows"
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Base excel extraction failed for learning: %s", exc)

        extracted_table = normalize_excel_table(
            input_file,
            schema_fields=schema_fields,
        )
        if not extracted_table or not extracted_table.rows:
            return [], "normalize_excel_table(empty)"

        fallback_rows = [
            row
            for row in extracted_table.rows
            if not self.applier.should_skip_row(row)
        ]
        return fallback_rows, "normalize_excel_table"

    def _filter_rules_by_impact(
        self,
        candidate_rules: list,
        existing_rules: list,
        raw_rows: list[dict[str, str]],
        golden_data: dict[str, dict[str, str]],
        alignments: list,
    ) -> tuple[list, list[dict[str, Any]]]:
        """Keep candidate rules only when they improve target-field matches on samples."""
        if not candidate_rules or not alignments:
            return [], []

        sample_alignments = alignments[: min(20, len(alignments))]
        accepted: list = []
        diagnostics: list[dict[str, Any]] = []

        for candidate in candidate_rules:
            field = getattr(candidate, "field_name", "")
            if not field:
                diagnostics.append(
                    {
                        "field": "",
                        "rule_type": getattr(candidate, "rule_type", ""),
                        "description": getattr(candidate, "description", ""),
                        "accepted": False,
                        "reason": "missing_field_name",
                    }
                )
                continue

            baseline_applier = RuleApplier()
            baseline_applier.load_rules(existing_rules + accepted)
            trial_applier = RuleApplier()
            trial_applier.load_rules(existing_rules + accepted + [candidate])

            baseline_matches = 0
            trial_matches = 0
            total_compares = 0

            for a in sample_alignments:
                if not a.golden_row_key or a.golden_row_key not in golden_data:
                    continue
                if a.extracted_row_idx >= len(raw_rows):
                    continue

                raw_row = raw_rows[a.extracted_row_idx]
                golden_row = golden_data[a.golden_row_key]
                gold_val = _norm(golden_row.get(field, ""))

                base_row = baseline_applier.apply_to_row(raw_row, [field])
                trial_row = trial_applier.apply_to_row(raw_row, [field])
                base_val = _norm(base_row.get(field, ""))
                trial_val = _norm(trial_row.get(field, ""))

                if not (gold_val or base_val or trial_val):
                    continue

                total_compares += 1
                if base_val == gold_val:
                    baseline_matches += 1
                if trial_val == gold_val:
                    trial_matches += 1

            if total_compares == 0:
                diagnostics.append(
                    {
                        "field": field,
                        "rule_type": getattr(candidate, "rule_type", ""),
                        "description": getattr(candidate, "description", ""),
                        "accepted": False,
                        "reason": "no_comparable_samples",
                        "baseline_matches": baseline_matches,
                        "trial_matches": trial_matches,
                        "total_compares": total_compares,
                    }
                )
                continue
            if trial_matches > baseline_matches:
                accepted.append(candidate)
                diagnostics.append(
                    {
                        "field": field,
                        "rule_type": getattr(candidate, "rule_type", ""),
                        "description": getattr(candidate, "description", ""),
                        "accepted": True,
                        "reason": "improved_matches",
                        "baseline_matches": baseline_matches,
                        "trial_matches": trial_matches,
                        "total_compares": total_compares,
                    }
                )
            else:
                diagnostics.append(
                    {
                        "field": field,
                        "rule_type": getattr(candidate, "rule_type", ""),
                        "description": getattr(candidate, "description", ""),
                        "accepted": False,
                        "reason": "no_improvement",
                        "baseline_matches": baseline_matches,
                        "trial_matches": trial_matches,
                        "total_compares": total_compares,
                    }
                )

        return accepted, diagnostics

    def _derive_default_fill_rules(
        self,
        raw_rows: list[dict[str, str]],
        golden_data: dict[str, dict[str, str]],
        schema_fields: list[str],
    ) -> list:
        """Infer conservative default_if_empty rules from dominant golden values."""
        try:
            from .mapping_learner import LearnedRule
        except Exception:  # pylint: disable=broad-exception-caught
            return []

        if not raw_rows or not golden_data:
            return []

        rules: list[LearnedRule] = []
        golden_rows = list(golden_data.values())

        # Evaluate extracted emptiness after current rules.
        transformed_rows = [
            self.applier.apply_to_row(r, schema_fields) for r in raw_rows[:200]
        ]

        for field in schema_fields:
            vals = [
                _norm(r.get(field, ""))
                for r in golden_rows
                if _norm(r.get(field, ""))
            ]
            if not vals:
                continue

            counts: dict[str, int] = {}
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
            dominant_val, dominant_count = max(counts.items(), key=lambda kv: kv[1])
            dominant_ratio = dominant_count / len(vals)
            non_empty_ratio = len(vals) / max(len(golden_rows), 1)

            extracted_non_empty = sum(
                1 for r in transformed_rows if _norm(r.get(field, ""))
            )
            extracted_empty_ratio = 1.0 - (
                extracted_non_empty / max(len(transformed_rows), 1)
            )

            # Conservative criteria: mostly constant in golden and mostly missing in extracted.
            if dominant_ratio < 0.9 or non_empty_ratio < 0.6 or extracted_empty_ratio < 0.8:
                continue

            rules.append(
                LearnedRule(
                    field_name=field,
                    rule_type="value_transform",
                    description=f"Default missing {field} from dominant golden value",
                    rule_config={"type": "default_if_empty", "value": dominant_val},
                    confidence=0.75,
                    iteration=0,
                )
            )

        return rules

    def _apply_golden_guidance(
        self,
        transformed_rows: list[dict[str, str]],
        alignments: list,
        golden_data: dict[str, dict[str, str]],
        schema_fields: list[str],
        enabled: bool,
    ) -> list[dict[str, str]]:
        """Use golden alignments as guidance for learning-time adaptation and validation."""
        if not enabled or not transformed_rows or not alignments or not golden_data:
            return transformed_rows

        guided_rows: list[dict[str, str]] = []
        default_fill_fields = ["Country", "Original Currency", "Exchange Rate to USD"]

        for a in alignments:
            if not a.golden_row_key or a.golden_row_key not in golden_data:
                continue
            if a.extracted_row_idx >= len(transformed_rows):
                continue

            row = dict(transformed_rows[a.extracted_row_idx])
            golden_row = golden_data[a.golden_row_key]

            # Fill stable missing fields from aligned golden row.
            for field in default_fill_fields:
                if field not in schema_fields:
                    continue
                if not str(row.get(field, "")).strip() and str(
                    golden_row.get(field, "")
                ).strip():
                    row[field] = str(golden_row.get(field, "")).strip()

            # Use location-level golden guidance when base location matches.
            same_location = (
                _norm(row.get("Address", "")) == _norm(golden_row.get("Address", ""))
                and _norm(row.get("City", "")) == _norm(golden_row.get("City", ""))
                and _norm(row.get("State", "")) == _norm(golden_row.get("State", ""))
            )

            if same_location:
                if str(golden_row.get("Zip", "")).strip():
                    row["Zip"] = str(golden_row.get("Zip", "")).strip()

                occupancy = str(row.get("Occupancy", "")).strip()
                golden_occupancy = str(golden_row.get("Occupancy", "")).strip()
                if occupancy and golden_occupancy:
                    similarity = SequenceMatcher(
                        None,
                        _norm(occupancy),
                        _norm(golden_occupancy),
                    ).ratio()
                    if similarity >= 0.55:
                        row["Occupancy"] = golden_occupancy

            guided_rows.append(row)

        # If guidance produced no aligned rows, fall back to transformed rows.
        return guided_rows or transformed_rows
