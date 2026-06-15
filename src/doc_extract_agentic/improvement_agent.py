from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_schema
from .local_llm_client import LocalLLMClient


@dataclass
class ImprovementProposal:
    alias_updates: dict[str, list[str]]
    rationale: str


def propose_alias_updates(
    config: dict[str, Any],
    schema_path: Path,
    failures: list[dict[str, Any]],
    raw_keys_by_file: dict[str, list[str]],
) -> ImprovementProposal:
    if not failures:
        return ImprovementProposal(alias_updates={}, rationale="No failures to improve")

    client = LocalLLMClient.from_config(config)
    if not client.is_ready():
        return ImprovementProposal(
            alias_updates={}, rationale="Local LLM not configured"
        )

    schema = load_schema(schema_path)
    fields = [{"name": f.name, "aliases": f.aliases} for f in schema.fields]

    top_failures = failures[:80]
    raw_key_sample = {
        fname: keys[:60] for fname, keys in list(raw_keys_by_file.items())[:40]
    }

    system_prompt = (
        "You are an extraction improvement agent. "
        "Propose only field alias updates to improve extraction quality. "
        "Return only valid JSON with shape: "
        '{"alias_updates": {"field_name": ["alias"]}, "rationale": "..."}. '
        "Use only aliases that are present in raw_keys_by_file labels. "
        "Keep aliases lowercase and concise."
    )

    user_prompt = json.dumps(
        {
            "fields": fields,
            "failures": top_failures,
            "raw_keys_by_file": raw_key_sample,
        }
    )

    parsed = (
        client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt) or {}
    )
    alias_updates = _normalize_alias_updates(parsed.get("alias_updates", {}))
    rationale = str(parsed.get("rationale", "No rationale provided"))
    return ImprovementProposal(alias_updates=alias_updates, rationale=rationale)


def apply_alias_updates(schema_path: Path, updates: dict[str, list[str]]) -> int:
    if not updates:
        return 0

    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    changed = 0

    for field in payload.get("fields", []):
        field_name = str(field.get("name", ""))
        additions = updates.get(field_name, [])
        if not additions:
            continue

        existing = {str(a).strip().lower() for a in field.get("aliases", [])}
        to_add = [a for a in additions if a not in existing]
        if to_add:
            field.setdefault("aliases", []).extend(to_add)
            changed += 1

    if changed:
        schema_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return changed


def _normalize_alias_updates(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}

    cleaned: dict[str, list[str]] = {}
    for field, aliases in raw.items():
        if not isinstance(field, str) or not isinstance(aliases, list):
            continue
        normalized = []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            val = " ".join(alias.strip().lower().split())
            if val:
                normalized.append(val)
        if normalized:
            cleaned[field] = sorted(set(normalized))
    return cleaned
