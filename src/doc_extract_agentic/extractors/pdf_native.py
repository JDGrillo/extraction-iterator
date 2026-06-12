from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from ..models import ExtractionCandidate, OutputSchema
from .base import BaseExtractor


class PdfNativeExtractor(BaseExtractor):
    name = "pdf_native"

    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        _ = config
        candidates: list[ExtractionCandidate] = []

        alias_lookup = {}
        for field in schema.fields:
            for alias in field.aliases + [field.name]:
                alias_lookup[alias.lower().strip()] = field.name

        try:
            reader = PdfReader(str(file_path))
        except (OSError, ValueError):
            return candidates

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            for line in text.splitlines():
                if ":" not in line:
                    continue
                key_part, value_part = line.split(":", 1)
                key = key_part.strip().lower()
                value = value_part.strip()
                if key in alias_lookup and value:
                    candidates.append(
                        ExtractionCandidate(
                            field_name=alias_lookup[key],
                            value=value,
                            confidence=0.82,
                            extractor=self.name,
                            source_ref=f"{file_path.name}:page_{i + 1}",
                        )
                    )

        return candidates
