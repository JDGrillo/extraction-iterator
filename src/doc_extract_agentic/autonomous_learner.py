"""Autonomous learning orchestrator that discovers and applies transformation rules."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .column_mapper import auto_map_columns
from .mapping_learner import MappingLearner
from .row_aligner import FieldDiscrepancy, align_rows, summarize_discrepancies
from .rule_applier import RuleApplier
from .rule_cache import RuleCache
from .table_normalizer import normalize_excel_table, normalize_golden_data

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    """Normalize value for comparison."""
    return " ".join(str(value).strip().lower().split())


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
        best_rules_snapshot = None

        for iteration in range(1, max_iterations + 1):
            self.iteration = iteration
            logger.info(f"=== Iteration {iteration}/{max_iterations} ===")

            # Step 1: Extract/normalize table from messy data
            extracted_table = normalize_excel_table(input_file)
            if not extracted_table or not extracted_table.rows:
                logger.error(f"Failed to extract table from {input_file}")
                break

            # Filter rows that should be skipped (empty rows, header rows, etc.)
            raw_rows = [
                row
                for row in extracted_table.rows
                if not self.applier.should_skip_row(row)
            ]
            if not raw_rows:
                logger.warning(f"No rows after skip filtering in iteration {iteration}")
                break

            # Step 2: Load golden data
            golden_data = normalize_golden_data(golden_file)
            if not golden_data:
                logger.error(f"Failed to load golden data from {golden_file}")
                break

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
                populated_fields = [f for f in schema_fields if golden_vals[f]]
                if not populated_fields:
                    continue
                matched = sum(
                    1 for f in populated_fields if transformed_vals[f] == golden_vals[f]
                )
                if matched / len(populated_fields) >= 0.8:
                    correct += 1

            current_accuracy = correct / len(alignments) if alignments else 0.0
            print(
                f"  Iteration {iteration}: {correct}/{len(alignments)} rows matched "
                f"(schema accuracy: {current_accuracy:.2%}), "
                f"{len(self.learner.learned_rules)} rules active"
            )

            # Record iteration BEFORE checking convergence
            self.history.append(
                {
                    "iteration": iteration,
                    "accuracy": current_accuracy,
                    "rows_correct": correct,
                    "total_rows": len(alignments),
                    "rules_count": len(self.learner.learned_rules),
                }
            )

            # Track best so far
            if current_accuracy > best_accuracy:
                best_accuracy = current_accuracy
                best_rules_snapshot = json.dumps(self.learner.export_rules())

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
            extracted_samples = [
                raw_rows[a.extracted_row_idx]
                for a in alignments[:5]
                if a.extracted_row_idx < len(raw_rows)
            ]
            golden_samples = [
                golden_data[a.golden_row_key]
                for a in alignments[:5]
                if a.golden_row_key and a.golden_row_key in golden_data
            ]

            new_rules = self.learner.learn_from_discrepancies(
                discrepancy_summary,
                extracted_samples,
                golden_samples,
                iteration=iteration,
            )

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
            extracted_table = normalize_excel_table(input_file)
            if extracted_table and extracted_table.rows:
                raw_rows = [
                    row
                    for row in extracted_table.rows
                    if not self.applier.should_skip_row(row)
                ]
                # Apply best rules to all rows
                for raw_row in raw_rows:
                    final_row = self.applier.apply_to_row(raw_row, schema_fields)
                    # Filter: require at least 2 populated fields to be considered "data"
                    # Excludes sparse note/comment rows with 0-1 populated fields
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
        return {
            "final_iteration": self.iteration,
            "best_accuracy": best_accuracy,
            "target_accuracy": target_accuracy,
            "target_reached": best_accuracy >= target_accuracy,
            "history": self.history,
            "learned_rules": final_rules,
            "rules_cached": bool(final_rules.get("rules")),
            "final_extracted_rows": final_extracted_rows,
            "schema_fields": schema_fields,
        }
