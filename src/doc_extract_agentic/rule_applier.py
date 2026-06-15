"""Rule application and transformation during extraction."""

from __future__ import annotations

import logging
import re
from typing import Any

from .mapping_learner import LearnedRule

logger = logging.getLogger(__name__)


class RuleApplier:
    """Apply learned transformation rules to extracted data."""

    def __init__(self):
        self.rules: list[LearnedRule] = []

    def load_rules(self, rules: list) -> None:
        """Load a set of rules to apply. Accepts both LearnedRule instances and plain dicts."""
        coerced = []
        for r in rules:
            if isinstance(r, LearnedRule):
                coerced.append(r)
            elif isinstance(r, dict):
                coerced.append(
                    LearnedRule(
                        field_name=str(r.get("field_name", "")),
                        rule_type=str(r.get("rule_type", "")),
                        description=str(r.get("description", "")),
                        rule_config=r.get("config", {}),
                        confidence=float(r.get("confidence", 0.5)),
                        iteration=int(r.get("iteration", 0)),
                    )
                )
        self.rules = coerced
        logger.info(f"Loaded {len(coerced)} transformation rules")

    def apply_to_row(
        self, row: dict[str, str], schema_fields: list[str]
    ) -> dict[str, str]:
        """
        Apply all rules to a single extracted row.
        Returns transformed row with fields mapped to schema.
        """
        # Apply column alias rules
        transformed = dict(row)
        for rule in self.rules:
            if rule.rule_type == "column_alias":
                transformed = self._apply_column_alias(transformed, rule)

        # Apply value transformation rules
        for rule in self.rules:
            if rule.rule_type == "value_transform":
                transformed = self._apply_value_transform(transformed, rule)

        # Map to schema fields (remove unknown columns, add missing ones)
        final_row = {field: transformed.get(field, "") for field in schema_fields}
        return final_row

    def _apply_column_alias(
        self, row: dict[str, str], rule: LearnedRule
    ) -> dict[str, str]:
        """Apply a column alias rule (rename extracted column to schema field)."""
        config = rule.rule_config
        # Accept both 'source_column' and 'source' keys for flexibility
        source_col = config.get("source_column") or config.get("source")
        target_col = rule.field_name

        if not source_col or source_col not in row:
            return row

        # Move value from source to target
        transformed = dict(row)
        if source_col != target_col and source_col in transformed:
            transformed[target_col] = transformed.pop(source_col)

        return transformed

    def _apply_value_transform(
        self, row: dict[str, str], rule: LearnedRule
    ) -> dict[str, str]:
        """Apply a value transformation rule (normalize, extract, reformat)."""
        config = rule.rule_config
        field_name = rule.field_name
        transform_type = config.get(
            "type"
        )  # e.g., "uppercase", "lowercase", "extract_number", "strip"

        if field_name not in row:
            return row

        value = row[field_name]
        transformed = dict(row)

        if transform_type == "uppercase":
            transformed[field_name] = value.upper()
        elif transform_type == "lowercase":
            transformed[field_name] = value.lower()
        elif transform_type == "strip":
            transformed[field_name] = value.strip()
        elif transform_type == "extract_number":
            # Extract first number from value
            match = re.search(r"\d+\.?\d*", value)
            transformed[field_name] = match.group(0) if match else value
        elif transform_type == "extract_alpha":
            # Extract alphabetic characters
            transformed[field_name] = "".join(c for c in value if c.isalpha())
        elif transform_type == "replace":
            old = config.get("old", "")
            new = config.get("new", "")
            transformed[field_name] = value.replace(old, new)
        elif transform_type == "split_first":
            # Split by delimiter and take first part
            delimiter = config.get("delimiter", " ")
            transformed[field_name] = (
                value.split(delimiter)[0] if delimiter in value else value
            )

        return transformed

    def should_skip_row(self, row: dict[str, str]) -> bool:
        """Check if a row should be skipped based on rules."""
        for rule in self.rules:
            if rule.rule_type == "row_skip":
                config = rule.rule_config
                condition = config.get("condition")  # e.g., "all_empty", "starts_with"
                value = config.get("value", "")

                if condition == "all_empty":
                    if all(not v.strip() for v in row.values()):
                        logger.debug("Skipping all-empty row")
                        return True
                elif condition == "starts_with":
                    for field_value in row.values():
                        if field_value.startswith(value):
                            logger.debug(f"Skipping row starting with '{value}'")
                            return True

        return False

    def get_header_row_idx(self, rows: list[dict[str, str]]) -> int | None:
        """Determine header row index based on rules."""
        for rule in self.rules:
            if rule.rule_type == "header_row":
                config = rule.rule_config
                row_idx = config.get("row_index")
                if row_idx is not None and isinstance(row_idx, int):
                    return row_idx

        return None
