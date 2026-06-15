from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import pandas as pd


def serialize_excel_for_llm(
    file_path: Path,
    max_sheets: int = 5,
    max_rows_per_sheet: int = 80,
    max_cols_per_sheet: int = 20,
    max_cell_chars: int = 120,
    focus_terms: list[str] | None = None,
) -> str:
    """Serialize workbook content into compact markdown tables for LLM reasoning.

    If focus_terms are provided (schema names/aliases), prefer header-aware,
    schema-relevant column slices to reduce prompt noise.
    """
    try:
        sheets = pd.read_excel(file_path, sheet_name=None, header=None)
    except (OSError, ValueError):
        return ""

    lines: list[str] = [f"Workbook: {file_path.name}"]
    normalized_focus = {_normalize_text(t) for t in (focus_terms or []) if t}

    for idx, (sheet_name, df) in enumerate(sheets.items()):
        if idx >= max_sheets:
            break

        trimmed = _trim_dataframe(df)
        if trimmed.empty:
            continue

        section = _build_sheet_section(
            trimmed,
            max_rows=max_rows_per_sheet,
            max_cols=max_cols_per_sheet,
            max_cell_chars=max_cell_chars,
            focus_terms=normalized_focus,
        )
        if not section:
            continue

        lines.append("")
        lines.append(f"Sheet: {sheet_name}")
        lines.extend(section)

    return "\n".join(lines).strip()


def _build_sheet_section(
    df: pd.DataFrame,
    max_rows: int,
    max_cols: int,
    max_cell_chars: int,
    focus_terms: set[str],
) -> list[str]:
    header_idx, header_scores = _detect_header_row(df, focus_terms)

    if header_idx is None:
        sliced = df.iloc[:max_rows, :max_cols]
        if sliced.empty:
            return []
        col_count = len(sliced.columns)
        lines = []
        header = ["row"] + [f"c{c+1}" for c in range(col_count)]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row_idx in range(len(sliced)):
            row_values = [str(row_idx + 1)]
            for col_idx in range(col_count):
                row_values.append(
                    _clean_cell(sliced.iat[row_idx, col_idx], max_cell_chars)
                )
            lines.append("| " + " | ".join(row_values) + " |")
        return lines

    # Use actual header labels and focus columns if available.
    header_row = df.iloc[header_idx]
    column_indices = _pick_focus_columns(header_scores, max_cols)
    if not column_indices:
        column_indices = list(range(min(len(df.columns), max_cols)))

    col_labels = []
    for col_idx in column_indices:
        label = _clean_cell(header_row.iat[col_idx], max_cell_chars)
        col_labels.append(label or f"c{col_idx + 1}")

    data = df.iloc[header_idx + 1 :].dropna(how="all")
    data = data.iloc[:max_rows]

    lines = [f"Detected header row: {header_idx + 1}"]
    header = ["row"] + col_labels
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for out_row_idx, (_, row) in enumerate(data.iterrows(), start=1):
        row_values = [str(out_row_idx)]
        for col_idx in column_indices:
            row_values.append(_clean_cell(row.iat[col_idx], max_cell_chars))
        lines.append("| " + " | ".join(row_values) + " |")

    return lines


def _detect_header_row(
    df: pd.DataFrame, focus_terms: set[str]
) -> tuple[int | None, dict[int, float]]:
    scan_limit = min(len(df), 25)
    best_idx = None
    best_total = 0.0
    best_scores: dict[int, float] = {}

    for row_idx in range(scan_limit):
        row = df.iloc[row_idx]
        scores: dict[int, float] = {}
        for col_idx, cell in enumerate(row):
            if pd.isna(cell):
                continue
            text = _normalize_text(str(cell))
            if not text:
                continue
            if _looks_numeric_like(text):
                continue

            score = _focus_match_score(text, focus_terms)
            if score >= 0.45:
                scores[col_idx] = score

        unique_hits = len(scores)
        total = sum(scores.values())
        if unique_hits >= 3 and total > best_total:
            best_idx = row_idx
            best_total = total
            best_scores = scores

    return best_idx, best_scores


def _pick_focus_columns(header_scores: dict[int, float], max_cols: int) -> list[int]:
    if not header_scores:
        return []

    # Keep matched columns, plus first two id columns for context when available.
    ranked = sorted(header_scores.items(), key=lambda x: x[1], reverse=True)
    cols = [idx for idx, _ in ranked]
    for idx in [0, 1]:
        if idx not in cols:
            cols.append(idx)

    cols = sorted(cols)
    return cols[:max_cols]


def _focus_match_score(text: str, focus_terms: set[str]) -> float:
    if not focus_terms:
        return 0.6
    if text in focus_terms:
        return 1.0
    matches = difflib.get_close_matches(text, list(focus_terms), n=1, cutoff=0.6)
    if not matches:
        return 0.0
    return difflib.SequenceMatcher(None, text, matches[0]).ratio()


def _normalize_text(value: str) -> str:
    text = value.replace("\n", " ").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _looks_numeric_like(text: str) -> bool:
    stripped = text.replace(",", "").replace(".", "")
    return stripped.isdigit()


def _trim_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    non_empty_rows = df.dropna(how="all")
    if non_empty_rows.empty:
        return non_empty_rows
    non_empty_cols = non_empty_rows.dropna(axis=1, how="all")
    return non_empty_cols


def _clean_cell(value: Any, max_len: int) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text.replace("|", "/")
