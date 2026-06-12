from __future__ import annotations

import logging
from typing import Optional

from .models import OutputSchema

logger = logging.getLogger(__name__)


def build_cu_field_prompt(schema: OutputSchema) -> str:
    """
    Build a natural-language instruction prompt for Azure Content Understanding
    based on the schema fields and their aliases.

    This guides CU to focus on the specific fields you care about.
    """
    lines = ["Extract the following fields from the document:"]
    for field in schema.fields:
        aliases_str = ", ".join(field.aliases) if field.aliases else field.name
        required_str = "(REQUIRED)" if field.required else "(optional)"
        lines.append(f"- {field.name}: {aliases_str} {required_str}")
    return "\n".join(lines)


def build_cu_analyzer_config(schema: OutputSchema, config: dict) -> dict:
    """
    Build the Azure CU analyzer configuration from schema and config.

    This includes:
    - extraction prompt (what fields to extract)
    - field aliases for mapping
    - confidence thresholds per field type
    """
    cu_cfg = config.get("azure_content_understanding", {})
    extractor_priors = config.get("extractor_priors", {})

    return {
        "endpoint": cu_cfg.get("endpoint", ""),
        "api_key": cu_cfg.get("api_key", ""),
        "model": cu_cfg.get("model", "prebuilt-document"),
        "prompt": build_cu_field_prompt(schema),
        "field_aliases": {
            field.name: field.aliases + [field.name] for field in schema.fields
        },
        "field_types": {field.name: field.field_type for field in schema.fields},
        "azure_cu_confidence": float(extractor_priors.get("azure_cu", 0.80)),
    }


def validate_cu_config(config: dict) -> tuple[bool, str]:
    """
    Validate that Azure CU configuration is complete and ready to use.

    Returns (is_valid, error_message).
    """
    cu_cfg = config.get("azure_content_understanding", {})
    endpoint = cu_cfg.get("endpoint", "").strip()
    api_key = cu_cfg.get("api_key", "").strip()

    if not endpoint:
        return (
            False,
            "Azure CU endpoint is not configured (azure_content_understanding.endpoint)",
        )
    if not api_key:
        return (
            False,
            "Azure CU API key is not configured (azure_content_understanding.api_key)",
        )

    return True, ""
