from __future__ import annotations

from pathlib import Path


def pick_extractors_for_file(file_path: Path, config: dict) -> list[str]:
    suffix = file_path.suffix.lower()
    llm_enabled = bool(config.get("local_llm", {}).get("enabled", True))
    fallback_enabled = bool(
        config.get("pipeline", {}).get("deterministic_fallback_enabled", True)
    )

    if suffix in {".xlsx", ".xls"}:
        plan = ["llm_native"] if llm_enabled else ["excel_native"]
        if llm_enabled and fallback_enabled:
            plan.append("excel_native")
    elif suffix == ".pdf":
        plan = ["pdf_native"]
    else:
        plan = []

    return plan
