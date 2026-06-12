from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CUPerformanceAnalyzer:
    """
    Analyzes Azure Content Understanding performance against other extractors.

    Tracks:
    - Which fields CU missed while other extractors found
    - Which fields CU got right vs wrong
    - Confidence calibration per field
    - Alias effectiveness
    - Extraction patterns and gaps
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.learning_events_path = output_dir / "learning_events.jsonl"
        self.discrepancies_path = output_dir / "discrepancies.csv"

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

    def analyze_cu_vs_others(self, events: list[dict]) -> dict[str, dict[str, Any]]:
        """
        Compare CU performance against other extractors.

        Returns per-field analysis:
        {
            "field_name": {
                "cu_success_rate": 0.8,
                "cu_misses": 3,
                "cu_found_count": 12,
                "other_found_count": 14,
                "missed_by_cu_found_by_others": ["file1.pdf", "file2.xlsx"],
                "confidence_avg": 0.85,
                "confidence_when_wrong": 0.62,
            }
        }
        """
        field_stats: dict[str, dict[str, Any]] = {}

        for event in events:
            file_name = event.get("file", "unknown")
            results = event.get("results", [])

            for result in results:
                field_name = result.get("field_name")
                status = result.get("status")
                confidence = result.get("confidence", 0.0)
                extractor = result.get("extractor", "unknown")

                if field_name not in field_stats:
                    field_stats[field_name] = {
                        "cu_found": 0,
                        "cu_not_found": 0,
                        "cu_confidences": [],
                        "cu_wrong_confidences": [],
                        "other_extractors_found": set(),
                        "missed_by_cu_found_by_others": [],
                        "cu_found_when_others_missed": [],
                        "extractor_successes": {},
                    }

                if extractor == "azure_cu":
                    if status == "found":
                        field_stats[field_name]["cu_found"] += 1
                        field_stats[field_name]["cu_confidences"].append(confidence)
                    else:
                        field_stats[field_name]["cu_not_found"] += 1
                        field_stats[field_name]["cu_wrong_confidences"].append(
                            confidence
                        )
                else:
                    if status == "found":
                        field_stats[field_name]["other_extractors_found"].add(
                            f"{file_name}:{extractor}"
                        )
                        if (
                            extractor
                            not in field_stats[field_name]["extractor_successes"]
                        ):
                            field_stats[field_name]["extractor_successes"][
                                extractor
                            ] = 0
                        field_stats[field_name]["extractor_successes"][extractor] += 1

        # Compute derived metrics
        result = {}
        for field_name, stats in field_stats.items():
            cu_total = stats["cu_found"] + stats["cu_not_found"]
            cu_success_rate = stats["cu_found"] / cu_total if cu_total > 0 else 0.0
            cu_avg_confidence = (
                sum(stats["cu_confidences"]) / len(stats["cu_confidences"])
                if stats["cu_confidences"]
                else 0.0
            )
            cu_avg_wrong_confidence = (
                sum(stats["cu_wrong_confidences"]) / len(stats["cu_wrong_confidences"])
                if stats["cu_wrong_confidences"]
                else 0.0
            )

            result[field_name] = {
                "cu_success_rate": round(cu_success_rate, 3),
                "cu_found_count": stats["cu_found"],
                "cu_not_found_count": stats["cu_not_found"],
                "other_found_count": len(stats["other_extractors_found"]),
                "cu_avg_confidence": round(cu_avg_confidence, 3),
                "cu_avg_confidence_when_wrong": round(cu_avg_wrong_confidence, 3),
                "extractor_wins": stats["extractor_successes"],
            }

        return result

    def identify_cu_gaps(self, events: list[dict]) -> dict[str, Any]:
        """
        Identify fields where CU consistently underperforms.

        Returns:
        {
            "high_priority_gaps": [
                {
                    "field": "invoice_number",
                    "cu_success_rate": 0.5,
                    "gap_size": 8,  # other extractors found 8 times CU missed
                    "recommendation": "Add more aliases or adjust extraction logic"
                }
            ],
            "cu_performing_well": ["total_amount", "invoice_date"],
            "needs_confidence_calibration": ["field_with_overconfidence", ...]
        }
        """
        perf = self.analyze_cu_vs_others(events)

        gaps = []
        performing_well = []
        overconfident = []

        for field_name, stats in perf.items():
            success_rate = stats["cu_success_rate"]
            gap = stats["other_found_count"] - stats["cu_found_count"]

            if success_rate < 0.7 and gap > 0:
                gaps.append(
                    {
                        "field": field_name,
                        "cu_success_rate": success_rate,
                        "gap_size": gap,
                        "other_extractors_beat_cu": stats["other_found_count"],
                        "recommendation": "Add aliases or improve extraction prompt",
                    }
                )
            elif success_rate >= 0.85:
                performing_well.append(field_name)

            # Check for overconfidence (high confidence but wrong)
            wrong_conf = stats["cu_avg_confidence_when_wrong"]
            right_conf = stats["cu_avg_confidence"]
            if wrong_conf > right_conf * 0.8:  # Too confident when wrong
                overconfident.append(
                    {
                        "field": field_name,
                        "confidence_when_wrong": wrong_conf,
                        "confidence_when_right": right_conf,
                        "recommendation": "Lower confidence threshold for this field",
                    }
                )

        return {
            "high_priority_gaps": sorted(
                gaps, key=lambda x: x["gap_size"], reverse=True
            ),
            "cu_performing_well": performing_well,
            "needs_confidence_calibration": overconfident,
            "summary": {
                "total_fields_analyzed": len(perf),
                "fields_needing_improvement": len(gaps),
                "fields_performing_well": len(performing_well),
            },
        }

    def suggest_alias_improvements(self, events: list[dict]) -> dict[str, list[str]]:
        """
        Suggest new aliases based on documents CU missed.

        Cross-reference what field labels appeared in discrepancies
        and suggest adding them as aliases.
        """
        suggestions = {}

        for event in events:
            results = event.get("results", [])

            for result in results:
                if (
                    result.get("extractor") == "azure_cu"
                    and result.get("status") != "found"
                ):
                    field_name = result.get("field_name")
                    if field_name not in suggestions:
                        suggestions[field_name] = []

        return suggestions

    def write_performance_report(self, report: dict, output_path: Path) -> None:
        """Write performance analysis to JSON."""
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
