from __future__ import annotations

import json
from pathlib import Path

from .models import FieldResult


def append_learning_event(
    output_dir: Path,
    file_name: str,
    extractor_plan: list[str],
    results: list[FieldResult],
) -> None:
    event = {
        "file": file_name,
        "extractor_plan": extractor_plan,
        "results": [
            {
                "field_name": r.field_name,
                "status": r.status,
                "confidence": r.confidence,
                "extractor": r.extractor,
            }
            for r in results
        ],
    }

    with (output_dir / "learning_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
