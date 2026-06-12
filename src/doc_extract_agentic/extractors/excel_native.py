from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..models import ExtractionCandidate, OutputSchema
from .base import BaseExtractor


class ExcelNativeExtractor(BaseExtractor):
    name = "excel_native"

    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        _ = config
        candidates: list[ExtractionCandidate] = []

        try:
            sheets = pd.read_excel(file_path, sheet_name=None, header=None)
        except (OSError, ValueError):
            return candidates

        alias_lookup = {}
        for field in schema.fields:
            for alias in field.aliases + [field.name]:
                alias_lookup[alias.lower().strip()] = field.name

        for sheet_name, df in sheets.items():
            # Heuristic: look for key/value pairs in adjacent cells.
            for row_idx in range(len(df)):
                for col_idx in range(max(0, len(df.columns) - 1)):
                    left = df.iat[row_idx, col_idx]
                    right = df.iat[row_idx, col_idx + 1]
                    if pd.isna(left) or pd.isna(right):
                        continue
                    key = str(left).strip().lower()
                    if key in alias_lookup:
                        candidates.append(
                            ExtractionCandidate(
                                field_name=alias_lookup[key],
                                value=str(right).strip(),
                                confidence=0.90,
                                extractor=self.name,
                                source_ref=f"{file_path.name}:{sheet_name}!R{row_idx + 1}C{col_idx + 1}",
                            )
                        )

        return candidates
