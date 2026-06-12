from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from .cu_initialization import build_cu_analyzer_config, build_cu_field_prompt
from .cu_performance_analyzer import CUPerformanceAnalyzer
from .models import OutputSchema

logger = logging.getLogger(__name__)


class CUFeedbackLoop:
    """
    Dynamic feedback loop for Azure Content Understanding.

    Analyzes extraction performance and suggests improvements to:
    - Field aliases
    - Extraction prompt
    - Confidence thresholds
    - Extractor prioritization
    """

    def __init__(self, output_dir: Path, schema: OutputSchema, config: dict):
        self.output_dir = output_dir
        self.schema = schema
        self.config = config
        self.analyzer = CUPerformanceAnalyzer(output_dir)

    def analyze_and_improve(self) -> dict:
        """
        Full feedback loop:
        1. Load learning events
        2. Analyze CU performance vs other extractors
        3. Identify gaps and improvements
        4. Suggest schema updates
        5. Generate improved analyzer config

        Returns improvement suggestions.
        """
        events = self.analyzer.load_learning_events()
        if not events:
            logger.warning("No learning events found; skipping feedback loop")
            return {"status": "no_events", "suggestions": []}

        # Analyze performance
        gaps = self.analyzer.identify_cu_gaps(events)
        logger.info(f"CU Performance Analysis: {gaps['summary']}")

        # Identify high-priority fields to improve
        improvements = self._generate_improvements(gaps)

        # Save report
        report = {
            "analysis": gaps,
            "suggested_improvements": improvements,
        }
        report_path = self.output_dir / "cu_feedback_report.json"
        self.analyzer.write_performance_report(report, report_path)
        logger.info(f"Feedback report saved to {report_path}")

        return report

    def _generate_improvements(self, gaps: dict) -> dict[str, Any]:
        """Generate specific improvement suggestions."""
        improvements = {
            "schema_alias_additions": {},
            "confidence_thresholds": {},
            "priority_fields": [],
        }

        # Flag high-priority gaps
        for gap in gaps.get("high_priority_gaps", []):
            field = gap["field"]
            improvements["priority_fields"].append(
                {
                    "field": field,
                    "current_success_rate": gap["cu_success_rate"],
                    "action": "Review and add missing aliases",
                }
            )

            # Suggest lower confidence threshold if CU is unreliable
            if gap["cu_success_rate"] < 0.5:
                improvements["confidence_thresholds"][field] = {
                    "suggested": 0.60,
                    "reason": "CU unreliable for this field; lower threshold to trigger fallback",
                }

        # Confidence calibration
        for calibration in gaps.get("needs_confidence_calibration", []):
            field = calibration["field"]
            improvements["confidence_thresholds"][field] = {
                "suggested": 0.75,
                "reason": "CU overconfident when wrong; lower to be more conservative",
            }

        return improvements

    def apply_improvements_to_config(
        self, improvements: dict, output_config_path: Path
    ) -> None:
        """
        Apply suggested improvements to config YAML.

        Updates:
        - field_aliases for CU
        - confidence thresholds
        - extractor priorities
        """
        updated_config = self.config.copy()

        # Apply confidence threshold adjustments
        if improvements.get("confidence_thresholds"):
            if "cu_field_thresholds" not in updated_config:
                updated_config["cu_field_thresholds"] = {}

            for field, threshold_info in improvements["confidence_thresholds"].items():
                updated_config["cu_field_thresholds"][field] = threshold_info[
                    "suggested"
                ]

        # Save updated config
        with output_config_path.open("w", encoding="utf-8") as f:
            yaml.dump(updated_config, f, default_flow_style=False)

        logger.info(f"Updated config saved to {output_config_path}")

    def generate_improved_analyzer_config(self, output_path: Path) -> None:
        """
        Generate improved CU analyzer configuration based on feedback.
        """
        analyzer_config = build_cu_analyzer_config(self.schema, self.config)

        # Add performance metrics
        events = self.analyzer.load_learning_events()
        if events:
            perf = self.analyzer.analyze_cu_vs_others(events)
            analyzer_config["field_performance"] = perf

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(analyzer_config, f, indent=2)

        logger.info(f"Improved analyzer config saved to {output_path}")
