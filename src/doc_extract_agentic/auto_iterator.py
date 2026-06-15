"""Autonomous local-LLM extraction loop with deterministic evaluation gates."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config, load_schema
from .example_promoter import promote_validated_examples
from .example_store import ExampleStore
from .evaluator import evaluate_extraction, write_evaluation_report
from .extractors.excel_native import ExcelNativeExtractor
from .improvement_agent import apply_alias_updates, propose_alias_updates
from .pipeline import run_pipeline


@dataclass
class AutoIterateConfig:
    max_iterations: int = 6
    target_accuracy: float = 0.97
    min_improvement_delta: float = 0.002


@dataclass
class IterationSnapshot:
    iteration: int
    run_id: str
    validation_accuracy: float
    holdout_accuracy: float
    total_cells: int
    correct_cells: int
    proposal_fields: int
    aliases_applied: int
    promoted: bool
    rationale: str
    regressed_fields: list[str]
    promoted_examples: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutoIterator:
    def __init__(
        self,
        input_dir: Path,
        output_base_dir: Path,
        schema_path: Path,
        config_path: Path,
        ground_truth_path: Path,
        auto_cfg: AutoIterateConfig,
    ) -> None:
        self.input_dir = input_dir
        self.output_base_dir = output_base_dir
        self.schema_path = schema_path
        self.config_path = config_path
        self.ground_truth_path = ground_truth_path
        self.auto_cfg = auto_cfg

        self.cfg = load_config(config_path)
        self.history: list[IterationSnapshot] = []
        self.decisions: list[str] = []

        self.working_schema_path = self.output_base_dir / "working_schema.json"
        self.staging_schema_path = self.output_base_dir / "staging_schema.json"
        self.example_store_path = Path(
            str(
                self.cfg.get("llm_extractor", {}).get(
                    "example_store", "./examples/training_examples.jsonl"
                )
            )
        )
        self.split_by_source = self._load_example_splits(self.example_store_path)

    def run(self) -> dict[str, Any]:
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.schema_path, self.working_schema_path)

        print("\n" + "=" * 72)
        print("LOCAL LLM AUTONOMOUS EXTRACTION LOOP")
        print("=" * 72)
        print(f"Input: {self.input_dir}")
        print(f"Ground truth: {self.ground_truth_path}")
        print(f"Working schema: {self.working_schema_path}")

        for iteration in range(1, self.auto_cfg.max_iterations + 1):
            print("\n" + "-" * 72)
            print(f"Iteration {iteration}/{self.auto_cfg.max_iterations}")
            print("-" * 72)

            run_dir = self.output_base_dir / f"iter_{iteration:02d}" / "candidate"
            candidate_eval = self._run_and_evaluate(
                run_dir, self.working_schema_path, split="validation"
            )
            candidate_holdout = self._evaluate_existing_output(
                run_dir=run_dir,
                split="holdout",
            )
            print(
                f"Candidate validation accuracy: {candidate_eval.accuracy:.2%} "
                f"({candidate_eval.correct_cells}/{candidate_eval.total_cells})"
            )
            print(f"Candidate holdout accuracy: {candidate_holdout.accuracy:.2%}")

            if candidate_eval.accuracy >= self.auto_cfg.target_accuracy:
                self.history.append(
                    IterationSnapshot(
                        iteration=iteration,
                        run_id=self._read_run_id(run_dir),
                        validation_accuracy=candidate_eval.accuracy,
                        holdout_accuracy=candidate_holdout.accuracy,
                        total_cells=candidate_eval.total_cells,
                        correct_cells=candidate_eval.correct_cells,
                        proposal_fields=0,
                        aliases_applied=0,
                        promoted=False,
                        rationale="Target accuracy reached",
                        regressed_fields=[],
                        promoted_examples=0,
                    )
                )
                self.decisions.append("[STOP] Target accuracy reached")
                break

            proposal, aliases_applied = self._propose_and_stage_updates(
                failures=candidate_eval.failures
            )

            if aliases_applied == 0:
                self.history.append(
                    IterationSnapshot(
                        iteration=iteration,
                        run_id=self._read_run_id(run_dir),
                        validation_accuracy=candidate_eval.accuracy,
                        holdout_accuracy=candidate_holdout.accuracy,
                        total_cells=candidate_eval.total_cells,
                        correct_cells=candidate_eval.correct_cells,
                        proposal_fields=len(proposal.alias_updates),
                        aliases_applied=0,
                        promoted=False,
                        rationale=proposal.rationale,
                        regressed_fields=[],
                        promoted_examples=0,
                    )
                )
                self.decisions.append("[STOP] No promotable alias updates")
                break

            validation_dir = (
                self.output_base_dir / f"iter_{iteration:02d}" / "validation"
            )
            validation_eval = self._run_and_evaluate(
                validation_dir, self.staging_schema_path, split="validation"
            )
            validation_holdout = self._evaluate_existing_output(
                run_dir=validation_dir,
                split="holdout",
            )
            delta = validation_eval.accuracy - candidate_eval.accuracy
            regressed_fields = self._find_regressed_fields(
                baseline=candidate_eval,
                challenger=validation_eval,
            )
            field_gate_ok = self._passes_field_gate(regressed_fields)

            if (
                validation_eval.accuracy + 1e-9 >= candidate_eval.accuracy
                and delta >= self.auto_cfg.min_improvement_delta
                and field_gate_ok
            ):
                shutil.copyfile(self.staging_schema_path, self.working_schema_path)
                promoted = True
                rationale = (
                    f"Promoted staged aliases. Validation accuracy {candidate_eval.accuracy:.2%} -> "
                    f"{validation_eval.accuracy:.2%}"
                )
                self.decisions.append(f"[CONTINUE] {rationale}")
                final_eval = validation_eval
                final_holdout = validation_holdout

                promoted_examples = self._auto_promote_examples(validation_dir)
            else:
                promoted = False
                regression_msg = ""
                if regressed_fields and not field_gate_ok:
                    regression_msg = (
                        f"; field regressions blocked: {', '.join(regressed_fields)}"
                    )
                rationale = f"Rejected staged aliases (delta {delta:+.2%}{regression_msg}); kept current schema"
                self.decisions.append(f"[STOP] {rationale}")
                final_eval = candidate_eval
                final_holdout = candidate_holdout
                promoted_examples = 0

            self.history.append(
                IterationSnapshot(
                    iteration=iteration,
                    run_id=self._read_run_id(run_dir),
                    validation_accuracy=final_eval.accuracy,
                    holdout_accuracy=final_holdout.accuracy,
                    total_cells=final_eval.total_cells,
                    correct_cells=final_eval.correct_cells,
                    proposal_fields=len(proposal.alias_updates),
                    aliases_applied=aliases_applied,
                    promoted=promoted,
                    rationale=rationale,
                    regressed_fields=regressed_fields,
                    promoted_examples=promoted_examples,
                )
            )

            if not promoted:
                break

        final_schema = self.output_base_dir / "final_schema.json"
        shutil.copyfile(self.working_schema_path, final_schema)

        report = self._build_report(final_schema)
        report_path = self.output_base_dir / "iteration_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        print("\n" + "=" * 72)
        print("AUTONOMOUS LOOP COMPLETE")
        print("=" * 72)
        print(f"Iterations: {len(self.history)}")
        if self.history:
            print(
                f"Final validation accuracy: {self.history[-1].validation_accuracy:.2%}"
            )
            print(f"Final holdout accuracy: {self.history[-1].holdout_accuracy:.2%}")
        print(f"Report: {report_path}")
        print(f"Final schema: {final_schema}")

        return report

    def _run_and_evaluate(self, run_dir: Path, schema_path: Path, split: str):
        result = run_pipeline(
            input_dir=self.input_dir,
            output_dir=run_dir,
            schema=load_schema(schema_path),
            config=self.cfg,
            ground_truth=self.ground_truth_path,
        )
        _ = result

        split_set = self._split_source_files(split)
        eval_result = evaluate_extraction(
            extracted_path=run_dir / "extracted_output.xlsx",
            ground_truth_path=self.ground_truth_path,
            include_source_files=split_set,
        )
        write_evaluation_report(eval_result, run_dir / "evaluation_report.json")
        return eval_result

    def _evaluate_existing_output(self, run_dir: Path, split: str):
        split_set = self._split_source_files(split)
        return evaluate_extraction(
            extracted_path=run_dir / "extracted_output.xlsx",
            ground_truth_path=self.ground_truth_path,
            include_source_files=split_set,
        )

    def _propose_and_stage_updates(self, failures: list[dict[str, Any]]):
        raw_keys_by_file = self._collect_raw_keys()
        shutil.copyfile(self.working_schema_path, self.staging_schema_path)

        proposal = propose_alias_updates(
            config=self.cfg,
            schema_path=self.staging_schema_path,
            failures=failures,
            raw_keys_by_file=raw_keys_by_file,
        )
        aliases_applied = apply_alias_updates(
            schema_path=self.staging_schema_path,
            updates=proposal.alias_updates,
        )
        return proposal, aliases_applied

    def _collect_raw_keys(self) -> dict[str, list[str]]:
        ext = ExcelNativeExtractor()
        results: dict[str, list[str]] = {}
        for fpath in list(self.input_dir.glob("**/*.xlsx")) + list(
            self.input_dir.glob("**/*.xls")
        ):
            results[fpath.name] = ext.collect_raw_keys(fpath)
        return results

    def _read_run_id(self, run_dir: Path) -> str:
        trace_path = run_dir / "run_trace.json"
        if not trace_path.exists():
            return ""
        try:
            payload = json.loads(trace_path.read_text(encoding="utf-8"))
            return str(payload.get("run_id", ""))
        except json.JSONDecodeError:
            return ""

    def _load_example_splits(self, example_store_path: Path) -> dict[str, str]:
        if not example_store_path.exists():
            return {}

        split_by_source: dict[str, str] = {}
        for record in ExampleStore(example_store_path).load():
            source = record.source_file.strip().lower()
            if not source:
                continue
            split_by_source[source] = record.split
        return split_by_source

    def _split_source_files(self, split: str) -> set[str] | None:
        split_l = split.lower()
        if not self.split_by_source:
            return None
        return {
            source
            for source, assigned in self.split_by_source.items()
            if assigned == split_l
        }

    def _find_regressed_fields(self, baseline, challenger) -> list[str]:
        regressed: list[str] = []
        for field, bstats in baseline.per_field.items():
            cstats = challenger.per_field.get(field)
            if cstats is None:
                continue
            if cstats.get("accuracy", 0.0) + 1e-9 < bstats.get("accuracy", 0.0):
                regressed.append(field)
        return sorted(regressed)

    def _passes_field_gate(self, regressed_fields: list[str]) -> bool:
        gate_cfg = self.cfg.get("auto_learning", {}).get("field_promotion", {})
        block_any = bool(gate_cfg.get("block_on_any_regression", True))
        allowed_regressions = set(gate_cfg.get("allowed_regressed_fields", []))
        critical_fields = set(gate_cfg.get("critical_fields", []))

        if any(field in critical_fields for field in regressed_fields):
            return False

        disallowed = [f for f in regressed_fields if f not in allowed_regressions]
        if block_any and disallowed:
            return False
        return True

    def _auto_promote_examples(self, run_dir: Path) -> int:
        learn_cfg = self.cfg.get("auto_learning", {})
        if not bool(learn_cfg.get("enabled", True)):
            return 0
        if not bool(learn_cfg.get("auto_promote_examples", True)):
            return 0

        schema = load_schema(self.working_schema_path)
        promote_result = promote_validated_examples(
            input_dir=self.input_dir,
            run_dir=run_dir,
            ground_truth_path=self.ground_truth_path,
            schema_field_names=[field.name for field in schema.fields],
            example_store_path=self.example_store_path,
            split_by_source=self.split_by_source,
            promote_split=str(learn_cfg.get("promote_split", "train")),
            min_row_accuracy=float(learn_cfg.get("min_row_accuracy", 0.98)),
            min_labeled_fields=int(learn_cfg.get("min_labeled_fields", 2)),
            max_promoted_per_iteration=int(
                learn_cfg.get("max_promoted_per_iteration", 50)
            ),
            max_sheets=int(self.cfg.get("llm_extractor", {}).get("max_sheets", 5)),
            max_rows_per_sheet=int(
                self.cfg.get("llm_extractor", {}).get("max_rows_per_sheet", 80)
            ),
            max_cols_per_sheet=int(
                self.cfg.get("llm_extractor", {}).get("max_cols_per_sheet", 20)
            ),
            max_cell_chars=int(
                self.cfg.get("llm_extractor", {}).get("max_cell_chars", 120)
            ),
        )
        return promote_result.promoted_rows

    def _build_report(self, final_schema_path: Path) -> dict[str, Any]:
        holdout_accuracy = None
        if self.history:
            holdout_accuracy = self.history[-1].holdout_accuracy

        return {
            "started_at": _utc_now_iso(),
            "input_dir": str(self.input_dir),
            "ground_truth": str(self.ground_truth_path),
            "config": str(self.config_path),
            "auto_config": asdict(self.auto_cfg),
            "history": [asdict(item) for item in self.history],
            "decisions": self.decisions,
            "holdout_accuracy": holdout_accuracy,
            "final_schema": str(final_schema_path),
        }
