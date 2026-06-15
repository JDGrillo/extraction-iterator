"""Row alignment and discrepancy analysis for autonomous learning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from difflib import SequenceMatcher


@dataclass
class RowAlignment:
    """Result of aligning an extracted row to a golden row."""

    extracted_row_idx: int
    golden_row_key: str | None
    golden_row_idx: int | None
    similarity_score: float
    discrepancies: list[FieldDiscrepancy]


@dataclass
class FieldDiscrepancy:
    """A field that differs between extracted and golden."""

    field_name: str
    extracted_value: str
    golden_value: str
    discrepancy_type: str  # e.g., "missing", "extra", "value_mismatch", "column_shift"


def align_rows(
    extracted_rows: list[dict[str, str]],
    golden_data: dict[str, dict[str, str]],
    field_names: list[str],
) -> list[RowAlignment]:
    """
    Align extracted rows to golden rows and classify discrepancies.
    Uses value-based similarity matching (robust to field name mismatches).
    Returns alignments with detailed field-level mismatches.
    """
    alignments = []

    for extracted_idx, extracted_row in enumerate(extracted_rows):
        best_match_key = None
        best_match_idx = None
        best_score = 0.0
        best_discrepancies = []

        # Try to match this row to a golden row based on content similarity
        for golden_key, golden_row in golden_data.items():
            score, discrepancies = _compare_rows_by_content(
                extracted_row, golden_row, field_names
            )
            if score > best_score:
                best_score = score
                best_match_key = golden_key
                best_match_idx = extracted_idx
                best_discrepancies = discrepancies

        alignments.append(
            RowAlignment(
                extracted_row_idx=extracted_idx,
                golden_row_key=best_match_key,
                golden_row_idx=best_match_idx,
                similarity_score=best_score,
                discrepancies=best_discrepancies,
            )
        )

    return alignments


def _compare_rows_by_content(
    extracted: dict[str, str],
    golden: dict[str, str],
    field_names: list[str],
) -> tuple[float, list[FieldDiscrepancy]]:
    """
    Compare extracted row to golden row based on content/value similarity.
    More robust to field name mismatches; works when columns are unnamed.
    Returns similarity score (0.0-1.0) and list of discrepancies.
    """
    # Get all values from both rows
    extracted_values = [_normalize(v) for v in extracted.values() if _normalize(v)]
    golden_values = [_normalize(v) for v in golden.values() if _normalize(v)]

    # Concatenate for bulk similarity comparison
    extracted_text = " ".join(extracted_values)
    golden_text = " ".join(golden_values)

    # Use sequence matching to find overall similarity
    matcher = SequenceMatcher(None, extracted_text, golden_text)
    bulk_score = matcher.ratio()

    # Penalize if key value (usually first/location) is missing
    # First column often contains the primary identifier
    extracted_first = (
        _normalize(next(iter(extracted.values()), "")) if extracted else ""
    )
    golden_first = _normalize(next(iter(golden.values()), "")) if golden else ""

    if extracted_first and golden_first:
        first_similarity = SequenceMatcher(None, extracted_first, golden_first).ratio()
        # Weight: 70% bulk + 30% first value
        final_score = 0.7 * bulk_score + 0.3 * first_similarity
    else:
        final_score = bulk_score

    # Build discrepancies for reporting (compare available fields)
    discrepancies = []
    for field in field_names:
        ext_val = _normalize(extracted.get(field, ""))
        gold_val = _normalize(golden.get(field, ""))

        if ext_val != gold_val:
            dtype = (
                "missing"
                if not ext_val
                else ("extra" if not gold_val else "value_mismatch")
            )
            discrepancies.append(
                FieldDiscrepancy(
                    field_name=field,
                    extracted_value=extracted.get(field, ""),
                    golden_value=golden.get(field, ""),
                    discrepancy_type=dtype,
                )
            )

    return final_score, discrepancies


def _compare_rows(
    extracted: dict[str, str],
    golden: dict[str, str],
    field_names: list[str],
) -> tuple[float, list[FieldDiscrepancy]]:
    """
    Compare extracted row to golden row field-by-field.
    Returns similarity score (0.0-1.0) and list of discrepancies.
    """
    discrepancies = []
    matched_fields = 0
    total_fields = len(field_names)

    for field in field_names:
        ext_val = _normalize(extracted.get(field, ""))
        gold_val = _normalize(golden.get(field, ""))

        if ext_val == gold_val:
            matched_fields += 1
        else:
            dtype = (
                "missing"
                if not ext_val
                else ("extra" if not gold_val else "value_mismatch")
            )
            discrepancies.append(
                FieldDiscrepancy(
                    field_name=field,
                    extracted_value=extracted.get(field, ""),
                    golden_value=golden.get(field, ""),
                    discrepancy_type=dtype,
                )
            )

    similarity = matched_fields / total_fields if total_fields > 0 else 0.0
    return similarity, discrepancies


def _normalize(value: str) -> str:
    """Normalize string for comparison."""
    return " ".join(value.strip().lower().split())


def summarize_discrepancies(alignments: list[RowAlignment]) -> dict[str, Any]:
    """
    Aggregate discrepancies across all rows.
    Returns summary of error patterns for LLM learning.
    """
    field_error_counts: dict[str, dict[str, int]] = {}
    total_misaligned = 0

    for alignment in alignments:
        if alignment.similarity_score < 1.0:
            total_misaligned += 1
            for disc in alignment.discrepancies:
                if disc.field_name not in field_error_counts:
                    field_error_counts[disc.field_name] = {}
                dtype = disc.discrepancy_type
                field_error_counts[disc.field_name][dtype] = (
                    field_error_counts[disc.field_name].get(dtype, 0) + 1
                )

    # Build summary for LLM
    summary = {
        "total_rows": len(alignments),
        "misaligned_rows": total_misaligned,
        "misalignment_rate": (
            total_misaligned / len(alignments) if alignments else 0.0
        ),
        "field_errors": field_error_counts,
        "worst_fields": sorted(
            field_error_counts.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True,
        )[
            :5
        ],  # Top 5 problematic fields
    }

    return summary
