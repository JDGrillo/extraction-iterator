from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_label(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class AliasPromotionConfig:
    enabled: bool = True
    min_confirmed_runs: int = 2
    min_docs_per_run: int = 2
    min_doc_ratio: float = 0.15

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> "AliasPromotionConfig":
        cfg = cfg or {}
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            min_confirmed_runs=max(1, int(cfg.get("min_confirmed_runs", 2))),
            min_docs_per_run=max(1, int(cfg.get("min_docs_per_run", 2))),
            min_doc_ratio=max(0.0, float(cfg.get("min_doc_ratio", 0.15))),
        )


class AliasPromotionLedger:
    """Track alias evidence across runs and approve only stable suggestions."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path

    def evaluate(
        self,
        suggestions: dict[str, list[str]],
        raw_keys_by_file: dict[str, list[str]],
        cfg: AliasPromotionConfig,
    ) -> dict[str, Any]:
        """Update ledger state and return approved/pending alias suggestions."""
        state = self._load()
        aliases_state = state.setdefault("aliases", {})

        total_docs = max(1, len(raw_keys_by_file))
        keys_by_file = {
            file_name: {_normalize_label(k) for k in keys}
            for file_name, keys in raw_keys_by_file.items()
        }

        approved: dict[str, list[str]] = {}
        pending: dict[str, list[dict[str, Any]]] = {}

        for field_name, aliases in suggestions.items():
            for alias in aliases:
                normalized = _normalize_label(alias)
                if not normalized:
                    continue

                support_docs = sum(
                    1 for labels in keys_by_file.values() if normalized in labels
                )
                support_ratio = support_docs / total_docs
                has_support = (
                    support_docs >= cfg.min_docs_per_run
                    and support_ratio >= cfg.min_doc_ratio
                )

                key = f"{field_name}::{normalized}"
                entry = aliases_state.setdefault(
                    key,
                    {
                        "field": field_name,
                        "alias": normalized,
                        "first_seen": _utc_now_iso(),
                        "last_seen": _utc_now_iso(),
                        "suggested_runs": 0,
                        "confirmed_runs": 0,
                        "promoted": False,
                        "promoted_at": None,
                        "last_support_docs": 0,
                        "last_support_ratio": 0.0,
                    },
                )

                entry["last_seen"] = _utc_now_iso()
                entry["suggested_runs"] = int(entry.get("suggested_runs", 0)) + 1
                entry["last_support_docs"] = support_docs
                entry["last_support_ratio"] = round(support_ratio, 3)

                if has_support:
                    entry["confirmed_runs"] = int(entry.get("confirmed_runs", 0)) + 1

                if not cfg.enabled:
                    approved.setdefault(field_name, []).append(normalized)
                    continue

                if entry.get("promoted", False):
                    approved.setdefault(field_name, []).append(normalized)
                    continue

                if int(entry.get("confirmed_runs", 0)) >= cfg.min_confirmed_runs:
                    entry["promoted"] = True
                    entry["promoted_at"] = _utc_now_iso()
                    approved.setdefault(field_name, []).append(normalized)
                else:
                    pending.setdefault(field_name, []).append(
                        {
                            "alias": normalized,
                            "confirmed_runs": int(entry.get("confirmed_runs", 0)),
                            "required_runs": cfg.min_confirmed_runs,
                            "last_support_docs": support_docs,
                            "last_support_ratio": round(support_ratio, 3),
                        }
                    )

        approved = {
            field_name: sorted(set(aliases))
            for field_name, aliases in approved.items()
            if aliases
        }

        state["last_updated"] = _utc_now_iso()
        state.setdefault("config", {})
        state["config"].update(
            {
                "enabled": cfg.enabled,
                "min_confirmed_runs": cfg.min_confirmed_runs,
                "min_docs_per_run": cfg.min_docs_per_run,
                "min_doc_ratio": cfg.min_doc_ratio,
            }
        )
        self._save(state)

        return {
            "approved": approved,
            "pending": pending,
            "state_path": str(self.ledger_path),
            "summary": {
                "total_suggested_fields": len(suggestions),
                "approved_fields": len(approved),
                "pending_fields": len(pending),
            },
        }

    def _load(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {"aliases": {}, "created_at": _utc_now_iso(), "last_updated": None}
        try:
            with self.ledger_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    data.setdefault("aliases", {})
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"aliases": {}, "created_at": _utc_now_iso(), "last_updated": None}

    def _save(self, data: dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
