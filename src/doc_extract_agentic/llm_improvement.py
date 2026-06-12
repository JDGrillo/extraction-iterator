from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


@dataclass
class LLMSuggesterConfig:
    enabled: bool = False
    provider: str = "openai_compatible"
    endpoint: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 30
    max_fields: int = 20


class LLMImprovementSuggester:
    """Optional LLM-based suggestion generator. Safe-by-default."""

    def __init__(self, cfg: LLMSuggesterConfig) -> None:
        self.cfg = cfg

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMImprovementSuggester":
        llm_cfg = config.get("llm_improvement", {})
        endpoint = llm_cfg.get("endpoint") or os.getenv("LLM_IMPROVEMENT_ENDPOINT", "")
        api_key = llm_cfg.get("api_key") or os.getenv("LLM_IMPROVEMENT_API_KEY", "")
        cfg = LLMSuggesterConfig(
            enabled=bool(llm_cfg.get("enabled", False)),
            provider=str(llm_cfg.get("provider", "openai_compatible")),
            endpoint=str(endpoint),
            api_key=str(api_key),
            model=str(llm_cfg.get("model", "gpt-4o-mini")),
            timeout_seconds=int(llm_cfg.get("timeout_seconds", 30)),
            max_fields=int(llm_cfg.get("max_fields", 20)),
        )
        return cls(cfg)

    def is_ready(self) -> bool:
        if not self.cfg.enabled:
            return False
        if self.cfg.provider != "openai_compatible":
            logger.warning("Unsupported LLM provider: %s", self.cfg.provider)
            return False
        if not self.cfg.endpoint or not self.cfg.api_key:
            logger.warning("LLM improvement enabled but endpoint/api_key missing")
            return False
        return True

    def generate_suggestions(
        self,
        strategies: dict[str, Any],
        deterministic_suggestions: dict[str, list[str]],
        discovery_patterns: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        """Return LLM-generated improvement suggestions keyed by field name."""
        if not self.is_ready():
            return {}
        targets: list[dict[str, Any]] = []
        for field_name, strategy in strategies.items():
            if not strategy.get("improvement_needed"):
                continue
            targets.append(
                {
                    "field_name": field_name,
                    "strategy": strategy,
                    "deterministic_suggestions": deterministic_suggestions.get(
                        field_name, []
                    ),
                    "pattern": (discovery_patterns or {})
                    .get("field_patterns", {})
                    .get(field_name, {}),
                }
            )
            if len(targets) >= self.cfg.max_fields:
                break
        if not targets:
            return {}
        system_prompt = (
            "You are an extraction optimization assistant. "
            'Return ONLY valid JSON: {"field_name": ["suggestion1"]}. '
            "Keep each suggestion under 180 characters."
        )
        response_text = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=json.dumps({"targets": targets}),
        )
        return self._parse_dict_of_lists(response_text, max_per_field=5)

    def suggest_aliases(
        self,
        schema_fields: list[dict[str, Any]],
        raw_keys_by_file: dict[str, list[str]],
        not_found_fields: list[str],
    ) -> dict[str, list[str]]:
        """Reason over actual document labels and propose missing aliases.

        Parameters
        ----------
        schema_fields: list of {name, aliases} from the output schema.
        raw_keys_by_file: {filename: [label, ...]} labels the extractors saw.
        not_found_fields: field names with zero or very low extraction success.

        Returns {field_name: [new_alias, ...]} — only net-new aliases.
        """
        if not self.is_ready() or not not_found_fields:
            return {}
        all_raw_keys = sorted({k for keys in raw_keys_by_file.values() for k in keys})
        if not all_raw_keys:
            return {}
        system_prompt = (
            "You are a document extraction expert. "
            "Identify which raw document labels are semantically equivalent to "
            "each target field and should be added as new aliases. "
            'Return ONLY valid JSON: {"field_name": ["new_alias_1"]}. '
            "Only include labels that appear verbatim in raw_document_labels. "
            "Do not invent or paraphrase labels."
        )
        user_payload = {
            "target_fields": [
                {"name": f["name"], "existing_aliases": f.get("aliases", [])}
                for f in schema_fields
                if f["name"] in not_found_fields
            ],
            "raw_document_labels": all_raw_keys[:300],
        }
        response_text = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=json.dumps(user_payload),
        )
        raw = self._parse_dict_of_lists(response_text, max_per_field=20)
        return {
            field: [a.strip().lower() for a in aliases if a.strip()]
            for field, aliases in raw.items()
        }

    def apply_alias_suggestions(
        self,
        schema_path: Path,
        suggestions: dict[str, list[str]],
    ) -> int:
        """Write alias suggestions into the schema JSON file.

        Returns the number of fields that received new aliases.
        """
        if not suggestions:
            return 0
        try:
            with schema_path.open("r", encoding="utf-8") as fh:
                schema = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read schema for alias update: %s", exc)
            return 0
        updated = 0
        for field in schema.get("fields", []):
            name = field.get("name")
            new_aliases = suggestions.get(name)
            if not new_aliases:
                continue
            existing = set(field.get("aliases", []))
            to_add = [a for a in new_aliases if a not in existing]
            if to_add:
                field.setdefault("aliases", []).extend(to_add)
                updated += 1
                logger.info("Added aliases to '%s': %s", name, to_add)
        if updated:
            with schema_path.open("w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=4)
        return updated

    def _parse_dict_of_lists(
        self, text: str, max_per_field: int = 5
    ) -> dict[str, list[str]]:
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return {}
            result: dict[str, list[str]] = {}
            for field_name, items in parsed.items():
                if not isinstance(field_name, str) or not isinstance(items, list):
                    continue
                cleaned = [s for s in items if isinstance(s, str) and s.strip()]
                if cleaned:
                    result[field_name] = cleaned[:max_per_field]
            return result
        except json.JSONDecodeError:
            logger.warning("LLM response was not valid JSON; skipping")
            return {}

    def _chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        try:
            payload = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            }
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                self.cfg.endpoint.rstrip("/") + "/chat/completions",
                method="POST",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.cfg.api_key}",
                },
            )
            with request.urlopen(req, timeout=self.cfg.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                return (
                    parsed.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            logger.warning("LLM call failed; continuing deterministically: %s", exc)
            return ""
