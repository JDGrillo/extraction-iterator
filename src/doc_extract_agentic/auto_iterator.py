"""Autonomous iteration orchestrator: extract, analyze, improve, repeat until success."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alias_promotion import AliasPromotionConfig, AliasPromotionLedger
from .config import load_config, load_schema
from .data_discovery import DataDiscoverer
from .extractor_performance_analyzer import ExtractorPerformanceAnalyzer
from .extractors.excel_native import ExcelNativeExtractor
from .extractors.pdf_native import PdfNativeExtractor
from .llm_improvement import LLMImprovementSuggester
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IterationMetrics:
    iteration: int
    timestamp: str
    field_count: int
    found_count: int
    success_rate: float
    avg_confidence: float
    critical_fields: int
    good_fields: int
    fields_below_target: int
    aliases_approved: int
    aliases_applied: int


@dataclass
class AutoIterateConfig:
    max_iterations: int = 5
    target_success_rate: float = 0.85
    min_improvement_delta: float = 0.05
    target_confidence: float = 0.75
    critical_field_threshold: float = 0.5


class AutoIterator:
    """Orchestrate autonomous extraction improvement iterations."""

    def __init__(
        self,
        input_dir: Path,
        output_base_dir: Path,
        schema_path: Path,
        config_path: Path,
        auto_cfg: AutoIterateConfig,
    ) -> None:
        self.input_dir = input_dir
        self.output_base_dir = output_base_dir
        self.schema_path = schema_path
        self.config_path = config_path
        self.auto_cfg = auto_cfg
        self.cfg = load_config(config_path)
        self.iteration_history: list[IterationMetrics] = []
        self.decisions: list[str] = []

    def run(self) -> dict[str, Any]:
        """Execute autonomous iteration loop until convergence or max iterations."""
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

        sep = "=" * 70
        print(f"\n{sep}\nAUTONOMOUS EXTRACTION ITERATION\n{sep}")
        print(f"  Input: {self.input_dir}")
        print(f"  Schema: {self.schema_path}")
        print(f"  Max iterations: {self.auto_cfg.max_iterations}")
        print(f"  Target success rate: {self.auto_cfg.target_success_rate:.0%}")
        print(f"  Min improvement delta: {self.auto_cfg.min_improvement_delta:.0%}")

        for iter_num in range(1, self.auto_cfg.max_iterations + 1):
            print(f"\n{'-' * 70}")
            print(f"[Iteration {iter_num}/{self.auto_cfg.max_iterations}]")
            print(f"{'-' * 70}")

            iter_dir = self.output_base_dir / f"iter_{iter_num:02d}"
            iter_dir.mkdir(parents=True, exist_ok=True)

            # Phase 1: Extract
            print(f"\n  [1] Running extraction ...")
            result = run_pipeline(
                input_dir=self.input_dir,
                output_dir=iter_dir,
                schema=self._load_schema(),
                config=self.cfg,
                ground_truth=None,
            )
            print(f"      ✓ Run ID: {result['run_id']}")

            # Phase 2: Analyze & measure
            print(f"\n  [2] Analyzing performance ...")
            metrics = self._measure_iteration(iter_num, iter_dir)
            self.iteration_history.append(metrics)
            self._print_metrics(metrics)

            # Phase 3: Check success criteria
            decision = self._evaluate_convergence(metrics, iter_num)
            self.decisions.append(decision)

            if decision.startswith("[STOP]"):
                print(f"\n  Decision: {decision}")
                break

            # Phase 4: Improve schema (if not final iteration)
            print(f"\n  [3] Applying improvements ...")
            aliases_approved, aliases_applied = self._apply_improvements(iter_dir)
            print(f"      ✓ Approved: {aliases_approved}, Applied: {aliases_applied}")

            if aliases_applied == 0:
                print(f"\n  No new aliases to apply; stopping iteration.")
                self.decisions.append("[STOP] No more improvements available")
                break

        # Write iteration report
        report = self._generate_report()
        report_path = self.output_base_dir / "iteration_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        print(f"\n{sep}")
        print(f"FINAL REPORT")
        print(f"{sep}")
        print(
            f"  Iterations: {len(self.iteration_history)}/{self.auto_cfg.max_iterations}"
        )
        if self.iteration_history:
            first = self.iteration_history[0]
            last = self.iteration_history[-1]
            improvement = last.success_rate - first.success_rate
            print(
                f"  First-to-last improvement: {first.success_rate:.1%} → {last.success_rate:.1%} ({improvement:+.1%})"
            )
        print(f"  Report: {report_path}")
        print(f"{sep}\n")

        return {
            "iterations": len(self.iteration_history),
            "max_iterations": self.auto_cfg.max_iterations,
            "report_path": str(report_path),
            "output_dir": str(self.output_base_dir),
            "history": [asdict(m) for m in self.iteration_history],
        }

    def _load_schema(self):
        """Load current schema from file."""
        return load_schema(self.schema_path)

    def _measure_iteration(self, iter_num: int, iter_dir: Path) -> IterationMetrics:
        """Measure extraction performance for this iteration."""
        perf_analyzer = ExtractorPerformanceAnalyzer(iter_dir)
        events = perf_analyzer.load_learning_events()

        if not events:
            return IterationMetrics(
                iteration=iter_num,
                timestamp=_utc_now_iso(),
                field_count=0,
                found_count=0,
                success_rate=0.0,
                avg_confidence=0.0,
                critical_fields=0,
                good_fields=0,
                fields_below_target=0,
                aliases_approved=0,
                aliases_applied=0,
            )

        performance = perf_analyzer.analyze_all_extractors(events)
        strategies = perf_analyzer.identify_best_strategies(performance)

        found_count = sum(
            1
            for _, s in strategies.items()
            if s.get("success_rate", 0.0) >= self.auto_cfg.target_confidence
        )
        good_count = sum(
            1
            for _, s in strategies.items()
            if s.get("success_rate", 0.0) >= self.auto_cfg.target_success_rate
        )
        critical_count = sum(
            1
            for _, s in strategies.items()
            if 0.0 < s.get("success_rate", 0.0) < self.auto_cfg.critical_field_threshold
        )
        below_target = sum(
            1
            for _, s in strategies.items()
            if s.get("success_rate", 0.0) < self.auto_cfg.target_success_rate
        )

        # Calculate overall success rate
        all_confidence = []
        for _, extractors in performance.items():
            for ext_perf in extractors.values():
                all_confidence.append(ext_perf.get("avg_confidence", 0.0))

        avg_conf = sum(all_confidence) / len(all_confidence) if all_confidence else 0.0

        return IterationMetrics(
            iteration=iter_num,
            timestamp=_utc_now_iso(),
            field_count=len(strategies),
            found_count=found_count,
            success_rate=found_count / len(strategies) if strategies else 0.0,
            avg_confidence=round(avg_conf, 3),
            critical_fields=critical_count,
            good_fields=good_count,
            fields_below_target=below_target,
            aliases_approved=0,
            aliases_applied=0,
        )

    def _print_metrics(self, metrics: IterationMetrics) -> None:
        """Print iteration metrics to console."""
        print(f"      Fields: {metrics.field_count}")
        print(f"      Success rate: {metrics.success_rate:.1%}")
        print(f"      Avg confidence: {metrics.avg_confidence:.3f}")
        print(
            f"      Good (≥{self.auto_cfg.target_success_rate:.0%}): {metrics.good_fields}"
        )
        print(f"      Below target: {metrics.fields_below_target}")
        if metrics.critical_fields > 0:
            print(
                f"      ⚠ Critical (<{self.auto_cfg.critical_field_threshold:.0%}): {metrics.critical_fields}"
            )

    def _evaluate_convergence(self, metrics: IterationMetrics, iter_num: int) -> str:
        """Determine whether to continue iterating."""
        if metrics.success_rate >= self.auto_cfg.target_success_rate:
            return f"[STOP] Target success rate reached ({metrics.success_rate:.1%})"

        if iter_num >= self.auto_cfg.max_iterations:
            return f"[STOP] Max iterations reached"

        if len(self.iteration_history) >= 2:
            prev = self.iteration_history[-2]
            improvement = metrics.success_rate - prev.success_rate
            if improvement < self.auto_cfg.min_improvement_delta:
                return f"[STOP] Improvement plateau (<{self.auto_cfg.min_improvement_delta:.1%})"

        return "[CONTINUE] Improvement needed and budget remaining"

    def _apply_improvements(self, iter_dir: Path) -> tuple[int, int]:
        """Apply approved alias improvements from this iteration."""
        llm_suggester = LLMImprovementSuggester.from_config(self.cfg)
        if not llm_suggester.is_ready():
            return 0, 0

        # Collect raw keys from input
        excel_ext = ExcelNativeExtractor()
        pdf_ext = PdfNativeExtractor()
        raw_keys_by_file: dict[str, list[str]] = {}
        for fpath in list(self.input_dir.glob("**/*.xlsx")) + list(
            self.input_dir.glob("**/*.xls")
        ):
            raw_keys_by_file[fpath.name] = excel_ext.collect_raw_keys(fpath)
        for fpath in self.input_dir.glob("**/*.pdf"):
            raw_keys_by_file[fpath.name] = pdf_ext.collect_raw_keys(fpath)

        # Load current schema and extract strategies
        perf_analyzer = ExtractorPerformanceAnalyzer(iter_dir)
        events = perf_analyzer.load_learning_events()
        if not events:
            return 0, 0

        performance = perf_analyzer.analyze_all_extractors(events)
        strategies = perf_analyzer.identify_best_strategies(performance)

        # Identify low-performing fields
        low_success = [
            f for f, s in strategies.items() if 0.0 < s.get("success_rate", 1.0) < 0.6
        ]
        not_found = [
            f for f, s in strategies.items() if s.get("success_rate", 1.0) == 0.0
        ]
        correction_targets = list(dict.fromkeys(not_found + low_success))

        if not correction_targets:
            return 0, 0

        # Get alias suggestions
        try:
            import json as _json

            schema_fields = _json.loads(
                self.schema_path.read_text(encoding="utf-8")
            ).get("fields", [])
        except (OSError, Exception):
            schema_fields = []

        alias_suggestions = llm_suggester.suggest_aliases(
            schema_fields=schema_fields,
            raw_keys_by_file=raw_keys_by_file,
            not_found_fields=correction_targets,
        )

        if not alias_suggestions:
            return 0, 0

        # Evaluate promotion
        promotion_cfg = AliasPromotionConfig.from_dict(
            self.cfg.get("llm_improvement", {}).get("alias_promotion", {})
        )
        ledger_path = self.output_base_dir / "alias_promotion_state.json"
        promotion = AliasPromotionLedger(ledger_path).evaluate(
            suggestions=alias_suggestions,
            raw_keys_by_file=raw_keys_by_file,
            cfg=promotion_cfg,
        )

        approved = promotion.get("approved", {})
        if not approved:
            return len(alias_suggestions), 0

        # Apply approved aliases
        applied = llm_suggester.apply_alias_suggestions(self.schema_path, approved)

        # Reload config for next iteration
        self.cfg = load_config(self.config_path)

        return len(alias_suggestions), applied

    def _generate_report(self) -> dict[str, Any]:
        """Generate comprehensive iteration report."""
        report = {
            "started_at": _utc_now_iso(),
            "input_dir": str(self.input_dir),
            "schema": str(self.schema_path),
            "config": str(self.config_path),
            "auto_config": asdict(self.auto_cfg),
            "iterations": [asdict(m) for m in self.iteration_history],
            "decisions": self.decisions,
        }

        if self.iteration_history:
            first = self.iteration_history[0]
            last = self.iteration_history[-1]
            report["summary"] = {
                "total_iterations": len(self.iteration_history),
                "max_iterations": self.auto_cfg.max_iterations,
                "fields_processed": last.field_count,
                "initial_success_rate": first.success_rate,
                "final_success_rate": last.success_rate,
                "improvement": last.success_rate - first.success_rate,
                "fields_at_target": last.good_fields,
                "fields_below_target": last.fields_below_target,
                "critical_fields_remaining": last.critical_fields,
                "converged": last.success_rate >= self.auto_cfg.target_success_rate,
            }

        return report
