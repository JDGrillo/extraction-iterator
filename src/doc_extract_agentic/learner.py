from __future__ import annotations

import json
from pathlib import Path

from .models import ExtractionCandidate, FieldResult


def append_learning_event(
    output_dir: Path,
    file_name: str,
    extractor_plan: list[str],
    results: list[FieldResult],
    candidates: list[ExtractionCandidate] | None = None,
) -> None:
    """
    Log extraction event with full detail for learning.

    Args:
        output_dir: Directory to write learning events
        file_name: Source document name
        extractor_plan: Which extractors were used
        results: Final field results
        candidates: (Optional) All candidate values before reconciliation
    """
    event = {
        "file": file_name,
        "extractor_plan": extractor_plan,
        "results": [
            {
                "field_name": r.field_name,
                "value": str(r.value),
                "status": r.status,
                "confidence": r.confidence,
                "extractor": r.extractor,
                "source_ref": r.source_ref,
            }
            for r in results
        ],
    }

    # Optionally include candidate detail (before reconciliation)
    if candidates:
        event["candidates"] = [
            {
                "field_name": c.field_name,
                "value": str(c.value),
                "confidence": c.confidence,
                "extractor": c.extractor,
                "source_ref": c.source_ref,
            }
            for c in candidates
        ]

    with (output_dir / "learning_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def append_extractor_metrics(
    output_dir: Path,
    file_name: str,
    metrics: dict,
) -> None:
    """
    Log extractor-level performance metrics for detailed analysis.

    Example metrics:
    {
        "excel_native": {"fields_found": 3, "avg_confidence": 0.92},
        "azure_cu": {"fields_found": 1, "avg_confidence": 0.65},
    }
    """
    metric_record = {
        "file": file_name,
        "metrics": metrics,
    }

    with (output_dir / "extractor_metrics.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(metric_record) + "\n")
