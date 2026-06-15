"""Autonomous mapping learner that uses LLM to discover transformation rules."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .local_llm_client import LocalLLMClient
from .row_aligner import FieldDiscrepancy

logger = logging.getLogger(__name__)


@dataclass
class LearnedRule:
    """A transformation rule learned from data discrepancies."""

    field_name: str
    rule_type: str  # e.g., "column_alias", "value_transform", "row_skip", "header_row"
    description: str
    rule_config: dict[str, Any]
    confidence: float  # How confident the LLM was (0.0-1.0)
    iteration: int  # Which iteration discovered this


class MappingLearner:
    """Uses LLM to learn transformation rules from row discrepancies."""

    def __init__(self, config: dict[str, Any], llm_config: dict[str, Any]):
        self.config = config
        self.llm_config = llm_config
        self.client = LocalLLMClient.from_config({"local_llm": llm_config})
        self.learned_rules: list[LearnedRule] = []

    def learn_from_discrepancies(
        self,
        discrepancy_summary: dict[str, Any],
        extracted_samples: list[dict[str, str]],
        golden_samples: list[dict[str, str]],
        iteration: int = 1,
    ) -> list[LearnedRule]:
        """
        Use LLM to analyze discrepancies and generate transformation rules.
        """
        if not self.client.is_ready():
            logger.warning("LLM client not ready; skipping rule learning")
            return []

        # Build prompt for LLM
        prompt = self._build_learning_prompt(
            discrepancy_summary, extracted_samples, golden_samples
        )

        logger.info(
            f"Learning rules from {discrepancy_summary.get('misaligned_rows', 0)} misaligned rows"
        )

        # Get LLM response
        response = self.client.chat_json(
            system_prompt=(
                "You are a data mapping expert. Given misaligned extracted vs golden data, "
                "return ONLY a JSON object with a 'rules' array. Each rule must have: "
                "field_name, rule_type (column_alias|value_transform|row_skip|header_row), "
                "description, config, confidence (0-1)."
            ),
            user_prompt=json.dumps(prompt),
        )

        if not response:
            logger.warning("LLM did not return valid response")
            print("  [LLM] No parseable JSON response returned")
            return []

        print(f"  [LLM] Parsed response keys: {list(response.keys())}")
        # Parse and validate rules
        rules = self._parse_rules(response, iteration)
        self.learned_rules.extend(rules)

        logger.info(f"Learned {len(rules)} rules in iteration {iteration}")
        return rules

    def _build_learning_prompt(
        self,
        discrepancy_summary: dict[str, Any],
        extracted_samples: list[dict[str, str]],
        golden_samples: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Build compact prompt focused on value transforms only."""
        worst = [
            {"field": str(name), "errors": int(sum(counts.values()))}
            for name, counts in (discrepancy_summary.get("worst_fields") or [])[:3]
        ]

        # Build side-by-side field comparison for top mismatched fields
        comparisons = []
        for a in (discrepancy_summary.get("worst_fields") or [])[:5]:
            field_name = a[0] if isinstance(a, (list, tuple)) else a.get("field", "")
            comparisons.append({"field": field_name})

        ext_sample = dict(
            list((extracted_samples[0] if extracted_samples else {}).items())[:8]
        )
        gold_sample = dict(
            list((golden_samples[0] if golden_samples else {}).items())[:8]
        )

        return {
            "task": "Propose value_transform rules to normalize field values.",
            "note": "Column-to-field mapping is already done. Only fix value format issues.",
            "worst_fields": worst,
            "example_extracted_row": ext_sample,
            "example_golden_row": gold_sample,
            "instructions": [
                "Only propose rule_type='value_transform'.",
                "field_name must be an exact golden field name.",
                "config must include 'type': one of uppercase/lowercase/strip/extract_number/replace.",
                "For 'replace': include 'pattern' (regex) and 'replacement' in config.",
            ],
            "response_format": {
                "rules": [
                    {
                        "field_name": "exact golden field name",
                        "rule_type": "value_transform",
                        "description": "one-line explanation",
                        "config": {
                            "type": "uppercase|lowercase|strip|extract_number|replace"
                        },
                        "confidence": 0.0,
                    }
                ]
            },
        }

    def _parse_rules(
        self, response: dict[str, Any], iteration: int
    ) -> list[LearnedRule]:
        """Parse and validate LLM rule response."""
        rules = []
        raw_rules = response.get("rules", [])

        if not isinstance(raw_rules, list):
            logger.warning("LLM rules response is not a list")
            return []

        for raw_rule in raw_rules:
            try:
                rule = LearnedRule(
                    field_name=str(raw_rule.get("field_name", "")).strip(),
                    rule_type=str(raw_rule.get("rule_type", "")).strip(),
                    description=str(raw_rule.get("description", "")).strip(),
                    rule_config=raw_rule.get("config", {}),
                    confidence=float(raw_rule.get("confidence", 0.5)),
                    iteration=iteration,
                )

                if rule.field_name and rule.rule_type:
                    rules.append(rule)
            except (TypeError, ValueError) as exc:
                logger.warning(f"Failed to parse rule: {exc}")
                continue

        return rules

    def get_rules_for_field(self, field_name: str) -> list[LearnedRule]:
        """Get all learned rules for a specific field."""
        return [r for r in self.learned_rules if r.field_name == field_name]

    def export_rules(self) -> dict[str, Any]:
        """Export rules for persistence and reuse."""
        rows = []
        for r in self.learned_rules:
            if isinstance(r, LearnedRule):
                rows.append(
                    {
                        "field_name": r.field_name,
                        "rule_type": r.rule_type,
                        "description": r.description,
                        "config": r.rule_config,
                        "confidence": r.confidence,
                        "iteration": r.iteration,
                    }
                )
            elif isinstance(r, dict):
                rows.append(r)
        return {"rules": rows}
