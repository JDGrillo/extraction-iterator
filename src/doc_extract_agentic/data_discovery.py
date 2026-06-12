"""
Data discovery: Learn what's actually in your input files.

Scans all input documents to understand:
- What structured data exists (key-value pairs, tables)
- Common field names/patterns
- Data types and formats
- Which extractors find what
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from collections import defaultdict, Counter

import pandas as pd
from pypdf import PdfReader

logger = logging.getLogger(__name__)


class DataDiscoverer:
    """
    Analyzes input documents to discover data patterns.

    Outputs:
    - data_profile.json: What fields/values exist in documents
    - field_patterns.json: How each field appears across documents
    - extraction_opportunities.json: Where data is hiding
    """

    def __init__(self, input_dir: Path):
        self.input_dir = input_dir
        self.discovered_fields: dict[str, list[str]] = defaultdict(list)
        self.field_patterns: dict[str, dict[str, Any]] = {}
        self.extractor_findings: dict[str, list[str]] = defaultdict(list)

    def discover(self) -> dict[str, Any]:
        """Scan all input files and discover what data exists."""
        excel_files = list(self.input_dir.glob("**/*.xlsx")) + list(
            self.input_dir.glob("**/*.xls")
        )
        pdf_files = list(self.input_dir.glob("**/*.pdf"))

        logger.info(
            f"Discovering data in {len(excel_files)} Excel + {len(pdf_files)} PDF files"
        )

        # Scan Excel files
        for excel_file in excel_files:
            self._discover_excel(excel_file)

        # Scan PDF files
        for pdf_file in pdf_files:
            self._discover_pdf(pdf_file)

        # Analyze patterns
        self._analyze_patterns()

        return {
            "discovered_fields": dict(self.discovered_fields),
            "field_patterns": self.field_patterns,
            "extractor_findings": dict(self.extractor_findings),
            "summary": {
                "total_unique_fields": len(self.field_patterns),
                "total_discovered_values": sum(
                    len(v) for v in self.discovered_fields.values()
                ),
                "excel_findings_count": len(
                    self.extractor_findings.get("excel_native", [])
                ),
                "pdf_findings_count": len(
                    self.extractor_findings.get("pdf_native", [])
                ),
            },
        }

    def _discover_excel(self, file_path: Path) -> None:
        """Scan Excel file for potential fields and values."""
        try:
            # Read all sheets
            xls = pd.ExcelFile(file_path)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

                # Look for key:value patterns
                for idx, row in df.iterrows():
                    for col_idx, val in enumerate(row):
                        if pd.isna(val):
                            continue

                        val_str = str(val).strip()

                        # Heuristic: key:value pattern
                        if ":" in val_str:
                            parts = val_str.split(":", 1)
                            if len(parts) == 2:
                                key = parts[0].strip().lower()
                                value = parts[1].strip()
                                if key and value and len(key) < 100:
                                    self.discovered_fields[key].append(value)
                                    self.extractor_findings["excel_native"].append(
                                        f"{key}:{value}"
                                    )

                        # Also look at adjacent cells
                        if col_idx + 1 < len(row):
                            next_val = row[col_idx + 1]
                            if not pd.isna(next_val):
                                next_str = str(next_val).strip()
                                key = val_str.lower()
                                if (
                                    key
                                    and next_str
                                    and len(key) < 100
                                    and len(next_str) < 500
                                ):
                                    self.discovered_fields[key].append(next_str)
                                    self.extractor_findings["excel_native"].append(
                                        f"{key}:{next_str}"
                                    )

        except Exception as e:
            logger.warning(f"Error scanning Excel {file_path}: {e}")

    def _discover_pdf(self, file_path: Path) -> None:
        """Scan PDF file for potential fields and values."""
        try:
            reader = PdfReader(file_path)
            for page_idx, page in enumerate(reader.pages):
                text = page.extract_text()
                if not text:
                    continue

                # Look for key:value patterns
                for line in text.split("\n"):
                    line = line.strip()
                    if not line or len(line) > 500:
                        continue

                    if ":" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            key = parts[0].strip().lower()
                            value = parts[1].strip()
                            if key and value and len(key) < 100 and len(value) < 500:
                                self.discovered_fields[key].append(value)
                                self.extractor_findings["pdf_native"].append(
                                    f"{key}:{value}"
                                )

        except Exception as e:
            logger.warning(f"Error scanning PDF {file_path}: {e}")

    def _analyze_patterns(self) -> None:
        """Analyze discovered fields to identify patterns and confidence."""
        for field_name, values in self.discovered_fields.items():
            if not values:
                continue

            # Analyze patterns
            patterns = {
                "count": len(values),
                "unique_count": len(set(values)),
                "examples": list(set(values))[:3],
                "value_types": self._infer_types(values),
                "frequency": Counter(values).most_common(1)[0] if values else None,
            }

            self.field_patterns[field_name] = patterns

    def _infer_types(self, values: list[str]) -> list[str]:
        """Infer data types for values."""
        types = set()
        for val in values:
            if val.replace(".", "").replace(",", "").isdigit():
                types.add("numeric")
            elif "/" in val or "-" in val:
                types.add("date")
            else:
                types.add("text")
        return list(types)

    def write_discovery_report(self, output_dir: Path) -> None:
        """Write discovery results to files."""
        output_dir.mkdir(parents=True, exist_ok=True)

        discovery_result = self.discover()

        # Write discovery report
        with (output_dir / "data_profile.json").open("w", encoding="utf-8") as f:
            json.dump(discovery_result, f, indent=2)

        # Write field patterns
        with (output_dir / "field_patterns.json").open("w", encoding="utf-8") as f:
            json.dump(discovery_result["field_patterns"], f, indent=2)

        # Write extractor findings
        with (output_dir / "extractor_findings.json").open("w", encoding="utf-8") as f:
            json.dump(discovery_result["extractor_findings"], f, indent=2)

        logger.info(f"Discovery report written to {output_dir}")
