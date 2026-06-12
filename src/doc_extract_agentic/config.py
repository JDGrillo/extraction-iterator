from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import OutputSchema, SchemaField


class ConfigError(RuntimeError):
    """Raised when configuration or schema is invalid."""


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be an object")
    return data


def load_schema(schema_path: Path) -> OutputSchema:
    if not schema_path.exists():
        raise ConfigError(f"Schema file not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    fields_raw = data.get("fields", [])
    if not isinstance(fields_raw, list) or not fields_raw:
        raise ConfigError("Schema fields must be a non-empty list")

    fields: list[SchemaField] = []
    for item in fields_raw:
        fields.append(
            SchemaField(
                name=item["name"],
                field_type=item.get("type", "string"),
                required=bool(item.get("required", False)),
                aliases=list(item.get("aliases", [])),
            )
        )

    return OutputSchema(schema_name=data.get("schema_name", "output"), fields=fields)
