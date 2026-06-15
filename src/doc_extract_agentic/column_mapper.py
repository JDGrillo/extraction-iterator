"""Deterministic column-to-field mapper using value overlap and name similarity."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", str(v).strip().lower())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _value_overlap(
    col_values: list[str],
    field_values: list[str],
    threshold: float = 0.7,
) -> float:
    """
    Fraction of col_values that fuzzy-match at least one golden field value.
    """
    if not col_values or not field_values:
        return 0.0
    hits = 0
    for cv in col_values:
        if not cv:
            continue
        best = max(
            SequenceMatcher(None, _norm(cv), _norm(fv)).ratio() for fv in field_values
        )
        if best >= threshold:
            hits += 1
    return hits / len(col_values)


def auto_map_columns(
    raw_rows: list[dict[str, str]],
    golden_data: dict[str, dict[str, str]],
    schema_fields: list[str],
    name_weight: float = 0.4,
    value_weight: float = 0.6,
    min_score: float = 0.35,
) -> dict[str, str]:
    """
    Map extracted column names to schema field names using:
      - Name similarity (fuzzy match of header label to field name)
      - Value overlap (do the column's cell values resemble the field's golden values?)

    Returns dict: {extracted_col -> schema_field}
    Columns with no confident match are excluded.
    """
    if not raw_rows:
        return {}

    # Build sets of non-empty values for each extracted column
    all_col_names = list(raw_rows[0].keys())
    col_values: dict[str, list[str]] = {col: [] for col in all_col_names}
    for row in raw_rows:
        for col in all_col_names:
            v = _norm(row.get(col, ""))
            if v:
                col_values[col].append(v)

    # Build sets of non-empty values for each golden field
    field_values: dict[str, list[str]] = {f: [] for f in schema_fields}
    for row in golden_data.values():
        for f in schema_fields:
            v = _norm(row.get(f, ""))
            if v:
                field_values[f].append(v)

    # Score each (col, field) pair
    scores: dict[tuple[str, str], float] = {}
    for col in all_col_names:
        for field in schema_fields:
            ns = _name_similarity(col, field)
            vo = _value_overlap(col_values[col][:20], field_values[field][:40])
            scores[(col, field)] = name_weight * ns + value_weight * vo

    # Greedy assignment: highest-score pairs win; each field/col used at most once
    mapping: dict[str, str] = {}
    assigned_fields: set[str] = set()
    assigned_cols: set[str] = set()

    sorted_pairs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for (col, field), score in sorted_pairs:
        if score < min_score:
            break
        if col in assigned_cols or field in assigned_fields:
            continue
        mapping[col] = field
        assigned_cols.add(col)
        assigned_fields.add(field)
        logger.info(f"Auto-mapped: '{col}' -> '{field}' (score={score:.3f})")

    return mapping
