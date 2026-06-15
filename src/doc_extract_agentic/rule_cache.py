"""Persistent rule cache for cross-document learning."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RuleCache:
    """
    Persistent cache of learned rules indexed by schema.
    Enables transfer learning: rules learned on one golden dataset
    apply to new documents with the same schema.
    """

    def __init__(self, cache_dir: Path = Path(".cache/rules")):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _schema_fingerprint(self, schema_fields: list[str]) -> str:
        """Create short deterministic fingerprint of schema fields using hash."""
        # Hash the sorted field names to create a short filename-safe fingerprint
        schema_str = "|".join(sorted(schema_fields))
        hash_digest = hashlib.sha256(schema_str.encode()).hexdigest()[:16]
        return hash_digest

    def _get_schema_cache_path(self, schema_fields: list[str]) -> Path:
        """Get cache file path for a given schema."""
        fp = self._schema_fingerprint(schema_fields)
        return self.cache_dir / f"rules_{fp}.json"

    def save_rules(
        self,
        rules: dict[str, Any],
        schema_fields: list[str],
        source_golden_file: str,
        iteration: int,
    ) -> Path:
        """
        Save learned rules to cache with metadata.
        """
        cache_path = self._get_schema_cache_path(schema_fields)

        # Load existing cache if present
        cached_data = {"rules": [], "schema_fields": schema_fields}
        if cache_path.exists():
            try:
                cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cached_data = {"rules": [], "schema_fields": schema_fields}

        # Add metadata to rules
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "source_golden_file": str(source_golden_file),
            "final_iteration": iteration,
            "rules": rules.get("rules", []),
        }

        # Append to history (keep all versions for traceability)
        cached_data.setdefault("history", []).append(entry)
        cached_data["latest"] = entry
        cached_data["schema_fields"] = schema_fields

        # Write cache
        cache_path.write_text(json.dumps(cached_data, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(rules.get('rules', []))} rules to cache: {cache_path}")

        return cache_path

    def load_rules(self, schema_fields: list[str]) -> dict[str, Any]:
        """
        Load all learned rules for a schema from cache.
        Returns deduplicated rules suitable as bootstrap.
        """
        cache_path = self._get_schema_cache_path(schema_fields)

        if not cache_path.exists():
            logger.info(
                f"No cached rules for schema {self._schema_fingerprint(schema_fields)}"
            )
            return {"rules": []}

        try:
            cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
            rules = cached_data.get("latest", {}).get("rules", [])
            logger.info(
                f"Loaded {len(rules)} cached rules for schema "
                f"{self._schema_fingerprint(schema_fields)}"
            )
            return {"rules": rules}
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Failed to load cache from {cache_path}")
            return {"rules": []}

    def deduplicate_rules(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Remove duplicate rules by (field_name, rule_type, description).
        Keeps highest confidence version.
        """
        seen: dict[tuple, dict[str, Any]] = {}

        for rule in rules:
            key = (
                rule.get("field_name"),
                rule.get("rule_type"),
                rule.get("description"),
            )
            existing = seen.get(key)

            if existing is None:
                seen[key] = rule
            elif rule.get("confidence", 0) > existing.get("confidence", 0):
                seen[key] = rule  # Replace with higher confidence

        return list(seen.values())

    def merge_rule_sets(
        self, cached_rules: list[dict[str, Any]], new_rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Merge cached rules with newly learned rules.
        Newer rules override older rules for same (field_name, rule_type).
        """
        merged = {(r.get("field_name"), r.get("rule_type")): r for r in cached_rules}

        # Newer rules override
        for rule in new_rules:
            key = (rule.get("field_name"), rule.get("rule_type"))
            merged[key] = rule

        return list(merged.values())

    def get_cache_stats(self) -> dict[str, Any]:
        """Get statistics about all cached rules."""
        stats = {"total_schemas": 0, "total_rules": 0, "schemas": {}}

        for cache_file in self.cache_dir.glob("rules_*.json"):
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                schema_fp = cache_file.stem.replace("rules_", "")
                rule_count = len(data.get("latest", {}).get("rules", []))
                stats["total_rules"] += rule_count
                stats["schemas"][schema_fp] = {
                    "rule_count": rule_count,
                    "history_entries": len(data.get("history", [])),
                    "latest_timestamp": data.get("latest", {}).get("timestamp"),
                }
                stats["total_schemas"] += 1
            except (json.JSONDecodeError, OSError):
                pass

        return stats
