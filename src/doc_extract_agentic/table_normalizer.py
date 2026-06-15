"""Extract raw tables from Excel with structure preserved for alignment and learning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class NormalizedTable:
    """Canonical representation of extracted table with provenance."""

    sheet_name: str
    file_name: str
    rows: list[dict[str, Any]]  # row_idx -> {col_name: value, ...}
    col_names: list[str]
    header_row_idx: int | None  # Detected header row index, if any


def normalize_excel_table(
    file_path: Path,
    sheet_name: str | None = None,
    skip_empty_rows: bool = True,
    detect_header_threshold: float = 0.7,
) -> NormalizedTable | None:
    """
    Extract table from Excel with minimal transformation.
    Preserves cell positions and values for alignment learning.
    """
    try:
        sheets = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        if isinstance(sheets, dict):
            # Multiple sheets; use first non-empty
            for sn, df in sheets.items():
                if not df.empty:
                    sheet_name = sn
                    data_df = df
                    break
            else:
                return None
        else:
            # Single sheet
            sheet_name = sheet_name or "Sheet1"
            data_df = sheets
    except (OSError, ValueError):
        return None

    if data_df.empty:
        return None

    # Trim empty rows and columns
    data_df = data_df.dropna(how="all").dropna(axis=1, how="all")
    if data_df.empty:
        return None

    # Detect header row: find the row that looks most like column labels.
    # Strategy: headers are text-only rows with no numeric/financial values.
    # Data rows contain numbers (values, ZIP codes, etc.).
    # We prefer earlier rows and discount rows that are entirely sparse (1 value).
    header_idx = None
    best_header_score = -1.0
    total_rows = len(data_df)
    for rank, (idx, row) in enumerate(data_df.iterrows()):
        non_null = [v for v in row if pd.notna(v) and str(v).strip()]
        if len(non_null) < 2:
            continue
        # Count cells that look purely numeric
        numeric_count = sum(
            1 for v in non_null if re.match(r"^[\d,.\-\$\s]+$", str(v).strip())
        )
        text_ratio = 1.0 - (numeric_count / len(non_null))
        # Penalize rows with very few values unless they are fully text
        density = len(non_null) / max(len(row), 1)
        # Score: text-heavy rows score high; prefer earlier rows slightly
        position_penalty = rank / max(total_rows, 1)
        score = text_ratio * (0.5 + 0.5 * density) - 0.1 * position_penalty
        if score > best_header_score:
            best_header_score = score
            header_idx = idx

    # Generate column names
    if header_idx is not None:
        col_names = [
            str(v).strip() if pd.notna(v) else f"col_{i}"
            for i, v in enumerate(data_df.loc[header_idx])
        ]
        # Select all rows AFTER the header row (by label, not position)
        data_rows = data_df.loc[header_idx + 1 :].reset_index(drop=True)
    else:
        col_names = [f"col_{i}" for i in range(len(data_df.columns))]
        data_rows = data_df.reset_index(drop=True)

    if skip_empty_rows:
        data_rows = data_rows.dropna(how="all")

    # Convert to list of dicts with cleaned values
    rows = []
    for idx, row in data_rows.iterrows():
        row_dict = {}
        for col_idx, col_name in enumerate(col_names):
            value = row.iloc[col_idx] if col_idx < len(row) else None
            # Clean: convert NaN/None to empty string
            if pd.isna(value):
                row_dict[col_name] = ""
            else:
                row_dict[col_name] = str(value).strip()
        rows.append(row_dict)

    return NormalizedTable(
        sheet_name=str(sheet_name),
        file_name=file_path.name,
        rows=rows,
        col_names=col_names,
        header_row_idx=header_idx,
    )


def normalize_golden_data(golden_path: Path) -> dict[str, dict[str, str]]:
    """
    Load golden/ground truth data as dict keyed by row identifier.
    Assumes first column is a unique row key or uses row index.
    """
    try:
        df = pd.read_excel(golden_path).fillna("")
    except (OSError, ValueError):
        return {}

    if df.empty:
        return {}

    golden = {}
    for idx, row in df.iterrows():
        # Use source_file or row_id as key if present, else use index
        if "source_file" in df.columns:
            key = str(row["source_file"]).strip()
        else:
            key = str(idx)
        golden[key] = {col: str(val).strip() for col, val in row.items()}

    return golden
