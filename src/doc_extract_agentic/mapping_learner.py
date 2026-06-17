"""Autonomous mapping learner that uses LLM to discover transformation rules."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
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
        two_model_cfg = config.get("two_model_learning", {})
        self.two_model_enabled = bool(two_model_cfg.get("enabled", False))
        self.critic_rounds = int(two_model_cfg.get("critic_rounds", 1))
        self.stop_on_no_change = bool(two_model_cfg.get("stop_on_no_change", True))
        self.proposer_max_rules = int(two_model_cfg.get("proposer_max_rules", 8))
        self.critic_max_rules = int(two_model_cfg.get("critic_max_rules", 4))
        self.proposer_min_confidence = float(
            two_model_cfg.get("proposer_min_confidence", 0.5)
        )
        self.critic_min_confidence = float(
            two_model_cfg.get("critic_min_confidence", 0.65)
        )
        proposer_profile = str(two_model_cfg.get("proposer_profile", "proposer"))
        critic_profile = str(two_model_cfg.get("critic_profile", "critic"))
        self.handoff_history_path = Path(
            str(
                two_model_cfg.get(
                    "handoff_history_path", ".cache/handoff/handoff_events.jsonl"
                )
            )
        )

        merged_cfg = {**config, "local_llm": llm_config}
        self.client = LocalLLMClient.from_config(merged_cfg, profile=proposer_profile)
        self.critic_client = LocalLLMClient.from_config(
            merged_cfg, profile=critic_profile
        )
        self.learned_rules: list[LearnedRule] = []

    def learn_from_discrepancies(
        self,
        discrepancy_summary: dict[str, Any],
        extracted_samples: list[dict[str, str]],
        golden_samples: list[dict[str, str]],
        schema_fields: list[str],
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
            discrepancy_summary,
            extracted_samples,
            golden_samples,
            schema_fields,
        )

        logger.info(
            f"Learning rules from {discrepancy_summary.get('misaligned_rows', 0)} misaligned rows"
        )

        # Step 1: proposer model suggests candidate rules.
        response = self.client.chat_json(
            system_prompt=(
                "You are a rule proposer for spreadsheet extraction. "
                "Generate candidate rules aggressively but validly. "
                "Return ONLY raw JSON (no markdown fences, no prose). "
                "Output shape: {\"rules\": [{\"field_name\": str, \"rule_type\": \"column_alias|value_transform\", "
                "\"description\": str, \"config\": object, \"confidence\": float}]}."
            ),
            user_prompt=json.dumps(prompt),
        )

        if not response:
            logger.warning("LLM did not return valid response")
            print("  [LLM] No parseable JSON response returned")
            return []

        print(f"  [Proposer] Parsed response keys: {list(response.keys())}")
        proposed_rules = self._parse_rules(
            response,
            iteration,
            schema_fields,
            min_confidence=self.proposer_min_confidence,
        )
        for rule in proposed_rules:
            if not rule.description.lower().startswith("[proposer]"):
                rule.description = f"[proposer] {rule.description}".strip()
        if not proposed_rules:
            return []

        rules = proposed_rules
        if self.two_model_enabled and self.critic_client.is_ready() and self.critic_rounds > 0:
            for round_idx in range(self.critic_rounds):
                print(f"  [Critic] Reviewing proposer rules (round {round_idx + 1}/{self.critic_rounds})")
                reviewed = self._review_rules_with_critic(
                    rules=rules,
                    prompt_context=prompt,
                    schema_fields=schema_fields,
                    iteration=iteration,
                )
                if not reviewed:
                    print("  [Critic] No review response returned")
                    break
                before = self.export_rules_from_list(rules)
                after = self.export_rules_from_list(reviewed)
                rules = reviewed
                print(f"  [Critic] Review returned {len(rules)} rules")
                if self.stop_on_no_change and before == after:
                    logger.info(
                        "Critic round %d produced no rule change; stopping review loop",
                        round_idx + 1,
                    )
                    break

        self.learned_rules.extend(rules)

        logger.info(f"Learned {len(rules)} rules in iteration {iteration}")
        return rules

    def _review_rules_with_critic(
        self,
        rules: list[LearnedRule],
        prompt_context: dict[str, Any],
        schema_fields: list[str],
        iteration: int,
    ) -> list[LearnedRule]:
        payload = {
            "task": "Act as an adversarial critic. Keep only robust, high-signal rules.",
            "allowed_field_names": schema_fields,
            "context": prompt_context,
            "candidate_rules": self.export_rules_from_list(rules),
            "instructions": [
                "Drop rules that are ambiguous, low-impact, or likely to overfit.",
                "Fix wrong field_name/rule_type/config combinations.",
                f"Keep at most {self.critic_max_rules} total rules.",
                "Prefer precision over recall; drop uncertain defaults.",
                "Return ONLY JSON object with key 'rules'.",
            ],
            "response_format": {
                "rules": [
                    {
                        "field_name": "exact golden field name",
                        "rule_type": "column_alias|value_transform",
                        "description": "one-line explanation",
                        "config": {},
                        "confidence": 0.0,
                    }
                ]
            },
        }

        response = self.critic_client.chat_json(
            system_prompt=(
                "You are a strict reviewer of extraction rules. "
                "You are not a proposer; your default action is to reject weak rules. "
                "Return ONLY raw JSON in shape {\"rules\": [...]} with corrected rules."
            ),
            user_prompt=json.dumps(payload),
        )
        if not response:
            return rules

        parsed = self._parse_rules(
            response,
            iteration,
            schema_fields,
            min_confidence=self.critic_min_confidence,
        )
        if not parsed:
            return rules
        parsed = parsed[: self.critic_max_rules]
        for rule in parsed:
            if not rule.description.lower().startswith("[critic]"):
                clean = rule.description
                if clean.lower().startswith("[proposer]"):
                    clean = clean[len("[proposer]") :].strip()
                rule.description = f"[critic] {clean}".strip()
        logger.info("Critic reviewed %d -> %d rules", len(rules), len(parsed))
        return parsed

    def export_rules_from_list(self, rules: list[LearnedRule]) -> dict[str, Any]:
        rows = []
        for r in rules:
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
        return {"rules": rows}

    def _build_learning_prompt(
        self,
        discrepancy_summary: dict[str, Any],
        extracted_samples: list[dict[str, str]],
        golden_samples: list[dict[str, str]],
        schema_fields: list[str],
    ) -> dict[str, Any]:
        """Build compact prompt focused on actionable alias/transform rules."""
        worst = [
            {"field": str(name), "errors": int(sum(counts.values()))}
            for name, counts in (discrepancy_summary.get("worst_fields") or [])[:3]
        ]

        # Provide several paired examples so the LLM can infer stable patterns.
        paired_examples: list[dict[str, Any]] = []
        for ext, gold in zip(extracted_samples[:4], golden_samples[:4]):
            ext_short = dict(list(ext.items())[:12])
            gold_short = dict(list(gold.items())[:12])
            paired_examples.append(
                {
                    "extracted": ext_short,
                    "golden": gold_short,
                }
            )

        return {
            "task": (
                "Propose candidate rules that improve extracted rows to match golden rows. "
                "Focus on transferable rules that generalize to new documents."
            ),
            "allowed_field_names": schema_fields,
            "worst_fields": worst,
            "paired_examples": paired_examples,
            "handoff_history_hints": self._load_handoff_hints(schema_fields),
            "instructions": [
                "Prefer rule_type='column_alias' when a source column should map to a schema field.",
                "Use rule_type='value_transform' for normalization or filling defaults.",
                "field_name must be one of allowed_field_names.",
                f"Max {self.proposer_max_rules} rules.",
                "Use compact JSON values only; no explanation text outside JSON.",
                "For value_transform, config.type must be one of uppercase/lowercase/strip/extract_number/replace/default_if_empty.",
                "For replace, use keys 'old' and 'new'.",
                "For default_if_empty, use key 'value'.",
                "For column_alias, use config.source_column.",
            ],
            "response_format": {
                "rules": [
                    {
                        "field_name": "exact golden field name",
                        "rule_type": "column_alias|value_transform",
                        "description": "one-line explanation",
                        "config": {},
                        "confidence": 0.0,
                    }
                ]
            },
        }

    def _parse_rules(
        self,
        response: dict[str, Any],
        iteration: int,
        schema_fields: list[str],
        min_confidence: float = 0.0,
    ) -> list[LearnedRule]:
        """Parse and validate LLM rule response."""
        rules = []
        raw_rules = response.get("rules", [])
        allowed_fields = set(schema_fields)
        allowed_rule_types = {"value_transform", "column_alias"}

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

                if not rule.field_name or not rule.rule_type:
                    continue
                if rule.field_name not in allowed_fields:
                    logger.info("Dropping rule for unknown field: %s", rule.field_name)
                    continue
                if rule.rule_type not in allowed_rule_types:
                    logger.info("Dropping unsupported rule type: %s", rule.rule_type)
                    continue
                if not isinstance(rule.rule_config, dict):
                    continue
                if rule.confidence < min_confidence:
                    continue

                if rule.rule_type == "column_alias":
                    source_col = str(rule.rule_config.get("source_column", "")).strip()
                    if not source_col:
                        continue
                elif rule.rule_type == "value_transform":
                    transform_type = str(rule.rule_config.get("type", "")).strip()
                    allowed_types = {
                        "uppercase",
                        "lowercase",
                        "strip",
                        "extract_number",
                        "replace",
                        "default_if_empty",
                    }
                    if transform_type not in allowed_types:
                        continue

                rules.append(rule)
            except (TypeError, ValueError) as exc:
                logger.warning(f"Failed to parse rule: {exc}")
                continue

        return rules

    def _load_handoff_hints(self, schema_fields: list[str]) -> dict[str, Any]:
        """Summarize recent handoff signals for this schema to guide rule proposals."""
        path = self.handoff_history_path
        if not path.exists():
            return {"recent_events": 0, "top_conflict_fields": [], "top_secondary_only_fields": []}

        target_fp = self._schema_fingerprint(schema_fields)
        conflict_counts: dict[str, int] = {}
        secondary_only_counts: dict[str, int] = {}
        seen = 0

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"recent_events": 0, "top_conflict_fields": [], "top_secondary_only_fields": []}

        for line in reversed(lines):
            if seen >= 30:
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(event.get("schema_fingerprint", "")) != target_fp:
                continue

            seen += 1
            model_handoff = event.get("model_handoff") or {}
            for c in model_handoff.get("value_conflicts", []) or []:
                field = str(c.get("field", "")).strip()
                if field:
                    conflict_counts[field] = conflict_counts.get(field, 0) + 1

            for field in model_handoff.get("primary_missing_secondary_has", []) or []:
                if isinstance(field, str) and field.strip():
                    secondary_only_counts[field] = secondary_only_counts.get(field, 0) + 1

        top_conflicts = [
            {"field": field, "count": count}
            for field, count in sorted(
                conflict_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:5]
        ]
        top_secondary = [
            {"field": field, "count": count}
            for field, count in sorted(
                secondary_only_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:5]
        ]
        return {
            "recent_events": seen,
            "top_conflict_fields": top_conflicts,
            "top_secondary_only_fields": top_secondary,
        }

    def _schema_fingerprint(self, schema_fields: list[str]) -> str:
        schema_str = "|".join(sorted(schema_fields))
        return hashlib.sha256(schema_str.encode()).hexdigest()[:16]

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
