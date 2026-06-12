from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib import request
from urllib.error import URLError, HTTPError

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
    """
    Optional LLM-based suggestion generator.

    This component is additive and safe-by-default:
    - If disabled, returns empty suggestions.
    - If misconfigured or unavailable, returns empty suggestions.
    - Core deterministic extraction and suggestions still run.
    """

    def __init__(self, cfg: LLMSuggesterConfig):
        self.cfg = cfg

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMImprovementSuggester":
        llm_cfg = config.get("llm_improvement", {})

        # Allow env vars so secrets are not stored in config files.
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
            logger.warning("LLM improvement is enabled but endpoint/api_key is missing")
            return False
        return True

    def generate_suggestions(
        self,
        strategies: dict[str, Any],
        deterministic_suggestions: dict[str, list[str]],
        discovery_patterns: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        """
        Returns LLM-generated suggestions keyed by field.
        Returns an empty dict when disabled/not ready/on error.
        """
        if not self.is_ready():
            return {}

        # Focus on fields that need improvement to keep token/cost bounded.
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
            "Given field-level performance and discovered patterns, provide concise, "
            "actionable improvement suggestions. Return ONLY valid JSON. "
            'JSON shape: {"field_name": ["suggestion1", "suggestion2"]}. '
            "Keep each suggestion implementation-oriented and under 180 characters."
        )

        user_payload = {
            "targets": targets,
            "constraints": {
                "no_new_dependencies": True,
                "prefer_config_and_alias_changes": True,
                "allow_custom_extractor_logic": True,
            },
        }

        response_text = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=json.dumps(user_payload),
        )
        if not response_text:
            return {}

        try:
            parsed = json.loads(response_text)
            if not isinstance(parsed, dict):
                return {}

            validated: dict[str, list[str]] = {}
            for field_name, suggestions in parsed.items():
                if not isinstance(field_name, str) or not isinstance(suggestions, list):
                    continue
                cleaned = [s for s in suggestions if isinstance(s, str) and s.strip()]
                if cleaned:
                    validated[field_name] = cleaned[:5]
            return validated
        except json.JSONDecodeError:
            logger.warning("LLM suggestions were not valid JSON; skipping")
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

        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            logger.warning(
                "LLM improvement call failed; continuing deterministically: %s", e
            )
            return ""
