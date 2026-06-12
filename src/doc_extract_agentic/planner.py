from __future__ import annotations

from pathlib import Path


def pick_extractors_for_file(file_path: Path, config: dict) -> list[str]:
    suffix = file_path.suffix.lower()
    cu_cfg = config.get("azure_content_understanding", {})
    cu_enabled = bool(cu_cfg.get("enabled", False))
    cu_mode = str(cu_cfg.get("mode", "fallback_only"))

    if suffix in {".xlsx", ".xls"}:
        plan = ["excel_native"]
    elif suffix == ".pdf":
        plan = ["pdf_native"]
    else:
        plan = []

    if cu_enabled and cu_mode == "assistive":
        plan.append("azure_cu")

    return plan


def should_invoke_cu_fallback(low_confidence_found: bool, config: dict) -> bool:
    cu_cfg = config.get("azure_content_understanding", {})
    return (
        bool(cu_cfg.get("enabled", False))
        and str(cu_cfg.get("mode", "fallback_only")) == "fallback_only"
        and low_confidence_found
    )
