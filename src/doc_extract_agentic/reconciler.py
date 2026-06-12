from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import ExtractionCandidate, FieldResult, OutputSchema


def _normalize_key(value: str) -> str:
    return " ".join(value.lower().strip().split())


def reconcile_candidates(
    candidates: Iterable[ExtractionCandidate],
    schema: OutputSchema,
    config: dict,
) -> list[FieldResult]:
    alias_map: dict[str, str] = {}
    for field in schema.fields:
        alias_map[_normalize_key(field.name)] = field.name
        for alias in field.aliases:
            alias_map[_normalize_key(alias)] = field.name

    grouped: dict[str, list[ExtractionCandidate]] = defaultdict(list)
    for cand in candidates:
        normalized = _normalize_key(cand.field_name)
        target_field = alias_map.get(normalized)
        if target_field:
            grouped[target_field].append(cand)

    missing_marker = config.get("pipeline", {}).get("missing_value_marker", "not_found")
    threshold = float(config.get("pipeline", {}).get("confidence_threshold", 0.75))

    results: list[FieldResult] = []
    for field in schema.fields:
        field_candidates = sorted(
            grouped.get(field.name, []), key=lambda c: c.confidence, reverse=True
        )
        if field_candidates:
            best = field_candidates[0]
            status = "found" if best.confidence >= threshold else "inferred"
            results.append(
                FieldResult(
                    field_name=field.name,
                    value=best.value,
                    status=status,
                    confidence=best.confidence,
                    extractor=best.extractor,
                    source_ref=best.source_ref,
                )
            )
        else:
            results.append(
                FieldResult(
                    field_name=field.name,
                    value=missing_marker,
                    status="not_found",
                    confidence=0.0,
                    extractor="none",
                    source_ref="",
                )
            )

    return results
