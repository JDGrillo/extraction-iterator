"""
Extractor performance analysis: Learn which extractors work best.

Analyzes all extractors to understand:
- Which extractors find which fields
- Success rates per extractor per field
- Reliability and confidence patterns
- Which extraction strategies are most effective
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from collections import defaultdict

from .llm_improvement import LLMImprovementSuggester

logger = logging.getLogger(__name__)


class ExtractorPerformanceAnalyzer:
    """
    Analyzes performance of all extractors (Excel, PDF, CU) to identify
    which extraction strategies work best for each field.

    Produces:
    - extractor_performance.json: Success rates per extractor/field
    - field_extraction_strategy.json: Best extractors for each field
    - improvement_suggestions.json: How to improve extraction
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.learning_events_path = output_dir / "learning_events.jsonl"

    def load_learning_events(self) -> list[dict]:
        """Load all learning events from JSONL file."""
        if not self.learning_events_path.exists():
            logger.warning("No learning_events.jsonl found")
            return []

        events = []
        with self.learning_events_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        return events

    def analyze_all_extractors(self, events: list[dict]) -> dict[str, Any]:
        """
        Analyze performance of all extractors.

        Returns:
        {
            "field_name": {
                "excel_native": {"success_rate": 0.9, "count": 10, "avg_confidence": 0.95},
                "pdf_native": {"success_rate": 0.7, "count": 10, "avg_confidence": 0.80},
                "azure_cu": {"success_rate": 0.5, "count": 10, "avg_confidence": 0.65},
            }
        }
        """
        performance_by_field: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(
                lambda: {
                    "found_count": 0,
                    "total_count": 0,
                    "confidence_scores": [],
                    "success_rate": 0.0,
                    "avg_confidence": 0.0,
                }
            )
        )

        for event in events:
            for result in event.get("results", []):
                field_name = result.get("field_name")
                status = result.get("status")
                confidence = result.get("confidence", 0.0)
                extractor = result.get("extractor", "unknown")

                if field_name not in performance_by_field:
                    performance_by_field[field_name] = defaultdict(
                        lambda: {
                            "found_count": 0,
                            "total_count": 0,
                            "confidence_scores": [],
                            "success_rate": 0.0,
                            "avg_confidence": 0.0,
                        }
                    )

                perf = performance_by_field[field_name][extractor]

                perf["total_count"] += 1
                perf["confidence_scores"].append(confidence)

                if status == "found":
                    perf["found_count"] += 1

        # Calculate rates
        result = {}
        for field_name, extractors in performance_by_field.items():
            result[field_name] = {}
            for extractor, perf in extractors.items():
                success_rate = (
                    perf["found_count"] / perf["total_count"]
                    if perf["total_count"] > 0
                    else 0.0
                )
                avg_confidence = (
                    sum(perf["confidence_scores"]) / len(perf["confidence_scores"])
                    if perf["confidence_scores"]
                    else 0.0
                )

                result[field_name][extractor] = {
                    "success_rate": round(success_rate, 3),
                    "count": perf["total_count"],
                    "found": perf["found_count"],
                    "avg_confidence": round(avg_confidence, 3),
                }

        return result

    def identify_best_strategies(self, performance: dict[str, Any]) -> dict[str, Any]:
        """
        For each field, identify which extractors work best.

        Returns:
        {
            "field_name": {
                "best_extractor": "excel_native",
                "success_rate": 0.95,
                "alternatives": ["pdf_native"],
                "improvement_needed": false
            }
        }
        """
        strategies = {}

        for field_name, extractors in performance.items():
            if not extractors:
                continue

            # Sort by success rate
            sorted_extractors = sorted(
                extractors.items(),
                key=lambda x: x[1]["success_rate"],
                reverse=True,
            )

            best_name, best_perf = sorted_extractors[0]
            best_rate = best_perf["success_rate"]

            # Find alternatives
            alternatives = [
                name
                for name, perf in sorted_extractors[1:]
                if perf["success_rate"] > 0.5
            ]

            # Determine if improvement needed
            improvement_needed = best_rate < 0.8

            strategies[field_name] = {
                "best_extractor": best_name,
                "success_rate": best_rate,
                "alternatives": alternatives,
                "improvement_needed": improvement_needed,
                "all_performance": extractors,
            }

        return strategies

    def generate_improvement_suggestions(
        self, strategies: dict[str, Any], _discovery_patterns: dict | None = None
    ) -> dict[str, Any]:
        """
        Generate specific suggestions to improve extraction.

        Based on:
        - Current success rates per field
        - What data patterns exist (from discovery)
        - Which extractors work best
        """
        suggestions = {}

        for field_name, strategy in strategies.items():
            if not strategy.get("improvement_needed"):
                continue

            best_extractor = strategy["best_extractor"]
            success_rate = strategy["success_rate"]
            all_perf = strategy.get("all_performance", {})

            # Generate field-specific suggestions
            field_suggestions = []

            if success_rate < 0.5:
                # Very low success - major issue
                field_suggestions.append(
                    f"Field '{field_name}' found in <50% of docs. "
                    f"Check if field actually exists in input files. "
                    f"May need different extraction strategy or may not be consistently present."
                )

                # Check if other extractors do better
                for ext_name, ext_perf in all_perf.items():
                    if ext_perf["success_rate"] > success_rate:
                        field_suggestions.append(
                            f"  → Try using {ext_name} instead "
                            f"(success: {ext_perf['success_rate']:.1%})"
                        )

            elif success_rate < 0.8:
                # Medium success - can improve
                field_suggestions.append(
                    f"Field '{field_name}' extraction can be improved "
                    f"(current: {success_rate:.1%}). "
                    f"Likely issue: field labels vary or data format changes."
                )

                # Suggest using multiple extractors
                if len(strategy["alternatives"]) > 0:
                    field_suggestions.append(
                        f"  → Consider using {best_extractor} as primary, "
                        f"with fallback to {', '.join(strategy['alternatives'])}"
                    )
                else:
                    field_suggestions.append(
                        "  → May need to add custom extraction logic for this field"
                    )

            suggestions[field_name] = field_suggestions

        return suggestions

    def write_performance_report(
        self,
        output_dir: Path,
        discovery_patterns: dict | None = None,
        llm_suggester: LLMImprovementSuggester | None = None,
    ) -> None:
        """Write extractor performance analysis to files."""
        output_dir.mkdir(parents=True, exist_ok=True)

        events = self.load_learning_events()
        if not events:
            logger.warning("No learning events to analyze")
            return

        # Analyze performance
        performance = self.analyze_all_extractors(events)

        # Identify best strategies
        strategies = self.identify_best_strategies(performance)

        # Generate suggestions
        suggestions = self.generate_improvement_suggestions(
            strategies, discovery_patterns
        )

        llm_suggestions: dict[str, list[str]] = {}
        if llm_suggester is not None:
            llm_suggestions = llm_suggester.generate_suggestions(
                strategies=strategies,
                deterministic_suggestions=suggestions,
                discovery_patterns=discovery_patterns,
            )

        merged_suggestions = self._merge_suggestions(suggestions, llm_suggestions)

        # Write reports
        with (output_dir / "extractor_performance.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(performance, f, indent=2)

        with (output_dir / "field_extraction_strategy.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(strategies, f, indent=2)

        with (output_dir / "improvement_suggestions.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(merged_suggestions, f, indent=2)

        with (output_dir / "llm_improvement_suggestions.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(llm_suggestions, f, indent=2)

        logger.info("Performance report written to %s", output_dir)

        # Print summary
        print("\n" + "=" * 70)
        print("EXTRACTOR PERFORMANCE SUMMARY")
        print("=" * 70)

        for field_name, strategy in sorted(strategies.items()):
            rate = strategy["success_rate"]
            status = (
                "✓ GOOD"
                if rate >= 0.9
                else "⚠ NEEDS IMPROVEMENT" if rate >= 0.7 else "✗ CRITICAL"
            )
            print(f"\n{field_name}: {rate:.1%} {status}")
            print(f"  Best: {strategy['best_extractor']}")
            if strategy["alternatives"]:
                print(f"  Alternatives: {', '.join(strategy['alternatives'])}")

            if field_name in merged_suggestions:
                for suggestion in merged_suggestions[field_name]:
                    print(f"  → {suggestion}")

    def _merge_suggestions(
        self,
        deterministic: dict[str, list[str]],
        llm_based: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        """Combine deterministic and LLM suggestions without duplicates."""
        merged: dict[str, list[str]] = {}
        fields = set(deterministic.keys()) | set(llm_based.keys())

        for field_name in fields:
            combined = deterministic.get(field_name, []) + llm_based.get(field_name, [])
            deduped: list[str] = []
            seen: set[str] = set()
            for item in combined:
                key = item.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    deduped.append(item)
            if deduped:
                merged[field_name] = deduped

        return merged
